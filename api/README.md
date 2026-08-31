# LuthuliScents — Vercel Python Serverless Functions & Courier Guy Integration

This directory contains the Python serverless functions for **LuthuliScents**:
1. `api/create-checkout.py` — Creates a Yoco hosted payment link for direct cart checkout.
2. `api/tcg-track.py` — Proxies **The Courier Guy** parcel tracking for `track.html` securely without exposing API keys.
3. `api/quote-checkout.py` — Fetches real-time shipping quotes from **The Courier Guy** and creates a combined Yoco payment link.

**Runtime:** Python on Vercel Functions. Each `api/*.py` file defining a `handler` inheriting from `http.server.BaseHTTPRequestHandler` is automatically routed to `/api/<filename>`.
All functions use only the Python standard library — zero external pip dependencies required.

---

## 1. The Courier Guy Parcel Tracking (`api/tcg-track.py`)

Proxies The Courier Guy (ShipLogic) tracking API so customers can check live parcel progress on `track.html`.

### Flow
1. The customer opens `track.html` and enters their waybill / tracking reference (e.g. `TCG12345678` or reference from the WhatsApp notification).
2. `js/track.js` calls `GET /api/tcg-track?ref=<tracking_reference>`.
3. The serverless function queries The Courier Guy tracking API (`https://api.shiplogic.com/tracking/shipments?tracking_reference=<ref>&provider_id=1`) with `Authorization: Bearer <COURIER_GUY_API_KEY>`.
4. Normalises the response into a unified timeline:
   ```json
   {
     "ok": true,
     "reference": "TCG12345678",
     "status": "in-transit",
     "status_friendly": "In Transit",
     "courier": "The Courier Guy",
     "service": "Door to Door - Economy",
     "events": [
       {
         "date": "2026-08-31T10:00:00Z",
         "status": "In Transit",
         "location": "Johannesburg Hub",
         "message": "Parcel in transit to delivery depot"
       }
     ]
   }
   ```

---

## 2. Live Rates & Combined Checkout (`api/quote-checkout.py`)

Used from the **Cart** page (`cart.html`) button "Generate & copy Yoco payment link".

### Flow
1. The cart page sends `{ items, delivery: { name, phone, email, address, suburb, city, postal }, successUrl, cancelUrl }`.
2. The function builds parcel dimensions and weights from `CATALOGUE` (50ml perfume bottles: 0.3kg, 10x6x6 cm).
3. Calls The Courier Guy's live rates API (`POST https://api.shiplogic.com/rates`) with your collection address and the buyer's delivery destination.
4. Picks the cheapest / best rate for the route and adds it to the product subtotal.
5. Generates a Yoco hosted checkout link for the exact total (products + actual Courier Guy shipping).
6. Copies the link to clipboard and renders it so the owner can send it to the buyer via WhatsApp.

---

## 3. Direct Cart Checkout (`api/create-checkout.py`)

Creates a Yoco hosted checkout for the customer's total (calculated with flat or free shipping rules).

---

## 4. Environment Variables Setup

Configure these in your local `.env` and in **Vercel Dashboard → Project Settings → Environment Variables**:

| Variable | Required | Description |
| :--- | :--- | :--- |
| `YOCO_SECRET_KEY` | **Yes** | Yoco secret key (`sk_live_...` or `sk_test_...` from Yoco Dashboard → API Keys). |
| `COURIER_GUY_API_KEY` | **Yes** | API key generated in The Courier Guy / ShipLogic portal (**tcg.shiplogic.com** → Settings → API keys). Also accepts `TCG_API_KEY`. |
| `COURIER_GUY_COLLECTION_ADDRESS` | **Yes** | JSON string of your pickup address (Selby / Selby branch, etc.). |
| `COURIER_GUY_BASE_URL` | No | Default: `https://api.shiplogic.com`. |
| `COURIER_GUY_COLLECTION_NAME` | No | Contact person at pickup (e.g. `LuthuliScents`). |
| `COURIER_GUY_COLLECTION_PHONE` | No | Contact phone number at pickup (e.g. `+27692380796`). |
| `COURIER_GUY_COLLECTION_EMAIL` | No | Contact email at pickup. |
| `COURIER_GUY_ACCOUNT_ID` | No | Optional account ID if required by your Courier Guy profile. |

### Example `COURIER_GUY_COLLECTION_ADDRESS` JSON:
```json
{
  "company": "LuthuliScents",
  "street_address": "46 Loveday Street, Trump Center Building, Wemmer",
  "local_area": "Selby",
  "city": "Johannesburg",
  "zone": "Gauteng",
  "country": "ZA",
  "code": "2092"
}
```

---

## 5. How to Get Courier Guy API Keys

1. Sign in to your Courier Guy account at **[tcg.shiplogic.com](https://tcg.shiplogic.com/login)**.
2. In the sidebar, navigate to **Settings** → **API keys**.
3. Click **Create API key**.
4. Copy the generated Key and save it as `COURIER_GUY_API_KEY` in your `.env` and Vercel Environment Variables.

---

## 6. Local Testing with Vercel CLI

```bash
# Set environment variables in your terminal or .env
$env:YOCO_SECRET_KEY="sk_test_..."
$env:COURIER_GUY_API_KEY="your_tcg_api_key_here"
$env:COURIER_GUY_COLLECTION_ADDRESS='{"company":"LuthuliScents","street_address":"46 Loveday Street","local_area":"Selby","city":"Johannesburg","zone":"Gauteng","country":"ZA","code":"2092"}'

# Start Vercel dev server
vercel dev

# Test Courier Guy Tracking
curl "http://localhost:3000/api/tcg-track?ref=TCG12345678" -i

# Test Courier Guy Live Rates & Yoco Link
curl -X POST http://localhost:3000/api/quote-checkout \
  -H "Content-Type: application/json" \
  -d '{"items":[{"key":"rosie","quantity":2}],"delivery":{"name":"Test Buyer","phone":"+27821234567","email":"buyer@example.com","address":"1 Main Rd","city":"Cape Town","postal":"8001"},"successUrl":"https://example.com/success.html","cancelUrl":"https://example.com/cart.html"}'
```