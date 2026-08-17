"""LuthuliScents local tooling — the single Python file for site logic.

The site itself is a static site hosted on GitHub Pages (HTML/CSS/JS only),
so Python runs locally (or in CI) rather than on the server. This module is
the single source of truth for the catalog and generates the JSON the
browser consumes.

Usage:
    python build.py products                # write data/products.json
    python build.py orders <source.csv>     # normalise a form export -> orders.csv
"""

import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"

PRODUCTS = [
    {
        "key": "rosie",
        "name": "Rosie",
        "family": "Female",
        "price": 180.00,
        "size": "50ml",
        "weight_kg": 0.3,
        "dimensions_cm": {"length": 10, "width": 6, "height": 6},
        "image": "img/WhatsApp Image 2026-05-27 at 09.07.42.jpeg",
        "tagline": "Long-lasting, blooming florals",
        "notes": "Peony, rose water, soft musk",
        "occasions": "Date night · Weddings · Evenings",
        "featured": True,
        "badge": "Bestseller",
    },
    {
        "key": "sweetapple",
        "name": "Sweetapple",
        "family": "Unisex",
        "price": 180.00,
        "size": "50ml",
        "weight_kg": 0.3,
        "dimensions_cm": {"length": 10, "width": 6, "height": 6},
        "image": "img/WhatsApp Image 2026-05-27 at 09.05.30.jpeg",
        "tagline": "Crisp, juicy and long-lasting",
        "notes": "Red apple, fresh green accord, vanilla",
        "occasions": "Day wear · Office · Casual",
        "featured": True,
        "badge": "Winter Sale",
    },
    {
        "key": "apple-blaze",
        "name": "Apple Blaze",
        "family": "Unisex",
        "price": 40.00,
        "size": "10ml",
        "image": "img/apple blaze.jpeg",
        "tagline": "A fiery caramelised apple accord",
        "notes": "Baked apple, warm amber, caramel",
        "occasions": "Cooler days · Evenings · Winter",
        "featured": False,
        "badge": "Limited",
    },
    {
        "key": "woody",
        "name": "Woody",
        "family": "Male",
        "price": 40.00,
        "size": "10ml",
        "image": "img/woody2.png",
        "tagline": "Bold, masculine, grounded",
        "notes": "Cedarwood, sandalwood, smoky vetiver",
        "occasions": "Business · Evenings · All season",
        "featured": False,
        "badge": "New",
    },
    {
        "key": "apple-blaze",
        "name": "Apple Blaze",
        "family": "Unisex",
        "price": 50.00,
        "size": "50ml",
        "weight_kg": 0.3,
        "dimensions_cm": {"length": 10, "width": 6, "height": 6},
        "image": "img/IMG-20260429-WA0066.jpg",
        "tagline": "Mysterious and sensual",
        "notes": "Blackberry, dark plum, amber musk",
        "occasions": "Evenings · Gala · Signature",
        "featured": False,
        "badge": "Evening",
    },
    {
        "key": "sweetapple-rose",
        "name": "Sweet Apple Rose",
        "family": "Unisex",
        "price": 40.00,
        "size": "10ml",
        "image": "img/sweetapple.jpeg",
        "tagline": "Rosy apple, fresh and fun",
        "notes": "Ripe apple, rose petals, sugar",
        "occasions": "Day wear · Brunch · Gift",
        "featured": False,
        "badge": "Gift Idea",
    },
    {
        "key": "woody",
        "name": "woody",
        "family": "Unisex",
        "price": 50.00,
        "size": "15ml",
        "image": "img/WhatsApp Image 2026-05-11 at 14.58.30.jpeg",
        "tagline": "The house signature — timeless luxury",
        "notes": "Golden amber, white florals, oud",
        "occasions": "Any occasion · Signature scent",
        "featured": True,
        "badge": "Signature",
    },
]

FAMILIES = ["All", "Female", "Male", "Unisex"]

