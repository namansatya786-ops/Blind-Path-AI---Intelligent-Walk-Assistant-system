import json
import logging
import math
import os
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from flask import Flask, jsonify, request, send_from_directory
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address


ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
FRONTEND_DIR = os.path.join(ROOT_DIR, "frontend")
NOMINATIM_URL = os.environ.get(
    "NOMINATIM_URL", "https://nominatim.openstreetmap.org/search"
)
VALHALLA_URL = os.environ.get(
    "VALHALLA_URL", "https://valhalla1.openstreetmap.de/route"
)
REQUEST_TIMEOUT = 15
MAX_PROVIDER_RESPONSE_BYTES = 2 * 1024 * 1024
NOMINATIM_MIN_INTERVAL = 1.0
USER_AGENT = "BlindPathAI/1.0 (walking route planning prototype)"
INDIAN_STATES_AND_UTS = frozenset(
    {
        "Andaman and Nicobar Islands",
        "Andhra Pradesh",
        "Arunachal Pradesh",
        "Assam",
        "Bihar",
        "Chandigarh",
        "Chhattisgarh",
        "Dadra and Nagar Haveli and Daman and Diu",
        "Delhi",
        "Goa",
        "Gujarat",
        "Haryana",
        "Himachal Pradesh",
        "Jammu and Kashmir",
        "Jharkhand",
        "Karnataka",
        "Kerala",
        "Ladakh",
        "Lakshadweep",
        "Madhya Pradesh",
        "Maharashtra",
        "Manipur",
        "Meghalaya",
        "Mizoram",
        "Nagaland",
        "Odisha",
        "Puducherry",
        "Punjab",
        "Rajasthan",
        "Sikkim",
        "Tamil Nadu",
        "Telangana",
        "Tripura",
        "Uttar Pradesh",
        "Uttarakhand",
        "West Bengal",
    }
)
_nominatim_lock = threading.Lock()
_last_nominatim_request = 0.0

app = Flask(__name__, static_folder=FRONTEND_DIR, static_url_path="/static")
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024
logging.basicConfig(level=logging.INFO)
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=[],
    storage_uri=os.environ.get("RATELIMIT_STORAGE_URL", "memory://"),
    headers_enabled=True,
)


class ProviderError(Exception):
    """An expected failure from a geocoding or routing service."""


def fetch_json(url, params):
    request_url = "{}?{}".format(url, urlencode(params))
    outbound_request = Request(
        request_url,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
    )
    try:
        with urlopen(outbound_request, timeout=REQUEST_TIMEOUT) as response:
            body = response.read(MAX_PROVIDER_RESPONSE_BYTES + 1)
            if len(body) > MAX_PROVIDER_RESPONSE_BYTES:
                raise ProviderError("A map service returned an oversized response.")
            return json.loads(body.decode("utf-8"))
    except HTTPError as exc:
        app.logger.warning("Provider returned HTTP %s", exc.code)
        raise ProviderError("A map service is temporarily unavailable.") from exc
    except (URLError, TimeoutError) as exc:
        app.logger.warning("Could not reach a configured map service.")
        raise ProviderError(
            "Could not reach a map service. Check your connection and try again."
        ) from exc
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        app.logger.error("Map service returned invalid JSON.")
        raise ProviderError("A map service returned an invalid response.") from exc


def geocode_place(place, state=None):
    global _last_nominatim_request
    search_text = "{}, {}".format(place, state) if state else place
    with _nominatim_lock:
        wait_seconds = NOMINATIM_MIN_INTERVAL - (
            time.monotonic() - _last_nominatim_request
        )
        if wait_seconds > 0:
            time.sleep(wait_seconds)
        try:
            results = fetch_json(
                NOMINATIM_URL,
                {
                    "q": search_text,
                    "format": "jsonv2",
                    "limit": 1,
                    "addressdetails": 1,
                    "countrycodes": "in",
                },
            )
        finally:
            _last_nominatim_request = time.monotonic()
    if not results:
        description = "{}, {}".format(place, state) if state else place
        raise ProviderError(
            "We could not find '{}'. Try adding a city or nearby landmark.".format(
                description
            )
        )
    address = results[0].get("address")
    if not isinstance(address, dict) or not isinstance(
        address.get("country_code"), str
    ):
        raise ProviderError("The location service could not verify this place is in India.")
    if address["country_code"].casefold() != "in":
        raise ProviderError("That place was not found in India. Choose an Indian place.")
    try:
        latitude = float(results[0]["lat"])
        longitude = float(results[0]["lon"])
        if (
            not math.isfinite(latitude)
            or not math.isfinite(longitude)
            or not 6 <= latitude <= 38
            or not 68 <= longitude <= 98
        ):
            raise ValueError("Coordinates are outside India")
        return {
            "lat": latitude,
            "lon": longitude,
            "label": results[0].get("display_name", place),
        }
    except (KeyError, TypeError, ValueError) as exc:
        app.logger.error("Geocoder returned invalid coordinates.")
        raise ProviderError("The location service returned invalid coordinates.") from exc


