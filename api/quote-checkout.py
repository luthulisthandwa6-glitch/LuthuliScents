"""LuthuliScents — real-time quote + Yoco payment link (Vercel, Python).

POST /api/quote-checkout
  body: {
    items:   [{ "key": "rosie", "quantity": 2 }],
    successUrl: "https://<site>/success.html",
    cancelUrl:  "https://<site>/cart.html"
  }
  response (200): {
    paymentLink, checkoutId,
    subtotalCents, shippingCents, totalCents, currency: "ZAR",
    shipping: { provider, service, amount }
  }

Workflow:
  1. Look up each item's price + parcel spec from the embedded catalogue
     (server-side source of truth — the browser never sets the price).
  2. Ask Bob Go for live courier rates (POST /rates) between your collection
     address and the customer's delivery address; Bob Go waits up to
     `timeout` ms and returns rates from the same POST.
  3. Take the CHEAPEST successful rate as the shipping fee.
  4. Create a Yoco hosted checkout for subtotal + shipping and return the
     redirectUrl so the owner can copy it into WhatsApp.

Secrets live only here (Vercel env vars):
  YOCO_SECRET_KEY               required — Yoco secret key (sk_...).
  BOBGO_API_KEY                 required — Bob Go bearer token.
  BOBGO_BASE_URL                optional — default sandbox; use production for live.
  BOBGO_COLLECTION_ADDRESS      required — JSON of your pickup address, keys:
                                company, street_address, local_area, city,
                                zone, country ("ZA"), code (postal).
  BOBGO_COLLECTION_NAME/EMAIL/PHONE - your collection contact.
"""

import json
import os
import time
import uuid
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler

YOCO_API = "https://payments.yoco.com/api/checkouts"
DEFAULT_BOBGO_BASE = "https://api.sandbox.bobgo.co.za/v2"
UA = "LuthuliScents/2.0 (+https://luthuli-scents.vercel.app)"

# key -> { price (Rand), weight_kg, dims (cm) } — mirrors products.json.
CATALOGUE = {
    "rosie":          {"price": 180.00, "weight_kg": 0.3, "dims": (10, 6, 6)},
    "sweetapple":     {"price": 180.00, "weight_kg": 0.3, "dims": (10, 6, 6)},
    "apple-blaze":    {"price": 180.00, "weight_kg": 0.3, "dims": (10, 6, 6)},
    "woody":          {"price": 180.00, "weight_kg": 0.3, "dims": (10, 6, 6)},
    "noir-velvet":    {"price": 180.00, "weight_kg": 0.3, "dims": (10, 6, 6)},
    "sweetapple-rose": {"price": 180.00, "weight_kg": 0.3, "dims": (10, 6, 6)},
    "signature-gold": {"price": 180.00, "weight_kg": 0.3, "dims": (10, 6, 6)},
}


def _collection_address():
    raw = os.environ.get("BOBGO_COLLECTION_ADDRESS", "")
    if not raw:
        return None
    try:
        value = json.loads(raw)
    except (ValueError, json.JSONDecodeError):
        return None
    return {
        "company": str(value.get("company") or ""),
        "street_address": str(value.get("street_address") or ""),
        "local_area": str(value.get("local_area") or ""),
        "city": str(value.get("city") or ""),
        "zone": str(value.get("zone") or ""),
        "country": str(value.get("country") or "ZA"),
        "code": str(value.get("code") or ""),
    }


def _http(url, payload, key, is_json_body=True):
    headers = {
        "Authorization": "Bearer " + key,
        "Accept": "application/json",
        "User-Agent": UA,
    }
    if is_json_body:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8") if is_json_body else None,
        method="POST" if is_json_body else "GET",
        headers=headers,
    )
    try:
        with urllib.request.urlopen(req, timeout=45) as res:
            status = res.status
            raw = res.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as err:
        status = err.code
        raw = err.read().decode("utf-8", "replace")
    except Exception as exc:
        raise RuntimeError("Network error: {0}".format(exc))
    try:
        return status, json.loads(raw)
    except (ValueError, json.JSONDecodeError):
        return status, {"raw": raw}