SOCIAL_LINKS = {
    "TikTok": "https://www.tiktok.com/@sthandiwe386?is_from_webapp=1&sender_device=pc",
    "Instagram": "https://www.instagram.com/luthuliscents?igsh=NzJvNDNxbDJsY3Jv",
    "WhatsApp": "https://wa.me/27692380796",
    "X / Twitter": "https://x.com/L68220Luthuli",
    "Email": "mailto:sthandiweluthuli322@gmail.com",
    "Facebook": "https://www.facebook.com/profile.php?id=61583709642144",
}

# Client-side checkout constants (mirrored by js/checkout.js)
SHIPPING = {
    "flat": 120.0,
    "flat_metro": 85.0,  # postal codes starting with these prefixes
    "metro_prefixes": ("2",),
    "free_shipping_threshold": 500.0,
}

# Vercel serverless function that creates a Yoco hosted checkout from the
# cart (holds YOCO_SECRET_KEY server-side). Replace <project> after you deploy
# to Vercel and copy the .vercel.app URL. See api/README.md.
YOCO_CHECKOUT_API = "https://luthuli-scents.vercel.app/api/create-checkout"

# Vercel serverless function that proxies BobGo tracking for the Track page
# (holds BOBGO_API_KEY server-side). Same <project>.vercel.app host as above.
BOBGO_TRACK_API = "https://luthuli-scents.vercel.app/api/bob-track"

# Vercel serverless function that returns a live BobGo shipping quote + a Yoco
# payment link for that total, so the owner can copy it into WhatsApp.
QUOTE_CHECKOUT_API = "https://luthuli-scents.vercel.app/api/quote-checkout"


def build_products() -> None:
    """Write the catalog the browser loads (data/products.json)."""
    DATA_DIR.mkdir(exist_ok=True)
    payload = {
        "products": PRODUCTS,
        "families": FAMILIES,
        "social_links": SOCIAL_LINKS,
        "shipping": SHIPPING,
        "yoco_checkout_link": YOCO_CHECKOUT_API,
        "tracking_api": BOBGO_TRACK_API,
        "quote_checkout_api": QUOTE_CHECKOUT_API,
    }
    out = DATA_DIR / "products.json"
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote {out}")


def process_orders(source_csv: str, out_csv: str = "orders.csv") -> None:
    """Normalise an exported order form (Google Sheets / CSV) for fulfilment.

    Expected columns (superset tolerated): name, email, phone, address,
    suburb, city, postal, items, total, date.
    """
    fieldnames = [
        "order_no", "customer", "email", "phone",
        "address", "suburb", "city", "postal",
        "items", "total", "date",
    ]
    src = Path(source_csv)
    with src.open(newline="", encoding="utf-8-sig") as fin, \
            ROOT.joinpath(out_csv).open("w", newline="", encoding="utf-8") as fout:
        rows = csv.DictReader(fin)
        writer = csv.DictWriter(fout, fieldnames=fieldnames)
        writer.writeheader()
        for order_no, row in enumerate(rows, start=1):
            writer.writerow({
                "order_no": f"LS-{order_no:04d}",
                "customer": (row.get("name") or row.get("Name") or "").strip(),
                "email": (row.get("email") or row.get("Email") or "").strip(),
                "phone": (row.get("phone") or row.get("Phone") or "").strip(),
                "address": (row.get("address") or "").strip(),
                "suburb": (row.get("suburb") or "").strip(),
                "city": (row.get("city") or "").strip(),
                "postal": (row.get("postal") or row.get("postal code") or "").strip(),
                "items": (row.get("items") or row.get("Items") or "").strip(),
                "total": (row.get("total") or row.get("Total") or "").strip(),
                "date": (row.get("date") or row.get("Date") or "").strip(),
            })
    print(f"Wrote {out_csv}")


def main() -> None:
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        raise SystemExit(0)
    if args[0] == "products":
        build_products()
    elif args[0] == "orders":
        if len(args) < 2:
            print("Usage: python build.py orders <source.csv>")
            raise SystemExit(1)
        process_orders(args[1])
    else:
        print(f"Unknown command: {args[0]}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
