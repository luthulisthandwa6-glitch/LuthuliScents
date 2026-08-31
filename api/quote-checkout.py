"""LuthuliScents — real-time quote + Yoco payment link (Vercel, Python).

POST /api/quote-checkout
  body: {
    items:   [{ "key": "rosie", "quantity": 2 }],
    delivery: {
      name: "Customer Name",
      phone: "+27821234567",
      email: "customer@example.com",
      address: "123 Main Road",
      city: "Johannesburg",
      suburb: "Selby",
      postal: "2092"
    },
    successUrl: "https://<site>/success.html",
    cancelUrl:  "https://<site>/cart.html"
  }
  response (200): {
    paymentLink, checkoutId,
    subtotalCents, shippingCents, totalCents, currency: "ZAR",
    shipping: { provider: "The Courier Guy", service, amount }
  }

Workflow:
  1. Look up each item's price + parcel spec from the embedded catalogue
     (server-side source of truth — the browser never sets the price).
  2. Ask The Courier Guy (ShipLogic) for live courier rates (POST /rates) between
     your collection address and the customer's delivery address.
  3. Take the CHEAPEST / best rate as the shipping fee.
  4. Create a Yoco hosted checkout for subtotal + shipping and return the
     paymentLink so the owner can copy it into WhatsApp or customer can open.

Secrets live only here (Vercel env vars):
  YOCO_SECRET_KEY               required — Yoco secret key (sk_...).
  COURIER_GUY_API_KEY           required — The Courier Guy (ShipLogic) API key.
                                (also checks TCG_API_KEY, SHIPLOGIC_API_KEY).
  COURIER_GUY_BASE_URL          optional — default https://api.shiplogic.com.
  COURIER_GUY_ACCOUNT_ID        optional — numeric account ID if required.
  COURIER_GUY_COLLECTION_ADDRESS required — JSON of your pickup address, keys:
                                company, street_address, local_area, city,
                                zone, country ("ZA"), code (postal).
  COURIER_GUY_COLLECTION_NAME/EMAIL/PHONE - your collection contact.
"""

import json
import os
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler

YOCO_API = "https://payments.yoco.com/api/checkouts"
DEFAULT_TCG_BASE = "https://api.shiplogic.com"
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
    raw = (
        os.environ.get("COURIER_GUY_COLLECTION_ADDRESS")
        or os.environ.get("TCG_COLLECTION_ADDRESS")
        or os.environ.get("SHIPLOGIC_COLLECTION_ADDRESS")
        or ""
    )
    if not raw:
        return None
    try:
        value = json.loads(raw)
    except (ValueError, json.JSONDecodeError):
        return None
    return {
        "type": str(value.get("type") or "business"),
        "company": str(value.get("company") or "LuthuliScents"),
        "street_address": str(value.get("street_address") or ""),
        "local_area": str(value.get("local_area") or value.get("suburb") or ""),
        "city": str(value.get("city") or ""),
        "zone": str(value.get("zone") or value.get("province") or "Gauteng"),
        "country": str(value.get("country") or "ZA"),
        "code": str(value.get("code") or value.get("postal") or value.get("postal_code") or ""),
    }


def _http(url, payload, key, is_json_body=True):
    headers = {
        "Accept": "application/json",
        "User-Agent": UA,
    }
    if key:
        headers["Authorization"] = "Bearer " + key
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
                "description": "50ml perfume",
                "submitted_length_cm": dims[0],
                "submitted_width_cm": dims[1],
                "submitted_height_cm": dims[2],
                "submitted_weight_kg": weight,
            })
    return parcels


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


def _extract_rate_amount(rate_obj):
    """Extract numeric Rand amount from various possible rate schemas in ShipLogic / TCG."""
    if not isinstance(rate_obj, dict):
        return 0.0

    # Direct numeric keys
    for k in ["rate", "rate_total", "total", "rate_amount", "charge", "value", "gross_amount", "net_amount", "amount", "price"]:
        val = rate_obj.get(k)
        if isinstance(val, (int, float)) and val > 0:
            return float(val)
        if isinstance(val, str):
            try:
                num = float(val.replace("R", "").replace(",", "").strip())
                if num > 0:
                    return num
            except (ValueError, TypeError):
                pass

    # Nested rate breakdown in 'rates' list: e.g. base + surcharges
    sub_rates = rate_obj.get("rates")
    if isinstance(sub_rates, list) and sub_rates:
        total = 0.0
        for sr in sub_rates:
            if isinstance(sr, dict):
                v = sr.get("value") or sr.get("charge") or sr.get("amount") or sr.get("rate") or 0
                try:
                    total += float(v)
                except (ValueError, TypeError):
                    pass
        if total > 0:
            return total

    return 0.0