def decode_polyline(encoded, precision=6):
    """Decode Valhalla's encoded polyline into [longitude, latitude] pairs."""
    coordinates = []
    index = 0
    latitude = 0
    longitude = 0
    factor = 10 ** precision

    while index < len(encoded):
        values = []
        for _ in range(2):
            result = 0
            shift = 0
            while True:
                if index >= len(encoded):
                    raise ValueError("Incomplete encoded route geometry")
                value = ord(encoded[index]) - 63
                index += 1
                result |= (value & 0x1F) << shift
                shift += 5
                if value < 0x20:
                    break
            values.append(~(result >> 1) if result & 1 else result >> 1)
        latitude += values[0]
        longitude += values[1]
        coordinates.append([longitude / factor, latitude / factor])

    return coordinates


def build_route(origin, destination, preferences):
    locations = [
        {"lat": origin["lat"], "lon": origin["lon"]},
        {"lat": destination["lat"], "lon": destination["lon"]},
    ]
    request_body = {
        "locations": locations,
        "costing": "pedestrian",
        "units": "kilometers",
        "directions_options": {"units": "kilometers"},
        "costing_options": {
            "pedestrian": {
                "use_sidewalk": 0.9 if preferences["prefer_sidewalks"] else 0.5,
                "use_hills": 0.2 if preferences["avoid_steep_hills"] else 0.5,
            }
        },
    }
    response = fetch_json(VALHALLA_URL, {"json": json.dumps(request_body)})
    try:
        trip = response["trip"]
        leg = trip["legs"][0]
        summary = leg["summary"]
        geometry = decode_polyline(leg["shape"])
        maneuvers = [
            {
                "instruction": str(item["instruction"]),
                "distance_km": round(float(item.get("length", 0)), 2),
                "duration_minutes": max(
                    0, int(round(float(item.get("time", 0)) / 60))
                ),
            }
            for item in leg["maneuvers"]
        ]
        distance_km = float(summary["length"])
        duration_minutes = int(round(float(summary["time"]) / 60))
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        app.logger.error("Routing service returned an invalid route.")
        raise ProviderError(
            "The routing service could not create a walking route for those places."
        ) from exc

    if not geometry:
        raise ProviderError("The routing service returned an empty route.")

    return {
        "origin": origin,
        "destination": destination,
        "distance_km": round(distance_km, 2),
        "duration_minutes": duration_minutes,
        "geometry": geometry,
        "steps": maneuvers,
    }


@app.get("/")
def home():
    return send_from_directory(FRONTEND_DIR, "index.html")


@app.get("/api/health")
def health():
    return jsonify({"status": "ok"})


@app.after_request
def add_security_headers(response):
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; base-uri 'self'; form-action 'self'; "
        "frame-ancestors 'none'; object-src 'none'; "
        "script-src 'self' https://unpkg.com; "
        "style-src 'self' 'unsafe-inline' https://unpkg.com https://fonts.googleapis.com; "
        "font-src 'self' data: https://fonts.gstatic.com https://unpkg.com; "
        "img-src 'self' data: blob: https://tile.openstreetmap.org "
        "https://*.tile.openstreetmap.org; connect-src 'self'"
    )
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = (
        "camera=(), geolocation=(), microphone=(), payment=(), usb=()"
    )
    if request.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    if request.is_secure:
        response.headers["Strict-Transport-Security"] = "max-age=31536000"
    return response


@app.errorhandler(413)
def request_too_large(_error):
    return jsonify({"error": "The request is too large."}), 413


@app.errorhandler(429)
def too_many_requests(_error):
    response = jsonify(
        {"error": "Too many route requests. Please wait a minute and try again."}
    )
    response.status_code = 429
    response.headers["Retry-After"] = "60"
    return response


@app.post("/api/route")
@limiter.limit("10 per minute")
def route():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"error": "Send route details as a JSON object."}), 400

    origin = payload.get("origin")
    destination = payload.get("destination")
    origin_state = payload.get("origin_state", "")
    destination_state = payload.get("destination_state", "")
    if not isinstance(origin, str) or not origin.strip():
        return jsonify({"error": "Enter a starting place."}), 400
    if not isinstance(destination, str) or not destination.strip():
        return jsonify({"error": "Enter a destination."}), 400
    if len(origin) > 200 or len(destination) > 200:
        return jsonify({"error": "Places must be 200 characters or fewer."}), 400
    for state in (origin_state, destination_state):
        if not isinstance(state, str) or (
            state and state not in INDIAN_STATES_AND_UTS
        ):
            return jsonify(
                {"error": "Choose a valid Indian state or union territory."}
            ), 400
    if origin.strip().casefold() == destination.strip().casefold():
        return jsonify({"error": "Choose two different places."}), 400
    for preference in ("prefer_sidewalks", "avoid_steep_hills"):
        if preference in payload and not isinstance(payload[preference], bool):
            return jsonify(
                {"error": "Walking preferences must be true or false."}
            ), 400

    preferences = {
        "prefer_sidewalks": payload.get("prefer_sidewalks") is True,
        "avoid_steep_hills": payload.get("avoid_steep_hills") is True,
    }
    try:
        start = geocode_place(origin.strip(), origin_state or None)
        end = geocode_place(destination.strip(), destination_state or None)
        return jsonify(build_route(start, end, preferences))
    except ProviderError as exc:
        return jsonify({"error": str(exc)}), 502


if __name__ == "__main__":
    app.run(
        host="127.0.0.1",
        port=int(os.environ.get("PORT", "5000")),
        debug=os.environ.get("FLASK_DEBUG") == "1",
    )