def _build_parcels(items):
    parcels = []
    for item in items:
        key = item.get("key", "")
        qty = int(item.get("quantity") or 1)
        spec = CATALOGUE.get(key) or {}
        dims = spec.get("dims") or (10, 6, 6)
        weight = float(spec.get("weight_kg") or 0.3)
        for _ in range(max(qty, 1)):
            parcels.append({
                "description": CATALOGUE.get(key, {}).get("name") or "50ml perfume",
                "submitted_length_cm": dims[0],
                "submitted_width_cm": dims[1],
                "submitted_height_cm": dims[2],
                "submitted_weight_kg": weight,
            })
    return parcels


def _cheapest_rate(response):
    candidates = []
    for prr in response.get("provider_rate_requests") or []:
        if prr.get("status") != "success":
            continue
        provider = prr.get("provider_name") or prr.get("provider_slug") or "Courier"
        for r in prr.get("responses") or []:
            if not isinstance(r, dict):
                continue
            amount = float(r.get("rate_amount") or 0)
            if amount <= 0:
                continue
            svc = r.get("service_level") if isinstance(r.get("service_level"), dict) else {}
            candidates.append({
                "provider": provider,
                "service": svc.get("name") or r.get("service_level_code") or "Standard",
                "amount": amount,
            })
    if not candidates:
        return None
    return min(candidates, key=lambda c: c["amount"])


def _bobgo_rates(items, declared_value, city, postal, delivery_contact):
    key = os.environ.get("BOBGO_API_KEY", "")
    if not key:
        raise RuntimeError("BOBGO_API_KEY is not configured on Vercel.")
    coll = _collection_address()
    if not coll or not coll.get("code"):
        raise RuntimeError(
            "BOBGO_COLLECTION_ADDRESS env var is not configured (must be JSON with a postal 'code')."
        )
    coll_phone = os.environ.get("BOBGO_COLLECTION_PHONE", "").strip()
    coll_email = os.environ.get("BOBGO_COLLECTION_EMAIL", "").strip()
    if not coll_phone and not coll_email:
        raise RuntimeError(
            "Bob Go requires a collection contact. Set BOBGO_COLLECTION_PHONE or "
            "BOBGO_COLLECTION_EMAIL on Vercel."
        )
    contact = delivery_contact or {}
    contact_phone = str(contact.get("phone") or "").strip()
    contact_email = str(contact.get("email") or "").strip()
    if not contact_phone and not contact_email:
        raise RuntimeError(
            "Bob Go requires the customer's phone or email to quote shipping. "
            "Please ask the customer for their contact details."
        )
    base = (os.environ.get("BOBGO_BASE_URL") or DEFAULT_BOBGO_BASE).rstrip("/")
    payload = {
        "collection_address": coll,
        "delivery_address": {
            "company": "",
            "street_address": str(contact.get("address") or ""),
            "local_area": city or "",
            "city": city or "",
            "zone": "",
            "country": "ZA",
            "code": str(postal or ""),
        },
        "parcels": _build_parcels(items),
        "collection_contact_full_name": os.environ.get("BOBGO_COLLECTION_NAME", "LuthuliScents"),
        "collection_contact_mobile_number": coll_phone,
        "collection_contact_email": coll_email,
        "delivery_contact_full_name": str(contact.get("name") or "Customer"),
        "delivery_contact_mobile_number": contact_phone,
        "delivery_contact_email": contact_email,
        "declared_value": declared_value,
        "timeout": 30000,
    }
    status, data = _http(base + "/rates", payload, key)
    if not 200 <= status < 300:
        raise RuntimeError("Bob Go rates failed: {0}".format(_first_message(data)))
    rate = _cheapest_rate(data)
    if not rate:
        dump = json.dumps(data)[:400]
        raise RuntimeError(
            "Bob Go returned no usable shipping rates. Detail: {0}".format(dump)
        )
    return rate