def _parse_tcg_rates(data):
    """Extract list of available rates from The Courier Guy response."""
    candidates = []

    rate_list = []
    if isinstance(data, list):
        rate_list = data
    elif isinstance(data, dict):
        if isinstance(data.get("rates"), list):
            rate_list = data["rates"]
        elif isinstance(data.get("services"), list):
            rate_list = data["services"]
        elif isinstance(data.get("results"), list):
            rate_list = data["results"]
        elif isinstance(data.get("data"), list):
            rate_list = data["data"]
        elif isinstance(data.get("data"), dict) and isinstance(data["data"].get("rates"), list):
            rate_list = data["data"]["rates"]
        else:
            # Single rate object
            rate_list = [data]

    for item in rate_list:
        if not isinstance(item, dict):
            continue

        amount = _extract_rate_amount(item)
        if amount <= 0:
            continue

        svc_name = ""
        svc_level = item.get("service_level")
        if isinstance(svc_level, dict):
            svc_name = svc_level.get("name") or svc_level.get("code") or ""
        elif isinstance(svc_level, str) and svc_level.strip():
            svc_name = svc_level.strip()

        if not svc_name:
            svc_name = (
                item.get("service_level_name")
                or item.get("service_name")
                or item.get("service_level_code")
                or item.get("service_code")
                or item.get("service")
                or item.get("name")
                or "Standard Delivery"
            )

        provider_name = (
            item.get("provider_name")
            or (item.get("provider") if isinstance(item.get("provider"), str) else "")
            or "The Courier Guy"
        )

        candidates.append({
            "provider": provider_name,
            "service": str(svc_name),
            "amount": amount,
        })

    if not candidates:
        return None

    # Pick the cheapest rate
    return min(candidates, key=lambda c: c["amount"])


def _tcg_rates(items, declared_value, city, postal, delivery_contact):
    key = (
        os.environ.get("COURIER_GUY_API_KEY")
        or os.environ.get("TCG_API_KEY")
        or os.environ.get("SHIPLOGIC_API_KEY")
        or ""
    ).strip()
    if not key:
        raise RuntimeError("COURIER_GUY_API_KEY is not configured on Vercel.")

    coll = _collection_address()
    if not coll or not coll.get("code"):
        raise RuntimeError(
            "COURIER_GUY_COLLECTION_ADDRESS env var is not configured (must be JSON with a postal 'code')."
        )

    coll_phone = (
        os.environ.get("COURIER_GUY_COLLECTION_PHONE")
        or os.environ.get("TCG_COLLECTION_PHONE")
        or ""
    ).strip()
    coll_email = (
        os.environ.get("COURIER_GUY_COLLECTION_EMAIL")
        or os.environ.get("TCG_COLLECTION_EMAIL")
        or ""
    ).strip()
    coll_name = (
        os.environ.get("COURIER_GUY_COLLECTION_NAME")
        or os.environ.get("TCG_COLLECTION_NAME")
        or "LuthuliScents"
    ).strip()

    contact = delivery_contact or {}
    contact_phone = str(contact.get("phone") or "").strip()
    contact_email = str(contact.get("email") or "").strip()
    contact_name = str(contact.get("name") or "Customer").strip()
    contact_suburb = str(contact.get("suburb") or city or "").strip()
    contact_address = str(contact.get("address") or "").strip()

    base = (
        os.environ.get("COURIER_GUY_BASE_URL")
        or os.environ.get("TCG_BASE_URL")
        or os.environ.get("SHIPLOGIC_BASE_URL")
        or DEFAULT_TCG_BASE
    ).rstrip("/")

    parcels = _build_parcels(items)

    payload = {
        "collection_address": coll,
        "delivery_address": {
            "type": "residential",
            "company": "",
            "street_address": contact_address,
            "local_area": contact_suburb,
            "city": city or "",
            "zone": str(contact.get("zone") or "Gauteng"),
            "country": "ZA",
            "code": str(postal or ""),
        },
        "parcels": parcels,
        "declared_value": declared_value,
        "opt_in_rates": True,
        "opt_in_time_based_rates": True,
    }

    # Optional account_id if configured
    account_id = os.environ.get("COURIER_GUY_ACCOUNT_ID") or os.environ.get("TCG_ACCOUNT_ID")
    if account_id:
        try:
            payload["account_id"] = int(account_id)
        except ValueError:
            payload["account_id"] = account_id

    # Optional contact metadata
    if coll_name:
        payload["collection_contact_name"] = coll_name
    if coll_phone:
        payload["collection_contact_mobile_number"] = coll_phone
    if coll_email:
        payload["collection_contact_email"] = coll_email
    if contact_name:
        payload["delivery_contact_name"] = contact_name
    if contact_phone:
        payload["delivery_contact_mobile_number"] = contact_phone
    if contact_email:
        payload["delivery_contact_email"] = contact_email

    status, data = _http(base + "/rates", payload, key)
    if not 200 <= status < 300:
        raise RuntimeError("The Courier Guy rates failed: {0}".format(_first_message(data)))

    rate = _parse_tcg_rates(data)
    if not rate:
        dump = json.dumps(data)[:400]
        raise RuntimeError(
            "The Courier Guy returned no usable shipping rates. Detail: {0}".format(dump)
        )
    return rate


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
            "suburb": str(delivery.get("suburb") or "").strip(),
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
            rate = _tcg_rates(items, subtotal_rand, city, postal, delivery_contact)
        except RuntimeError as exc:
            self._json(502, {"error": str(exc)})
            return
        if not rate:
            self._json(
                502,
                {
                    "error": "The Courier Guy returned no shipping rates for this delivery address. "
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
