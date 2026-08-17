# LuthuliScents — Yoco checkout function (Vercel, Python)

One serverless function that turns the customer's **actual cart** into a Yoco
hosted payment link. It is the only place your Yoco secret key lives — it must
never go in the static site's HTML/JS.

**Runtime:** Python. [+`api/create-checkout.py`]. Each `api/*.py` file with a
`handler` class inheriting from `http.server.BaseHTTPRequestHandler` becomes a
Vercel Function routed to `/api/<filename>` (see
[Vercel Python runtime docs](https://vercel.com/docs/functions/runtimes/python#python-entrypoints)).
Both functions use only the Python standard library — no pip deps.

## Flow

1. The static site on GitHub Pages posts `{ total, items, email, successUrl,
   cancelUrl }` to this function via `js/checkout.js`.
2. This function calls Yoco's Checkout API
   (`POST payments.yoco.com/api/checkouts`) with
   `Authorization: Bearer <YOCO_SECRET_KEY>` and an amount in **cents**.
3. Yoco returns a `redirectUrl`; this function responds with it; the browser
   redirects the customer to pay on Yoco's hosted page.

## Deploy

Create the project in the Vercel dashboard (import your GitHub repo, Framework
Preset = **Other**). This repo has no framework, so Vercel serves the static
files at root and treats `api/*.py` as serverless functions.

Set the environment variable (never commit it):
- Vercel dashboard → Project → Settings → Environment Variables
- Name `YOCO_SECRET_KEY`, value `sk_live_...` (live) or `sk_test_...` (test).
- Check the deployment scope you use (Production / Preview / Development).

Deploy via `vercel --prod` or push to your `main` branch if you enabled
Git integration.

> Only `requirements.txt` is installed into the Function bundle. If you want
> to slim the bundle, add a `vercel.json` `functions` rule with `excludeFiles`
> (docs above) so static assets like `img/` don't ship into each Function.

## Point the static site at your function

After deploying you get a URL like `https://<project>.vercel.app`. The
checkout endpoint is `https://<project>.vercel.app/api/create-checkout`.

Edit the constant in `build.py`:
```python
YOCO_CHECKOUT_API = "https://<project>.vercel.app/api/create-checkout"
```
then regenerate the site data:
```bash
python build.py products
```

## Yoco live keys / domain verification

Yoco requires you to verify the domain that redirects back after payment
(`success.html`/`cart.html`, i.e. your GitHub Pages hostname) before live keys
activate. In the Yoco app: **Sales → Payment Gateway → Verified domains**.
Use `sk_test_...` while building, `sk_live_...` for production.

> **Key gotcha — publishable vs secret keys.** Yoco publishable keys start
> with `pk_` (e.g. `pk_live_...`) and are only for the browser. `api/create-checkout.py`
> calls Yoco's API with `Authorization: Bearer <YOCO_SECRET_KEY>`, so it needs the
> **secret** key, which starts with `sk_`. If a `pk_` key is in `.env`/Vercel under
> `YOCO_SECRET_KEY`, checkout will fail. Fix: Yoco dashboard → **Settings → API keys**
> → **Secret key** (the `sk_...` value, not the publishable `pk_...` one).

## Local testing

```bash
# run the functions locally with a key present
set YOCO_SECRET_KEY=sk_test_your_key_here   # PowerShell
vercel dev
curl -X POST http://localhost:3000/api/create-checkout \
  -H "Content-Type: application/json" \
  -d '{"total":54000,"items":[{"name":"Rosie","quantity":2}],"successUrl":"https://example.com/success.html","cancelUrl":"https://example.com/cart.html"}'
```

## Security notes

- `YOCO_SECRET_KEY` is a secret — set it as a Vercel env var, never commit it.
- Amounts are validated server-side (min R2.00). Confirm actual receipt via
  Yoco's `payment.succeeded` webhook in production, not the `successUrl`.

---

# LuthuliScents — Bob Go tracking function (Vercel, Python)

Second serverless function: `api/bob-track.py` proxies Bob Go's courier
tracking so the static Track page (`track.html`) can show live parcel status
without ever exposing your `BOBGO_API_KEY` to the browser.

## Flow

1. The customer opens `track.html` and enters the waybill / tracking
   reference you gave them (Bob Go issues it when you book the courier).
2. `js/track.js` calls this function: `GET /api/bob-track?ref=UASDRW78`.
3. The function forwards to Bob Go
   `GET {base}/tracking?tracking_reference=<ref>` with
   `Authorization: Bearer <BOBGO_API_KEY>` and returns a normalised
   `{ ok, reference, status, events: [...] }` timeline for the page.

## Env vars (Vercel → Project → Settings → Environment Variables)

- `BOBGO_API_KEY` — required. Bearer token from the Bob Go app
  (Settings → API). Your `4b...` sandbox key works against the sandbox base.
- `BOBGO_BASE_URL` — optional. Defaults to the **sandbox**
  `https://api.sandbox.bobgo.co.za/v2`. Switch to
  `https://api.bobgo.co.za/v2` for production (with a live key).

## Deploy

Same project as the Yoco function — there is no extra project to create.
After deploying you get `https://<project>.vercel.app`; the tracking endpoint
is `https://<project>.vercel.app/api/bob-track`.

Edit the constant in `build.py`:
```python
BOBGO_TRACK_API = "https://<project>.vercel.app/api/bob-track"
```
then regenerate:
```bash
python build.py products
```

## Local testing

```bash
# env present (see .env.example)
vercel dev
curl "http://localhost:3000/api/bob-track?ref=UASDRW78" -i
```

Expected: either a `{ ok: true, status: "...", events: [...] }` body for a
valid reference, or a clean `400`/`502` error object. Sandbox accounts can
create test shipments (they return tracking references) to verify the
timeline renders.

## How the reference reaches the customer

Fulfilment is manual (Yoco payment → WhatsApp handoff → you book the courier
on Bob Go). When you book, Bob Go issues a tracking reference / waybill;
send that to the buyer (e.g. in the WhatsApp reply). They enter it on
`track.html`. No order sync or webhook is required for this flow.

---

# LuthuliScents — Live quote + Yoco payment link (`api/quote-checkout.py`)

Third serverless function: `POST /api/quote-checkout`. Used from the **Cart**
page button "Generate & copy Yoco payment link".

## Flow

1. The cart page sends `{ items, delivery, successUrl, cancelUrl }`.
2. The function looks up each product's **price + parcel spec server-side**
   (the browser never sets the price), builds the parcels, and calls
   `POST /rates` on Bob Go with your collection address, the buyer's delivery
   address/contact, the declared value, and a `timeout`.
3. Bob Go returns live courier rates inside the same POST. The function picks
   the **cheapest** successful rate.
4. Total = product subtotal + the live shipping rate. The function creates a
   Yoco hosted checkout for that total and returns `paymentLink`.
5. The page copies the link to the clipboard so the owner can paste it into
   WhatsApp for the buyer.

## Env vars (Vercel → Project → Settings → Environment Variables)

- `YOCO_SECRET_KEY` — required (shared with `create-checkout`).
- `BOBGO_API_KEY` — required (shared with `bob-track`).
- `BOBGO_BASE_URL` — optional; defaults to the sandbox. Switch to
  `https://api.bobgo.co.za/v2` for live rates.
- `BOBGO_COLLECTION_ADDRESS` — **required JSON** of your pickup address, e.g.:
  ```json
  {"company":"LuthuliScents","street_address":"46 Loveday Street, Trump Center Building, Wemmer","local_area":"Selby","city":"Johannesburg","zone":"Gauteng","country":"ZA","code":"2092"}
  ```
- `BOBGO_COLLECTION_NAME` / `BOBGO_COLLECTION_PHONE` / `BOBGO_COLLECTION_EMAIL`
  — the collection contact. Bob Go requires a **phone or email** for both the
  collection and the delivery contact.

The returned amount covers products + live courier delivery. The owner still
books the courier on Bob Go (which settles the freight to the Bob Go account
separately); the Yoco link collects product + delivery from the buyer in one
payment.

## Local testing

```bash
# env present (see .env.example) + BOBGO_COLLECTION_ADDRESS etc.
vercel dev
curl -X POST http://localhost:3000/api/quote-checkout \
  -H "Content-Type: application/json" \
  -d '{"items":[{"key":"rosie","quantity":2}],"delivery":{"name":"J Buyer","phone":"+27123456789","email":"b@t.com","city":"Cape Town","postal":"8001"},"successUrl":"https://x/success.html","cancelUrl":"https://x/cart.html"}'
```