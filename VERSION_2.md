# LuthuliScents — Static HTML/CSS/JS site on GitHub Pages + Python tooling

A redesigned, single-navigation version of LuthuliScents: a **static website
hosted free on GitHub Pages** (no Railway, no server) with **Python used only
as local tooling** for content generation and order processing.

## 1. Hosting constraint

GitHub Pages only serves static HTML/CSS/JS — it **cannot run Python**. So:

- All customer-facing logic (cart, shipping, checkout) runs **client-side** in
  vanilla JavaScript.
- **Python (`build.py`)** runs locally or in CI to generate the catalog data
  (`data/products.json`) and to process downloaded order exports. It is not
  part of the served site.
- The Courier Guy API is proxied via Vercel serverless functions (`/api/quote-checkout`
  and `/api/tcg-track`) so secret keys are never exposed in the browser. Orders are captured
  via a **Yoco payment link** plus a **WhatsApp order handoff**.

## 2. Project structure

```
/
├── index.html               # Home: hero, featured scents, quotes, VIP list
├── about.html               # Brand story, values, family guide, social links
├── products.html            # Full catalog + scent-family filter + add to cart
├── contact.html             # WhatsApp enquiry form, FAQs, direct contacts
├── cart.html                # Cart line items + checkout (Yoco + WhatsApp)
├── css/
│   └── style.css            # Ivory minimal-luxury theme (ported from core/styles.py)
├── js/
│   ├── data.js              # Loads data/products.json once (+ helpers)
│   ├── site.js              # Shared header/nav/footer + cart badge + social icons
│   ├── cart.js              # localStorage cart logic
│   ├── products.js          # Renders product cards + family filter
│   ├── checkout.js          # Flat shipping, order summary, Yoco + WhatsApp links
│   └── contact.js           # WhatsApp contact-form handoff
├── img/                     # logo + all product images
├── data/
│   └── products.json        # Generated catalog (single source of truth for JS)
├── build.py                 # Single Python file: catalog source + generators
└── .github/workflows/
    └── pages.yml            # Deploys the static site to GitHub Pages
```

## 3. Feature migration (from the old Streamlit app)

| V1 / Streamlit feature          | V2 (this site)                                     |
| ------------------------------- | -------------------------------------------------- |
| `st.session_state` cart         | `localStorage` cart — survives page loads           |
| The Courier Guy live rates      | Real-time quotes via `/api/quote-checkout`          |
| Free shipping over R500         | Preserved (client-side)                            |
| Yoco checkout                  | Vercel serverless function (`/api/create-checkout`) builds a cart-specific hosted checkout |
| Server-side order capture       | WhatsApp order handoff + form → CSV (via build.py) |
| Injected CSS in Python string   | `css/style.css` (cacheable, maintainable)          |
| Duplicated nav in each page     | Single JS-injected header/footer (site.js)         |
| Streamlit runtime (Railway)     | Removed — static site only                       |
| `pages/`, `views/`, `core/`     | Retired — logic consolidated into `build.py` + `js/` |

## 4. Python tooling (`build.py`)

Local/CI only. Run from the repo root.

- `python build.py products` — write `data/products.json` from the catalog
  defined inside `build.py` (the single source of truth). Also regenerates the
  shipping constants and Yoco link the browser uses.
- `python build.py orders <source.csv>` — normalise an exported order form
  (Google Sheets / CSV) into `orders.csv` for fulfilment.

Dependencies: `requests`, `python-dotenv` (see `requirements.txt`).

## 5. Checkout flow (cart.html)

1. Cart lives in `localStorage`; prices always come from `data/products.json`.
2. Customer fills shipping form (name, email, phone, delivery address, postal).
3. Flat shipping is computed client-side (R85 for `2*` postal codes, else
   R120), **free over R500**.
4. Order summary is shown (items, subtotal, shipping, total).
5. Payment is started by POSTing the cart to the Vercel
   function `/api/create-checkout`, which creates a Yoco hosted checkout and
   returns a `redirectUrl`; the customer is redirected there to pay.
6. A **WhatsApp order handoff** link is provided so the order details
   (customer + items + total) reach the shop for fulfilment.

## 6. Deployment

- GitHub Pages is enabled with **Source: GitHub Actions** (repo Settings).
- Push to `main` (or run the workflow manually) → the `pages.yml` workflow
  regenerates `data/products.json` and deploys the repo root as a static site.
- Asset paths are **relative** (`./css`, `./js`, `./img`, `./data`) so the site
  works under the `<user>.github.io/<repo>/` subpath.

## 7. Adding / editing products

Edit the `PRODUCTS` list inside `build.py`, then run `python build.py products`
(or just push — CI regenerates the JSON). There is only **one** place to add or
change products; both the static pages and any future consumers read
`data/products.json`.