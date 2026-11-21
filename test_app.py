import unittest
from unittest.mock import patch

import app as application


def encode_polyline(points, precision=6):
    previous_latitude = 0
    previous_longitude = 0
    encoded = []
    factor = 10 ** precision

    for latitude, longitude in points:
        scaled_latitude = round(latitude * factor)
        scaled_longitude = round(longitude * factor)
        for value in (
            scaled_latitude - previous_latitude,
            scaled_longitude - previous_longitude,
        ):
            value = ~(value << 1) if value < 0 else value << 1
            while value >= 0x20:
                encoded.append(chr((0x20 | (value & 0x1F)) + 63))
                value >>= 5
            encoded.append(chr(value + 63))
        previous_latitude = scaled_latitude
        previous_longitude = scaled_longitude

    return "".join(encoded)


class RouteApiTests(unittest.TestCase):
    def setUp(self):
        self.client = application.app.test_client()

    def test_health_endpoint(self):
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json, {"status": "ok"})
        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(response.headers["X-Frame-Options"], "DENY")
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertIn("frame-ancestors 'none'", response.headers["Content-Security-Policy"])

    def test_rejects_missing_origin(self):
        with patch("app.fetch_json") as fetch:
            response = self.client.post(
                "/api/route", json={"origin": " ", "destination": "Library"}
            )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json["error"], "Enter a starting place.")
        fetch.assert_not_called()

    def test_returns_decoded_pedestrian_route(self):
        route_shape = encode_polyline([(18.52, 73.85), (15.49, 73.82)])
        provider_responses = [
            [
                {
                    "lat": "18.52",
                    "lon": "73.85",
                    "display_name": "Station, Maharashtra",
                    "address": {"country_code": "in"},
                }
            ],
            [
                {
                    "lat": "15.49",
                    "lon": "73.82",
                    "display_name": "Library, Goa",
                    "address": {"country_code": "in"},
                }
            ],
            {
                "trip": {
                    "legs": [
                        {
                            "summary": {"length": 1.5, "time": 900},
                            "shape": route_shape,
                            "maneuvers": [
                                {
                                    "instruction": "Head east.",
                                    "length": 0.4,
                                    "time": 240,
                                }
                            ],
                        }
                    ]
                }
            },
        ]
        with patch("app.fetch_json", side_effect=provider_responses) as fetch:
            response = self.client.post(
                "/api/route",
                json={
                    "origin": "Station",
                    "destination": "Library",
                    "origin_state": "Maharashtra",
                    "destination_state": "Goa",
                    "prefer_sidewalks": True,
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["distance_km"], 1.5)
        self.assertEqual(response.json["duration_minutes"], 15)
        self.assertEqual(
            response.json["geometry"],
            [[73.85, 18.52], [73.82, 15.49]],
        )
        self.assertEqual(response.json["steps"][0]["instruction"], "Head east.")
        self.assertEqual(fetch.call_count, 3)
        self.assertEqual(fetch.call_args_list[0].args[1]["countrycodes"], "in")
        self.assertEqual(fetch.call_args_list[0].args[1]["q"], "Station, Maharashtra")
        self.assertEqual(fetch.call_args_list[1].args[1]["q"], "Library, Goa")

    def test_rejects_unknown_indian_state(self):
        with patch("app.fetch_json") as fetch:
            response = self.client.post(
                "/api/route",
                json={
                    "origin": "Pune",
                    "destination": "Goa",
                    "origin_state": "Atlantis",
                },
            )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json["error"], "Choose a valid Indian state or union territory."
        )
        fetch.assert_not_called()

    def test_rejects_search_result_outside_india(self):
        with patch(
            "app.fetch_json",
            return_value=[
                {
                    "lat": "51.5",
                    "lon": "-0.12",
                    "display_name": "London",
                    "address": {"country_code": "gb"},
                }
            ],
        ):
            response = self.client.post(
                "/api/route",
                json={"origin": "London", "destination": "Mumbai"},
            )
        self.assertEqual(response.status_code, 502)
        self.assertEqual(
            response.json["error"],
            "That place was not found in India. Choose an Indian place.",
        )

    def test_reports_provider_failure(self):
        with patch(
            "app.fetch_json",
            side_effect=application.ProviderError("Map service unavailable."),
        ):
            response = self.client.post(
                "/api/route",
                json={"origin": "Station", "destination": "Library"},
            )
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json["error"], "Map service unavailable.")

    def test_rejects_non_boolean_preferences(self):
        response = self.client.post(
            "/api/route",
            json={
                "origin": "Station",
                "destination": "Library",
                "prefer_sidewalks": "yes",
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json["error"], "Walking preferences must be true or false."
        )

    def test_limits_route_requests_by_client_ip(self):
        with patch("app.fetch_json") as fetch:
            for _ in range(10):
                response = self.client.post(
                    "/api/route",
                    json={"origin": "", "destination": "Library"},
                    environ_base={"REMOTE_ADDR": "192.0.2.44"},
                )
                self.assertEqual(response.status_code, 400)
            response = self.client.post(
                "/api/route",
                json={"origin": "", "destination": "Library"},
                environ_base={"REMOTE_ADDR": "192.0.2.44"},
            )
        self.assertEqual(response.status_code, 429)
        self.assertEqual(
            response.json["error"],
            "Too many route requests. Please wait a minute and try again.",
        )
        self.assertEqual(response.headers["Retry-After"], "60")
        fetch.assert_not_called()


if __name__ == "__main__":
    unittest.main()
