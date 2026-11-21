# BlindPath AI — Intelligent Walking Path Assistant

A user-friendly walking-route planning prototype with an accessible web interface, turn-by-turn directions, and optional spoken instructions.

## What it does

- Looks up typed addresses, cities, and landmarks across India with OpenStreetMap's Nominatim service.
- Offers state and union-territory selectors for both trip ends; city and landmark names remain free-text so the app is not limited to a fixed city list.
- Restricts geocoding to India, verifies the returned country, and opens the map fitted to India.
- Requests pedestrian routes and turn instructions from the public Valhalla routing service.
- Displays the route on an OpenStreetMap map.
- Lets users prefer sidewalks and gentler hills when the routing data supports them.
- Offers browser-based spoken directions and keyboard-accessible controls.
- Reports unavailable locations and service errors instead of showing a made-up route.
- Applies browser security headers, limits route requests, and does not save trip history.

This is a prototype, not a certified navigation or safety system. It cannot verify current sidewalk conditions, crossings, obstacles, lighting, construction, or whether a route is suitable for a particular person's needs. Always check your surroundings and use your usual mobility aids and trusted guidance.

## Privacy and security

- Typed places are sent to public OpenStreetMap Nominatim (search) and Valhalla (routing) services. Those providers' policies apply; this app does not save trip history. Avoid sensitive destinations if you are not comfortable sharing them.
- Route requests are limited to 10 per minute per client IP. Avoid logging request bodies or forwarding client IP headers from untrusted proxies.
- The default rate-limit counter is in memory and resets when the app restarts. For a multi-worker deployment, set `RATELIMIT_STORAGE_URL` to a shared store such as Redis.
- Serve the app over HTTPS in production. Keep Flask debug mode off, protect the server, and configure trusted proxy handling before relying on client IP rate limits.
- This prototype has no accounts and does not need to collect names, phone numbers, or contact details. Do not enter sensitive personal information in place fields.

## Run locally

1. Install Python 3.10 or later.
2. Open a terminal in this project folder.
3. Create and activate a virtual environment:

   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```

4. Install dependencies:

   ```powershell
   python -m pip install -r requirements.txt
   ```

5. Start the server:

   ```powershell
   python app.py
   ```

6. Open [http://127.0.0.1:5000](http://127.0.0.1:5000) in a browser.

The map tiles and route lookup require an internet connection. Browser speech is provided by the browser's built-in speech synthesis support.

## API

- `GET /api/health` — basic application health check.
- `POST /api/route` — geocodes the origin and destination, then returns a pedestrian route.

Example request:

```json
{
  "origin": "Pune",
  "origin_state": "Maharashtra",
  "destination": "Panaji",
  "destination_state": "Goa",
  "prefer_sidewalks": true,
  "avoid_steep_hills": false
}
```

The app spaces public Nominatim geocoding requests by at least one second within a single server process. Multiple server processes do not share that geocoding throttle, so use a managed service or centralized throttle for production. The public providers have their own usage limits and availability; this prototype is intended for small-scale use. For production use, review provider policies and arrange service attribution and monitoring.

## Project layout

```text
app.py                 Flask app and route API
frontend/
  index.html           Accessible planner interface
  styles.css           Responsive visual design
  app.js               Map, route results, and spoken directions
requirements.txt       Python dependencies
tests/
  test_app.py          Backend API and security checks
```
