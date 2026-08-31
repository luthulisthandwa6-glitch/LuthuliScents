"""LuthuliScents — Vercel Python serverless function.

GET /api/tcg-track?ref=<tracking_reference>   (also accepts ?tracking_reference=)

Proxies The Courier Guy (ShipLogic) tracking so customers can check their parcel on the static
site without exposing COURIER_GUY_API_KEY. Returns a normalised:
  {
    ok, reference, status, status_friendly,
    courier, service, order_number, type,
    events: [{ date, status, location, message }]
  }

Env:
  COURIER_GUY_API_KEY   required — API key / token from The Courier Guy portal
                        (tcg.shiplogic.com -> Settings -> API keys).
                        Also accepts fallback TCG_API_KEY or SHIPLOGIC_API_KEY.
  COURIER_GUY_BASE_URL  optional — default https://api.shiplogic.com.
                        Also accepts fallback TCG_BASE_URL.

Vercel Python entrypoint: the `handler` class below is routed to /api/tcg-track.
"""

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler

DEFAULT_BASE_URL = "https://api.shiplogic.com"


def _pick_field(obj, keys):
    if not isinstance(obj, dict):
        return ""
    for key in keys:
        value = obj.get(key)
        if value is not None and str(value).strip() != "":
            return value
    return ""


def _normalize_events(events):
    if not isinstance(events, list) or not events:
        return []
    normalised = []
    for event in events:
        if not isinstance(event, dict):
            continue
        item = {
            "date": _pick_field(event, ["date", "time", "event_date", "created_at", "timestamp"]),
            "status": _pick_field(event, ["status_friendly", "status", "event_type", "type", "title"]),
            "location": _pick_field(event, ["location", "address", "city", "branch_name", "depot", "hub"]),
            "message": _pick_field(event, ["message", "description", "text", "notes", "comment"]),
        }
        if item["date"] or item["status"] or item["message"]:
            normalised.append(item)
    return normalised


def _pick_status(payload):
    status = _pick_field(payload, ["status_friendly", "status"])
    if status:
        return str(status)
    events = payload.get("tracking_events") or payload.get("checkpoints") or payload.get("tracking_steps")
    if isinstance(events, list) and events:
        last = events[-1]
        if isinstance(last, dict):
            return str(_pick_field(last, ["status_friendly", "status", "title"]) or "in-progress")
    return "in-progress"


def _extract_events(payload):
    if not isinstance(payload, dict):
        return []
    
    # 1. Direct tracking_events
    events = payload.get("tracking_events")
    if isinstance(events, list) and events:
        return events
    
    # 2. Checkpoints
    checkpoints = payload.get("checkpoints")
    if isinstance(checkpoints, list) and checkpoints:
        return checkpoints

    # 3. Tracking steps
    steps = payload.get("tracking_steps")
    if isinstance(steps, list) and steps:
        step_events = []
        for s in steps:
            if isinstance(s, dict):
                step_events.append({
                    "date": s.get("date") or s.get("completed_at") or "",
                    "status": s.get("title") or s.get("name") or s.get("status") or "",
                    "location": s.get("location") or "",
                    "message": s.get("description") or s.get("message") or "",
                })
        return step_events

    # 4. Nested in parcels
    parcels = payload.get("parcels")
    if isinstance(parcels, list) and parcels and isinstance(parcels[0], dict):
        p_events = parcels[0].get("tracking_events") or parcels[0].get("checkpoints")
        if isinstance(p_events, list) and p_events:
            return p_events

    return []


class handler(BaseHTTPRequestHandler):
    def _cors(self):
        origin = self.headers.get("Origin", "*")
        self.send_header("Access-Control-Allow-Origin", origin)
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _json(self, code, payload):
        data = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self._cors()
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        if self.command != "OPTIONS":
            self.wfile.write(data)

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
        track_ref = (query.get("ref") or query.get("tracking_reference") or query.get("waybill") or [""])[0].strip()
        if not track_ref:
            self._json(400, {"error": "Missing tracking reference (?ref=...)."})
            return

        key = (
            os.environ.get("COURIER_GUY_API_KEY")
            or os.environ.get("TCG_API_KEY")
            or os.environ.get("SHIPLOGIC_API_KEY")
            or ""
        ).strip()

        base = (
            os.environ.get("COURIER_GUY_BASE_URL")
            or os.environ.get("TCG_BASE_URL")
            or os.environ.get("SHIPLOGIC_BASE_URL")
            or DEFAULT_BASE_URL
        ).rstrip("/")

        # Construct request to The Courier Guy (ShipLogic) tracking endpoint
        url = base + "/tracking/shipments?tracking_reference=" + urllib.parse.quote(track_ref) + "&provider_id=1"

        headers = {
            "Accept": "application/json",
            "User-Agent": "LuthuliScents/2.0 (+https://luthuli-scents.vercel.app)",
        }
        if key:
            headers["Authorization"] = "Bearer " + key

        req = urllib.request.Request(url, headers=headers)

        try:
            with urllib.request.urlopen(req, timeout=30) as res:
                status = res.status
                text = res.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as err:
            status = err.code
            text = err.read().decode("utf-8", "replace")
        except Exception as exc:
            self._json(502, {"error": "Could not reach The Courier Guy: {0}".format(exc)})
            return

        data = {}
        if text:
            try:
                data = json.loads(text)
            except (ValueError, json.JSONDecodeError):
                data = {"raw": text}

        if status == 404:
            self._json(404, {
                "error": "No tracking record found for reference '{0}'. Please check the waybill or tracking reference and try again.".format(track_ref)
            })
            return

        if not 200 <= status < 300:
            err_msg = (
                data.get("message")
                or data.get("error")
                or data.get("description")
                or "The Courier Guy tracking failed"
            )
            if isinstance(err_msg, str) and err_msg.startswith("could not find"):
                self._json(404, {"error": "No shipment found with reference '{0}'.".format(track_ref)})
                return
            self._json(status, {"error": err_msg, "detail": data})
            return

        # ShipLogic tracking returns { shipments: [ ... ], tracking_steps: [ ... ] } or a direct object
        shipments = data.get("shipments") if isinstance(data.get("shipments"), list) else []
        if shipments and isinstance(shipments[0], dict):
            payload = shipments[0]
        elif isinstance(data, dict) and (data.get("tracking_reference") or data.get("tracking_events") or data.get("status")):
            payload = data
        else:
            payload = data

        raw_events = _extract_events(payload)
        events = _normalize_events(raw_events)

        ref = (
            _pick_field(payload, ["short_tracking_reference", "tracking_reference", "waybill_number", "id"])
            or track_ref
        )
        status_val = payload.get("status") or _pick_status(payload)
        status_friendly = payload.get("status_friendly") or str(status_val).replace("-", " ").title()
        service_name = (
            _pick_field(payload, ["service_level_name", "service_level", "service"])
            or "The Courier Guy Standard"
        )
        order_num = _pick_field(payload, ["custom_tracking_reference", "order_number", "customer_reference"])

        self._json(
            200,
            {
                "ok": True,
                "reference": ref,
                "status": status_val,
                "status_friendly": status_friendly,
                "courier": "The Courier Guy",
                "service": service_name,
                "order_number": order_num,
                "type": "shipment",
                "events": events,
                "raw": data,
            },
        )