def _first_message(data):
    if isinstance(data, dict):
        return (
            data.get("message")
            or data.get("description")
            or data.get("error")
            or data.get("raw")
            or json.dumps(data)[:300]
        )
    return str(data)[:300]


def _yoco_checkout(total_cents, success_url, cancel_url, order_id):
    key = os.environ.get("YOCO_SECRET_KEY", "")
    if not key:
        raise RuntimeError("YOCO_SECRET_KEY is not configured on Vercel.")
    payload = {
        "amount": total_cents,
        "currency": "ZAR",
        "successUrl": success_url,
        "cancelUrl": cancel_url,
        "metadata": {"source": "luthuliscents-static", "orderId": order_id},
        "externalId": order_id,
    }
    status, data = _http(YOCO_API, payload, key)
    if not 200 <= status < 300:
        raise RuntimeError(
            "Yoco checkout failed: {0}".format(
                _first_message(data) or ("status " + str(status))
            )
        )
    if not data.get("redirectUrl"):
        raise RuntimeError("Yoco returned no redirectUrl")
    return data.get("redirectUrl"), data.get("id")


def _abs_url(value):
    if isinstance(value, str) and value.startswith(("http://", "https://")):
        return value
    return "https://luthuli-scents.vercel.app/cart.html"


class handler(BaseHTTPRequestHandler):
    def _cors(self):
        origin = self.headers.get("Origin", "*")
        self.send_header("Access-Control-Allow-Origin", origin)
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
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

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", 0) or 0)
            body = json.loads(self.rfile.read(length).decode("utf-8"))
        except (ValueError, json.JSONDecodeError):
            self._json(400, {"error": "Invalid JSON body."})
            return

        items = [i for i in (body.get("items") or []) if isinstance(i, dict)]
        if not items:
            self._json(400, {"error": "Cart is empty."})
            return
        if any(i.get("key") not in CATALOGUE for i in items):
            self._json(400, {"error": "Unknown product in cart."})
            return

        delivery = body.get("delivery") if isinstance(body.get("delivery"), dict) else {}
        postal = str(delivery.get("postal") or "").strip()
        city = str(delivery.get("city") or "").strip()
        if not postal:
            self._json(400, {"error": "Delivery postal code is required."})
            return
        delivery_contact = {
            "name": str(delivery.get("name") or "").strip(),
            "phone": str(delivery.get("phone") or "").strip(),
            "email": str(delivery.get("email") or "").strip(),
            "address": str(delivery.get("address") or "").strip(),
        }

        subtotal = sum(
            int(round(CATALOGUE[i["key"]]["price"] * int(i.get("quantity") or 1) * 100))
            for i in items
        )
        subtotal_rand = subtotal / 100.0
        success_url = _abs_url(body.get("successUrl"))
        cancel_url = _abs_url(body.get("cancelUrl"))
        order_id = "LS-{0}".format(int(time.time() * 1000))

        try:
            rate = _bobgo_rates(items, subtotal_rand, city, postal, delivery_contact)
        except RuntimeError as exc:
            self._json(502, {"error": str(exc)})
            return
        if not rate:
            self._json(
                502,
                {
                    "error": "Bob Go returned no shipping rates for this delivery address. "
                             "Please ask the owner to arrange a courier quote."
                },
            )
            return

        shipping_cents = int(round(rate["amount"] * 100))
        total_cents = subtotal + shipping_cents

        try:
            link, checkout_id = _yoco_checkout(total_cents, success_url, cancel_url, order_id)
        except RuntimeError as exc:
            self._json(502, {"error": str(exc)})
            return

        self._json(
            200,
            {
                "paymentLink": link,
                "checkoutId": checkout_id,
                "currency": "ZAR",
                "subtotalCents": subtotal,
                "shippingCents": shipping_cents,
                "totalCents": total_cents,
                "shipping": rate,
                "orderId": order_id,
            },
        )
