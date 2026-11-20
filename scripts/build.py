#!/usr/bin/env python3
"""Static site generator for 3rde.online (عروض أونلاين).

Reads data/raw/*.json (exported from the Google Sheet — the single source
of truth) + data/coupons.json + data/guides.json + data/news.json +
settings.json, and generates the full uploadable static site into site/.

Binding rules (docs/seo-plan.md, docs/audit.md, docs/content-workflow.md,
docs/affiliate-setup.md):
  - Static HTML per page; one page per unified model (brand+model+storage+RAM).
  - Every affiliate/buy link: rel="sponsored noopener" target="_blank".
  - NEVER the word "وهمي" (or synonyms) in any generated content.
  - Prices in JSON-LD must match visible prices exactly. Currency EGP.
  - sitemap lastmod changes ONLY when page content actually changes.
  - Guides are drafts (noindex, not in sitemap) until human review.
  - Images: w_800 upgrade (sync-helpers), watermark style B on main images.
  - Affiliate system (docs/affiliate-setup.md):
      Jumia: full tracking link stored as the offer's product URL
             (built in the Jumia Link Builder); optional jumia_sub_id.
      Amazon Egypt: single tag, MUST end with -21; search links until
             real ASINs exist; OneLink is NOT used (doesn't support .eg).

Usage:
    python3 scripts/build.py [--out site] [--no-images]
"""
import hashlib
import html
import json
import re
import shutil
import sys
import unicodedata
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path
from urllib.parse import quote_plus

import importlib.util
_spec = importlib.util.spec_from_file_location(
    "sync_helpers", Path(__file__).resolve().parent / "sync-helpers.py")
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
affiliate_link_attrs = _mod.affiliate_link_attrs
amazon_tag_is_valid = _mod.amazon_tag_is_valid
build_amazon_product_url = _mod.build_amazon_product_url
build_amazon_search_url = _mod.build_amazon_search_url
build_jumia_product_url = _mod.build_jumia_product_url
discount_verdict = _mod.discount_verdict
jumia_tracking_url = _mod.jumia_tracking_url
lowest_price_badge = _mod.lowest_price_badge
price_change = _mod.price_change
should_log_price = _mod.should_log_price
upgrade_image_url = _mod.upgrade_image_url

BASE = Path(__file__).resolve().parent.parent
DATA = BASE / "data"
RAW = DATA / "raw"
SITE = BASE / "site"
TODAY = date.today().isoformat()          # 2026-11-19
TODAY_AR = "19 نوفمبر 2026"
SPONSORED = affiliate_link_attrs()        # rel="sponsored noopener" target="_blank"

FORBIDDEN_WORDS = ["وهمي", "مزيف", "خدعة", "احتيال"]


# ------------------------------------------------------------------ utils
def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def norm(s):
    return re.sub(r"\s+", " ", str(s or "")).strip()


def esc(s):
    return html.escape(str(s or ""), quote=True)


# ------------------------------------------------------------------ icons
# Professional inline SVG icons (Lucide-style, stroke=currentColor) replacing
# emoji in headings and buttons. `icon("menu")` -> <span class="ic">...</span>.
# `sec_icon("star")` -> the small blue icon used in <h2> section headings.
_ICON_PATHS = {
    # filled star (new / latest)
    "star": '<path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z" fill="currentColor" stroke="none"/>',
    # percent (biggest discounts)
    "percent": '<line x1="19" x2="5" y1="5" y2="19"/><circle cx="6.5" cy="6.5" r="2.5"/><circle cx="17.5" cy="17.5" r="2.5"/>',
    # simple down arrow (price drops)
    "arrow-down": '<path d="M12 5v14"/><path d="m19 12-7 7-7-7"/>',
    # cheapest (price tag)
    "tag": '<path d="M12.586 2.586A2 2 0 0 0 11.172 2H4a2 2 0 0 0-2 2v7.172a2 2 0 0 0 .586 1.414l8.704 8.704a2.426 2.426 0 0 0 3.42 0l6.58-6.58a2.426 2.426 0 0 0 0-3.42z"/><circle cx="7.5" cy="7.5" r=".5" fill="currentColor"/>',
    # nav menu
    "menu": '<line x1="4" x2="20" y1="6" y2="6"/><line x1="4" x2="20" y1="12" y2="12"/><line x1="4" x2="20" y1="18" y2="18"/>',
    # dark mode toggle
    "moon": '<path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z"/>',
    # light mode toggle (sun)
    "sun": '<circle cx="12" cy="12" r="4"/><path d="M12 2v2"/><path d="M12 20v2"/><path d="m4.93 4.93 1.41 1.41"/><path d="m17.66 17.66 1.41 1.41"/><path d="M2 12h2"/><path d="M20 12h2"/><path d="m6.34 17.66-1.41 1.41"/><path d="m19.07 4.93-1.41 1.41"/>',
    # install app
    "download": '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" x2="12" y1="15" y2="3"/>',
    # best price badge (confirmation)
    "trophy": '<path d="M6 9H4.5a2.5 2.5 0 0 1 0-5H6"/><path d="M18 9h1.5a2.5 2.5 0 0 0 0-5H18"/><path d="M4 22h16"/><path d="M10 14.66V17c0 .55-.47.98-.97 1.21C7.85 18.75 7 20.24 7 22"/><path d="M14 14.66V17c0 .55.47.98.97 1.21C16.15 18.75 17 20.24 17 22"/><path d="M18 2H6v7a6 6 0 0 0 12 0V2Z"/>',
    # best price badge (check in a circle)
    "check-circle": '<circle cx="12" cy="12" r="10"/><path d="m9 12 2 2 4-4"/>',
    # draft warning
    "alert": '<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/><path d="M12 9v4"/><path d="M12 17h.01"/>',
}


def icon(name):
    return (f'<span class="ic"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" '
            f'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
            f'{_ICON_PATHS[name]}</svg></span>')


def sec_icon(name, tone=""):
    cls = "sec-icon" + (f" {tone}" if tone else "")
    return (f'<span class="{cls}"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" '
            f'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
            f'{_ICON_PATHS[name]}</svg></span>')


AR_DIGITS = "٠١٢٣٤٥٦٧٨٩"


def num(v, default=None):
    """Parse a number, tolerating Arabic-Indic digits and Arabic separators."""
    if v is None or str(v).strip() == "":
        return default
    s = str(v).strip()
    for i, d in enumerate(AR_DIGITS):
        s = s.replace(d, str(i))
    s = s.replace("٫", ".").replace("٬", "").replace(",", "").replace(" ", "")
    try:
        return float(s)
    except ValueError:
        return default


def fmt_price(v):
    """12,459 — Western digits with thousands separator."""
    return f"{int(round(float(v))):,}"


def slugify(s):
    s = unicodedata.normalize("NFKD", str(s)).lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s or "item"


def parse_sheet_date(s):
    """'19-11-2026' -> '2026-11-19' (ISO)."""
    m = re.match(r"(\d{1,2})-(\d{1,2})-(\d{4})", str(s or "").strip())
    if m:
        d, mo, y = m.groups()
        return f"{y}-{mo.zfill(2)}-{d.zfill(2)}"
    return TODAY


def check_no_forbidden(text, where):
    for w in FORBIDDEN_WORDS:
        if w in text:
            raise SystemExit(f"FORBIDDEN WORD {w!r} in {where} — build stopped.")


# ---------------------------------------------------------------- settings
# Schema note: settings.json may use either key style (site_domain/domain,
# site_slogan/slogan, ads slots as plain code strings or {code,enabled,height}
# objects). Normalize here so the generator works with both.
SETTINGS = load_json(BASE / "settings.json")
SITE_NAME = SETTINGS["site_name"]
DOMAIN = SETTINGS.get("domain") or SETTINGS.get("site_domain", "3rde.online")
BASE_URL = (SETTINGS.get("base_url") or f"https://{DOMAIN}").rstrip("/")
EMAIL = SETTINGS["contact_email"]


def _ads_slot(name):
    slots = SETTINGS.get("ads", {}).get("slots", {})
    raw = slots.get(name, "")
    if isinstance(raw, dict):
        return {"code": raw.get("code", "") or "",
                "enabled": bool(raw.get("enabled")) and bool(raw.get("code")),
                "height": int(raw.get("height", 90))}
    return {"code": raw or "", "enabled": bool(raw),
            "height": 250 if name in ("in_list", "in_product") else 90}


ADS_SLOTS = {n: _ads_slot(n) for n in ("top", "in_list", "in_product", "bottom")}
_AN = SETTINGS.get("analytics", {})
ANALYTICS = {
    "google_analytics_id": _AN.get("google_analytics_id", ""),
    "google_search_console_verification": _AN.get("google_search_console_verification", ""),
    "bing_webmaster_verification": (_AN.get("bing_webmaster_verification", "")
                                    or _AN.get("bing_verification", "")),
}
ADMIN_API_URL = SETTINGS.get("admin", {}).get("apps_script_url", "")
HOME_LAYOUTS = {
    "classic": ("الكلاسيكي", ""), "rows": ("القوائم المدمجة", ""),
    "deals": ("العروض أولاً", ""),
    "store": ("متجر", "ocean"), "compact": ("مدمج", "slate"),
    "luxury": ("فاخر داكن", "gold"), "forest": ("أخضر", "forest"),
    "royal": ("ملكي", "royal"), "sunset": ("غروب", "sunset"),
    "minimal": ("بسيط", "minimal"), "showcase": ("عرض كبير", "rose"),
    "fullrows": ("صفوف كاملة", "teal"), "quick": ("سريع", "indigo"),
}
HOME_LAYOUT = (SETTINGS.get("home_layout") or "classic").strip().lower()
if HOME_LAYOUT not in HOME_LAYOUTS:
    HOME_LAYOUT = "classic"
HOME_THEME = HOME_LAYOUTS[HOME_LAYOUT][1]
ONESIGNAL_APP_ID = SETTINGS.get("notifications", {}).get("onesignal_app_id", "")
AFF = SETTINGS.get("affiliate", {})
AMAZON_TAG = (AFF.get("amazon_associates_tag") or "").strip()
JUMIA_SUB_ID = (AFF.get("jumia_sub_id") or "").strip()
NOON_TAG = (AFF.get("noon_affiliate_tag") or "").strip()
if AMAZON_TAG and not amazon_tag_is_valid(AMAZON_TAG):
    raise SystemExit(
        f"Invalid Amazon Egypt tag {AMAZON_TAG!r}: it must end with -21 "
        "(a -20 US tag earns nothing on amazon.eg). Fix settings.json.")


# ------------------------------------------------------------ affiliate URLs
JUMIA_HOME_URL = (AFF.get("jumia_homepage_url") or "").strip()


def jumia_home():
    """The user's tracked Arabic Jumia homepage (settings), used for
    Jumia coupon redirects and generic 'shop on Jumia' links."""
    if JUMIA_HOME_URL and "utm_source=JFORCE" in JUMIA_HOME_URL:
        return JUMIA_HOME_URL
    return build_jumia_product_url("https://www.jumia.com.eg/ar/")


def jumia_url(offer_url, affiliate_url=""):
    """Jumia JForce deep link for a buy button (updated 2026-11-19):
    column AU ("رابط الأفلييت") in the Sheet holds the ready JForce
    tracking link for the product — use it directly. If it is empty
    for a row, fall back to building the deep link from the plain
    product URL with build_jumia_product_url()."""
    aff = (affiliate_url or "").strip()
    if aff:
        return aff
    return build_jumia_product_url(offer_url)


AMAZON_ASINS = {}
_asin_file = DATA / "amazon_asins.json"
if _asin_file.exists():
    AMAZON_ASINS = load_json(_asin_file)  # {model_slug: "B0XXXXXXX"}


def amazon_url(model_display, model_slug):
    """Amazon Egypt: tagged product link when an ASIN is known, else a
    tagged search link. Without a tag yet, a plain search link."""
    asin = AMAZON_ASINS.get(model_slug)
    if asin and AMAZON_TAG:
        return build_amazon_product_url(asin, AMAZON_TAG)
    if AMAZON_TAG:
        return build_amazon_search_url(model_display, AMAZON_TAG)
    return f"https://www.amazon.eg/s?k={quote_plus(model_display)}"


def noon_url(model_display):
    return f"https://www.noon.com/egypt-en/search/?q={quote_plus(model_display)}"


def buy_buttons(model_slug, model_display, jumia_href, cheapest_store=""):
    """The 3 buy buttons (templates/buy-buttons.html structure).
    cheapest_store: store of the cheapest tracked offer ('جوميا' / 'أمازون' / 'نون').
    The '(أفضل سعر حالياً)' badge goes on the cheapest store's button — NEVER on
    the Noon button; if Noon is the cheapest, no badge is shown on any button."""
    s = (cheapest_store or "").strip().lower()
    is_jumia = s in ("جوميا", "jumia")
    is_amazon = s in ("أمازون", "amazon")
    # Noon never gets the badge, even if it is the cheapest.
    badge = f' <span class="best-price-badge">{icon("check-circle")} (أفضل سعر حالياً)</span>'
    jumia_badge = badge if is_jumia else ""
    amazon_badge = badge if is_amazon else ""
    return f"""<div class="buy-buttons" data-model="{esc(model_slug)}">
  <a class="btn-buy btn-jumia" href="{esc(jumia_href)}" {SPONSORED} data-store="jumia" data-model="{esc(model_slug)}" data-event="buy-click">اشترِ من جوميا مصر{jumia_badge}</a>
  <a class="btn-buy btn-amazon" href="{esc(amazon_url(model_display, model_slug))}" {SPONSORED} data-store="amazon" data-model="{esc(model_slug)}" data-event="buy-click">اشترِ من أمازون مصر{amazon_badge}</a>
  <a class="btn-buy btn-noon" href="{esc(noon_url(model_display))}" {SPONSORED} data-store="noon" data-model="{esc(model_slug)}" data-event="buy-click">اشترِ من نون مصر</a>
  <p class="affiliate-note">روابط شراء بالعمولة — <a href="/affiliate-disclosure/">اقرأ الإفصاح</a></p>
</div>"""


# ------------------------------------------------------------------- data
def load_sheet():
    """Load sheet1 + summary + price history + duplicates (raw exports)."""
    sheet = load_json(RAW / "sheet1.json")
    header = [norm(h) for h in sheet["values"][0]]
    col = {name: i for i, name in enumerate(header)}
    rows = []
    for r in sheet["values"][1:]:
        if not any(norm(c) for c in r):
            continue
        rows.append(r)
    summary = load_json(RAW / "summary.json")
    history = load_json(RAW / "price_history.json")
    return header, col, rows, summary, history


HEADER, COL, ROWS, SUMMARY, HISTORY = load_sheet()
SHEET_UPDATED = load_json(RAW / "sheet1.json").get("retrieved_at", {}).get(
    "user_local", TODAY)


def c(row, name):
    i = COL.get(name)
    if i is None or i >= len(row):
        return ""
    return row[i]


SHEET_UPDATED_DATE = max(
    (parse_sheet_date(c(r, "تاريخ آخر تحديث")) for r in ROWS),
    default=TODAY)


def availability_in_stock(text):
    t = norm(text).lower()
    if not t:
        return True
    if "out of stock" in t or "غير متوفر" in t or "نفد" in t:
        return False
    return True


def units_left(text):
    """Units left parsed from an availability string ('1 unit left',
    'يوجد منتج 1 فقط', 'Few units left' -> 3). None if unknown/plenty."""
    t = norm(text).lower()
    if not t:
        return None
    m = re.search(r"(\d+)\s*(?:units?\s+left|unit\s+left|in\s+stock|pieces?)", t)
    if m:
        return int(m.group(1))
    if "only 1" in t or "منتج 1 فقط" in t or "1 unit" in t:
        return 1
    if "few units" in t:
        return 3
    return None


def availability_ar(text):
    t = norm(text)
    if not t:
        return "متوفر"
    low = t.lower()
    if "in stock" in low and "units" not in low:
        return "متوفر"
    m = re.match(r"(\d+)\s*(?:units? left|in stock)", low)
    if m:
        return f"متوفر — بقي {m.group(1)} فقط" if int(m.group(1)) <= 3 else "متوفر"
    if "few units" in low:
        return "متوفر — كمية محدودة"
    return "متوفر"


def offer_discount(row):
    """Discount % (positive number) from old/current prices, fallback to col."""
    cur = num(c(row, "السعر الحالي (بعد الخصم) - جنيه"))
    old = num(c(row, "السعر قبل الخصم - جنيه"))
    if cur and old and old > cur:
        return round((old - cur) / old * 100, 1)
    v = num(c(row, "نسبة الخصم %"), 0) or 0
    return abs(v) if v < 0 else 0.0


# ------------------------------------------------------------- model groups
class Model:
    def __init__(self, key, offers):
        self.brand, self.model, self.storage, self.ram = key
        self.offers = sorted(offers, key=lambda r: num(
            c(r, "السعر الحالي (بعد الخصم) - جنيه")) or 0)
        cheapest = self.offers[0]
        self.cheapest_price = num(c(cheapest, "السعر الحالي (بعد الخصم) - جنيه"))
        self.old_price = num(c(cheapest, "السعر قبل الخصم - جنيه"))
        self.discount = max(offer_discount(r) for r in self.offers)
        self.rating = num(c(cheapest, "التقييم"))
        self.rating_count = int(num(c(cheapest, "عدد التقييمات"), 0) or 0)
        self.name_en = f"{self.brand} {self.model} {self.storage}/{self.ram}"
        self.name_ar = norm(c(cheapest, "الاسم باللغة العربية")) or self.name_en
        self.image_remote = upgrade_image_url(norm(c(cheapest, "رابط صورة المنتج")))
        self.image_local = None  # set later if a watermarked local file exists
        self.g5 = norm(c(cheapest, "دعم 5G")) == "نعم"
        self.in_stock = any(availability_in_stock(c(r, "التوفر")) for r in self.offers)
        self.last_update = max(
            (parse_sheet_date(c(r, "تاريخ آخر تحديث")) for r in self.offers),
            default=TODAY)
        self.year = max(
            (int(num(c(r, "سنة الإصدار"), 0) or 0) for r in self.offers),
            default=0)
        self.slug = None
        self.history = []       # [(date_iso, price)]
        self.history_days = 0
        self.avg_30d = None
        self.min_price = self.cheapest_price
        self.max_price = max(num(c(r, "السعر الحالي (بعد الخصم) - جنيه"))
                             or 0 for r in self.offers)

    @property
    def display(self):
        return f"{self.brand} {self.model}"

    @property
    def image(self):
        return self.image_local or self.image_remote


def build_models():
    groups = defaultdict(list)
    for r in ROWS:
        key = (norm(c(r, "الماركة")), norm(c(r, "الموديل")),
               norm(c(r, "التخزين")), norm(c(r, "الرام")))
        if not key[0] or not key[1]:
            continue
        groups[key].append(r)
    models = [Model(k, v) for k, v in groups.items()]
    # unique slugs (one collision in the data: infinix-hot-60-pro-256gb-8gb)
    seen = Counter()
    for m in sorted(models, key=lambda x: (x.brand, x.model, x.storage, x.ram)):
        base = slugify(f"{m.brand}-{m.model}-{m.storage}-{m.ram}")
        seen[base] += 1
        m.slug = base if seen[base] == 1 else f"{base}-{seen[base]}"
    return sorted(models, key=lambda m: m.cheapest_price)


MODELS = build_models()
MODEL_BY_SLUG = {m.slug: m for m in MODELS}
def order_brands(brands):
    """Order brands by the admin-set brand_order in settings.json (fame
    order, editable from the admin panel). Brands NOT in brand_order
    (e.g. newly added in the Sheet) come last, alphabetically. Matching
    is exact first, then case-insensitive, so 'Xiaomi'/'XIAOMI' stay
    adjacent even if only one is listed."""
    order = [b for b in (SETTINGS.get("brand_order") or [])
             if isinstance(b, str)]
    rank = {}
    for i, b in enumerate(order):
        rank.setdefault(b, i)
        rank.setdefault(b.lower(), i)
    n = len(order)
    return sorted(brands,
                  key=lambda b: (rank.get(b, rank.get(b.lower(), n)),
                                 b.lower(), b))


BRANDS = order_brands({m.brand for m in MODELS})
BRAND_SLUGS = {b: slugify(b) for b in BRANDS}


# ------------------------------------------- brand logos (Clearbit) + stores
# Official domain per brand (lowercase key) for the Clearbit Logo API.
# Brands NOT listed here (local/obscure) get a styled text tile instead.
BRAND_LOGOS = {
    "samsung": "samsung.svg", "apple": "apple.svg", "xiaomi": "xiaomi.svg",
    "redmi": "redmi.svg", "oppo": "oppo.svg", "vivo": "vivo.svg",
    "realme": "realme.svg", "honor": "honor.svg", "huawei": "huawei.svg",
    "infinix": "infinix.svg", "tecno": "tecno.svg",
    "itel": "itel.svg", "nokia": "nokia.svg", "motorola": "motorola.svg",
    "zte": "zte.png", "micromax": "micromax.svg",
}


def brand_logo_url(brand):
    """Self-hosted local logo path for a brand, or None for local/obscure brands."""
    f = BRAND_LOGOS.get(str(brand).strip().lower())
    return f"/assets/brand-logos/{f}" if f else None


def get_stores():
    """Stores for the /brands/ page, from settings.json (admin-editable)."""
    stores = SETTINGS.get("stores") or []
    out = []
    for s in stores:
        if not isinstance(s, dict):
            continue
        name = norm(s.get("name"))
        url = norm(s.get("url"))
        if not name or not url:
            continue
        out.append({"name": name, "logo": norm(s.get("logo")),
                    "url": url})
    return out


def logo_img_html(logo_url, name, fallback_id):
    """An <img> logo with an onerror fallback to a single-letter monogram tile
    (the card already shows the full name below, so the fallback must not
    repeat it)."""
    initial = esc(name.strip()[:1]) if name and name.strip() else "؟"
    if not logo_url:
        return (f'<span class="brand-logo-fallback" id="{fallback_id}">'
                f'{initial}</span>')
    return (f'<img src="{esc(logo_url)}" alt="{esc(name)}" loading="lazy" '
            f'onerror="this.style.display=\'none\';'
            f'document.getElementById(\'{fallback_id}\').style.display=\'flex\'">'
            f'<span class="brand-logo-fallback" id="{fallback_id}" '
            f'style="display:none">{initial}</span>')


# ---------------------------------------------------------- image status
# sync.py records per-model image download results here:
#   {slug: {"local": bool, "working_url": str, "note": str}}
# A model whose remote image is DEAD (404 even at original size) gets the
# local placeholder instead of a broken link, and is listed in the build
# report so the admin can fix the sheet URL.
IMAGE_STATUS = load_json(DATA / "image-status.json") if (DATA / "image-status.json").exists() else {}
DEAD_IMAGES = []


def resolve_model_image(model):
    """(local_path_or_None, remote_url, is_placeholder)."""
    local = local_image_for(model)
    if local:
        return local, None, False
    st = IMAGE_STATUS.get(model.slug)
    if st and not st.get("local"):
        if model.slug not in DEAD_IMAGES:
            DEAD_IMAGES.append(model.slug)
        return None, "/images/placeholder.jpg?v=2", True
    return None, model.image_remote, False
def build_history():
    """Join سجل الأسعار rows to models via product URL -> brand."""
    url_to_brand = {}
    for r in ROWS:
        url_to_brand[norm(c(r, "رابط المنتج"))] = norm(c(r, "الماركة"))
    per_model = defaultdict(list)  # slug -> [(date, new_price)]
    key_to_slug = {(m.brand, m.model, m.storage, m.ram): m.slug for m in MODELS}
    for r in HISTORY["values"][1:]:
        if len(r) < 10 or not any(norm(x) for x in r):
            continue
        d = parse_sheet_date(r[0])
        brand = url_to_brand.get(norm(r[7]), "")
        key = (brand, norm(r[2]), norm(r[3]), norm(r[4]))
        slug = key_to_slug.get(key)
        new_price = num(r[9])
        if slug and new_price:
            per_model[slug].append((d, new_price))
    _merge_local_price_history(per_model, key_to_slug)
    for m in MODELS:
        pts = sorted(set(per_model.get(m.slug, [])))
        m.history = pts
        if pts:
            dates = [p[0] for p in pts]
            m.history_days = (datetime.fromisoformat(max(dates))
                              - datetime.fromisoformat(min(dates))).days + 1
            recent = [p for d, p in pts
                      if (datetime.fromisoformat(max(dates))
                          - datetime.fromisoformat(d)).days <= 30]
            m.avg_30d = sum(recent) / len(recent) if recent else None
            m.min_price = min(p for _, p in pts)
            m.max_price = max(m.max_price, max(p for _, p in pts))


def _merge_local_price_history(per_model, key_to_slug):
    """Merge hourly-sync price changes (data/price_history_local.json,
    written by scripts/sync.py) into the chart data. The local file has
    {url, old, new, date}; the model is joined via the sheet row URL."""
    local_file = DATA / "price_history_local.json"
    if not local_file.exists():
        return
    try:
        changes = json.loads(local_file.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return
    url_to_key = {}
    for r in ROWS:
        url_to_key[norm(c(r, "رابط المنتج"))] = (
            norm(c(r, "الماركة")), norm(c(r, "الموديل")),
            norm(c(r, "التخزين")), norm(c(r, "الرام")))
    for ch in changes:
        key = url_to_key.get(norm(ch.get("url", "")))
        if not key:
            continue
        slug = key_to_slug.get(key)
        if slug and ch.get("new"):
            per_model[slug].append((ch.get("date", TODAY), float(ch["new"])))



build_history()


def latest_drops(limit=8):
    """Offers whose price dropped in the history log (new < old)."""
    drops = []
    for r in HISTORY["values"][1:]:
        if len(r) < 10:
            continue
        old, new = num(r[8]), num(r[9])
        if old and new and new < old:
            drops.append({"name": norm(r[1]), "model": norm(r[2]),
                          "old": old, "new": new,
                          "pct": round((old - new) / old * 100, 1),
                          "date": parse_sheet_date(r[0])})
    drops.sort(key=lambda d: d["pct"], reverse=True)
    # dedupe by model name, keep biggest drop
    seen, out = set(), []
    for d in drops:
        if d["model"] in seen:
            continue
        seen.add(d["model"])
        out.append(d)
        if len(out) >= limit:
            break
    return out


# ------------------------------------------------------------------- shell
def head_html(title, desc, canonical, og_image=None, noindex=False,
              extra=""):
    ga = ""
    ga_id = ANALYTICS.get("google_analytics_id", "")
    if ga_id:
        ga = (f'<script async src="https://www.googletagmanager.com/gtag/js?id={ga_id}"></script>'
              f'<script>window.dataLayer=window.dataLayer||[];function gtag(){{dataLayer.push(arguments);}}'
              f'gtag("js",new Date());gtag("config","{ga_id}");</script>')
    verif = ""
    an = ANALYTICS
    if an.get("google_search_console_verification"):
        verif += (f'<meta name="google-site-verification" content="'
                  f'{esc(an["google_search_console_verification"])}">\n')
    if an.get("bing_webmaster_verification"):
        verif += (f'<meta name="msvalidate.01" content="'
                  f'{esc(an["bing_webmaster_verification"])}">\n')
    robots = ('<meta name="robots" content="noindex, nofollow">' if noindex
              else '<meta name="robots" content="index, follow, max-image-preview:large">')
    og = ""
    if og_image:
        og = (f'<meta property="og:image" content="{esc(og_image)}">\n'
              f'<meta name="twitter:card" content="summary_large_image">\n'
              f'<meta name="twitter:image" content="{esc(og_image)}">\n')
    return f"""<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{esc(title)}</title>
<meta name="description" content="{esc(desc)}">
{robots}
<link rel="canonical" href="{esc(canonical)}">
<link rel="alternate" hreflang="ar-eg" href="{esc(canonical)}">
<meta property="og:locale" content="ar_EG">
<meta property="og:type" content="website">
<meta property="og:site_name" content="{esc(SITE_NAME)}">
<meta property="og:title" content="{esc(title)}">
<meta property="og:description" content="{esc(desc)}">
<meta property="og:url" content="{esc(canonical)}">
{og}<link rel="icon" href="/assets/favicon.png" type="image/png">
<link rel="apple-touch-icon" href="/assets/icon-192.png">
<link rel="manifest" href="/manifest.json">
<meta name="theme-color" content="#0b5ed7">
<link rel="stylesheet" href="/assets/style.css?v=9">
{verif}{ga}{extra}"""


def header_html():
    return f"""<header class="site-header"><div class="container wide">
<a class="brand" href="/"><img src="/assets/logo.png" alt="{esc(SITE_NAME)} {DOMAIN}" width="162" height="56"></a>
<button id="nav-toggle" class="nav-toggle" type="button" aria-expanded="false" aria-controls="main-nav">{icon("menu")} القائمة</button>
<nav class="main-nav" id="main-nav">
<a href="/">الرئيسية</a><a href="/deals/">أفضل العروض</a><a href="/coupons/">الكوبونات</a><a href="/guides/">أدلة الشراء</a><a href="/news/">الأخبار</a><a href="/brands/">الماركات</a><a href="/about/">من نحن</a>
</nav>
<button id="theme-toggle" class="theme-toggle" type="button">{icon("sun")} الوضع النهاري</button>
<button id="pwa-install" class="theme-toggle" type="button" style="display:none">{icon("download")} ثبّت التطبيق</button>
</div></header>"""


def footer_html():
    return f"""<footer class="site-footer"><div class="container wide">
<div class="cols">
<div><h3>{esc(SITE_NAME)}</h3><p>مقارنة أسعار الهواتف في مصر.</p>
<p class="muted">آخر تحديث للأسعار من الشيت: {SHEET_UPDATED_DATE} — تُحدَّث كل ساعة.</p></div>
<div><h3>روابط سريعة</h3><a href="/coupons/">الكوبونات</a><a href="/deals/">أفضل العروض</a><a href="/guides/">أدلة الشراء</a><a href="/news/">الأخبار</a><a href="/budget/">البحث بالميزانية</a><a href="/search/specs/">بحث بالمواصفات</a><a href="/compare/">قارن بين الهواتف</a><a href="/about/">من نحن</a><a href="/contact/">اتصل بنا</a></div>
<div><h3>سياسات الموقع</h3><a href="/privacy/">سياسة الخصوصية</a><a href="/terms/">شروط الاستخدام</a><a href="/affiliate-disclosure/">إفصاح التسويق بالعمولة</a><a href="/cookies/">سياسة ملفات تعريف الارتباط</a></div>
<div><h3>تواصل معنا</h3><a href="mailto:{EMAIL}">{EMAIL}</a></div>
</div>
<div class="bottom">© 2026 {esc(SITE_NAME)} {DOMAIN} — جميع الحقوق محفوظة. الأسعار استرشادية والسعر النهائي هو سعر المتجر وقت الشراء.</div>
</div></footer>
<div class="compare-bar" id="compare-bar"><span id="compare-list"></span><button class="btn" id="compare-go" type="button">عرض المقارنة</button><button class="clear" id="compare-clear" type="button">مسح</button></div>
<div class="cookie-banner" id="cookie-banner"><div class="container wide">نستخدم ملفات تعريف الارتباط لتحسين تجربتك وعرض إعلانات مناسبة. <a href="/cookies/">اقرأ سياسة ملفات تعريف الارتباط</a>. <button class="btn" id="cookie-ok" type="button">موافق</button></div></div>
<button id="to-top" type="button" aria-label="العودة للأعلى">↑</button>
<div class="toast" id="toast" role="status"></div>
<script>window.SITE_CONFIG = {json.dumps({"adminApiUrl": ADMIN_API_URL, "onesignalAppId": ONESIGNAL_APP_ID, "contactEmail": EMAIL}, ensure_ascii=False)};</script>
<script src="/assets/app.js" defer></script>"""


def page_shell(title, desc, canonical, body, noindex=False, json_ld=None,
               og_image=None, hero=None, body_class=""):
    ld = ""
    if json_ld:
        ld = ('<script type="application/ld+json">\n'
              + json.dumps(json_ld, ensure_ascii=False) + '\n</script>')
    hero_html = hero or ""
    body_tag = '<body class="' + body_class + '">' if body_class else "<body>"
    return ("<!DOCTYPE html>\n<html lang=\"ar\" dir=\"rtl\" data-theme=\"dark\">\n<head>\n"
            + head_html(title, desc, canonical, og_image, noindex)
            + "\n" + ld + "\n</head>\n" + body_tag + "\n"
            + header_html() + "\n" + hero_html + "\n<main class=\"container wide\">\n"
            + body + "\n</main>\n" + footer_html() + "\n</body>\n</html>\n")


def org_ld():
    return {"@context": "https://schema.org", "@type": "Organization",
            "name": SITE_NAME, "url": BASE_URL + "/",
            "email": EMAIL,
            "logo": BASE_URL + "/assets/logo.png"}


def ad_slot(name):
    """AdSense slot: rendered only when enabled AND code is set.
    Fixed height reserves the space (audit ت-10, CLS)."""
    slot = ADS_SLOTS.get(name, {"code": "", "enabled": False, "height": 90})
    code = (slot.get("code") or "").strip()
    if slot.get("enabled") and code:
        check_no_forbidden(code, f"ad slot {name}")
        return (f'<div class="ad-slot" style="min-height:{int(slot.get("height", 90))}px">'
                f"{code}</div>")
    return f"<!-- ad slot {name}: disabled (no code in settings) -->"


def local_image_for(model):
    """Return local watermarked path if it exists, else None."""
    p = SITE / "images" / "products" / f"{model.slug}.jpg"
    return f"/images/products/{model.slug}.jpg" if p.exists() else None


def abs_image(model):
    local, remote, _ph = resolve_model_image(model)
    if local:
        return BASE_URL + local
    if remote and remote.startswith("/"):
        return BASE_URL + remote
    return remote or (BASE_URL + "/images/placeholder.jpg?v=2")


# ------------------------------------------------------------------- cards
def card_html(m):
    _local, _remote, _ph = resolve_model_image(m)
    img = _local or _remote
    disc = f'<span class="disc-badge">خصم {int(m.discount)}%</span>' if m.discount >= 5 else ""
    old = (f'<span class="old-price">{fmt_price(m.old_price)} جنيه</span>'
           if m.old_price and m.old_price > m.cheapest_price else "")
    rating = (f'<span class="rating">★ {m.rating} ({m.rating_count} تقييمات)</span>'
              if m.rating else "")
    g5 = " • يدعم 5G" if m.g5 else ""
    search_text = f"{m.name_en} {m.name_ar} {m.brand} {m.model}".lower()
    return f"""<article class="pcard" data-slug="{m.slug}" data-brand="{esc(m.brand)}" data-price="{m.cheapest_price:g}" data-discount="{m.discount}" data-rating="{m.rating or 0}" data-ram="{esc(m.ram)}" data-storage="{esc(m.storage)}" data-g5="{1 if m.g5 else 0}" data-instock="{1 if m.in_stock else 0}" data-updated="{m.last_update}" data-year="{m.year}" data-search="{esc(search_text)}">
<a href="/mobiles/{m.slug}/"><img src="{esc(img)}" alt="هاتف {esc(m.name_ar)} {esc(m.storage)} / {esc(m.ram)}" loading="lazy" decoding="async" width="500" height="500"></a>
<div class="pcard-body">
<h3><a href="/mobiles/{m.slug}/">{esc(m.name_ar)}</a></h3>
<div class="brand-line">{esc(m.brand)} {esc(m.model)} • {esc(m.storage)} / {esc(m.ram)}{g5}{(" • " + str(m.year)) if m.year else ""}</div>
<div class="price-row"><span class="price">{fmt_price(m.cheapest_price)} جنيه</span>{old}{disc}</div>
<div class="brand-line">{rating} • أرخص سعر في جوميا</div>
<div class="actions"><a class="btn-mini btn-prices" href="/mobiles/{m.slug}/">عرض الأسعار</a><button class="btn-mini btn-compare" type="button" data-compare="{m.slug}">قارن</button><button class="btn-mini btn-fav" type="button" data-fav="{m.slug}">♡ مفضلة</button></div>
</div></article>"""


# ------------------------------------------------------------------- index
def build_index():
    biggest = sorted(MODELS, key=lambda m: m.discount, reverse=True)[:8]
    cheapest = sorted(MODELS, key=lambda m: m.cheapest_price)[:8]
    drops = latest_drops(8)
    drop_cards = ""
    if drops:
        by_model = {m.model: m for m in MODELS}
        for d in drops:
            m = by_model.get(d["model"])
            if not m:
                continue
            drop_cards += (f'<li>{esc(d["name"])}: من {fmt_price(d["old"])} إلى '
                           f'{fmt_price(d["new"])} جنيه (انخفاض {d["pct"]}%) — '
                           f'<a href="/mobiles/{m.slug}/">عرض الهاتف</a></li>')
        drops_html = f"<ul>{drop_cards}</ul>"
    else:
        drops_html = ("<p>لا توجد انخفاضات مسجلة بعد — بدأ تتبع الأسعار في "
                      "19 نوفمبر 2026، وستظهر هنا أول الانخفاضات فور حدوثها.</p>")
    brands_opts = "".join(
        f'<option value="{esc(b)}">{esc(b)} ({sum(1 for m in MODELS if m.brand == b)})</option>'
        for b in BRANDS)
    rams = filter_size_opts({m.ram for m in MODELS}, 1)
    storages = filter_size_opts({m.storage for m in MODELS}, 32)
    ram_opts = "".join(f'<option value="{esc(r)}">{esc(r)}</option>' for r in rams)
    st_opts = "".join(f'<option value="{esc(s)}">{esc(s)}</option>' for s in storages)
    brand_chips = "".join(
        f'<button class="chip" type="button" data-brand="{esc(b)}">{esc(b)}</button>'
        for b in BRANDS)
    brand_cards = "".join(
        f'<a class="chip" href="/brand/{BRAND_SLUGS[b]}/">{esc(b)} ({sum(1 for m in MODELS if m.brand == b)})</a>'
        for b in BRANDS)
    newest_first = sorted(MODELS, key=lambda m: (-(m.year or 0), m.cheapest_price))
    latest = newest_first[:12]
    cards = "".join(card_html(m) for m in newest_first)
    hero_cls = ("hero-search hero-compact"
                if HOME_LAYOUT in ("compact", "luxury", "minimal")
                else "hero-search")
    hero = f"""<section class="{hero_cls}"><div class="container wide">
<h1>{esc(SITE_NAME)}</h1>
<p>قارن أسعار الهواتف في جوميا مصر وأمازون مصر ونون مصر، وتابع انخفاض الأسعار أولاً بأول.</p>
<div class="hero-search-row">
<form class="search-box" action="/search/" method="get" role="search">
<input type="search" name="q" id="hero-q" placeholder="ابحث عن هاتف…" aria-label="ابحث عن هاتف">
<button class="btn" type="submit">بحث</button>
</form>
<div class="hero-deals">
<a class="hero-deal-btn hero-deal-amazon" href="https://www.amazon.eg/deals?tag=amazon0c2aca6-21" target="_blank" rel="sponsored noopener">انقر للحصول على أفضل عروض أمازون مصر 2026</a>
<a class="hero-deal-btn hero-deal-jumia" href="https://jforce.jumia.com.eg/s/C4i51XK" target="_blank" rel="sponsored noopener">انقر للحصول على أفضل عروض جوميا مصر 2026</a>
</div>
</div>
<a class="request-banner" href="/#request-form">أخبرنا بطلبك في رسالة — يصلك أفضل خصم؟ <strong>اضغط هنا</strong></a>
</div></section>"""
    toolbar_html = f"""<div class="toolbar" id="filters">
<input type="search" id="filter-q" placeholder="ابحث بالاسم أو الموديل…" aria-label="بحث سريع" style="flex:1;min-width:180px">
<select id="filter-brand" aria-label="الماركة"><option value="">كل الماركات</option>{brands_opts}</select>
<select id="filter-ram" aria-label="الرام"><option value="">كل الرامات</option>{ram_opts}</select>
<select id="filter-storage" aria-label="التخزين"><option value="">كل التخزين</option>{st_opts}</select>
<input type="number" id="filter-maxprice" placeholder="حد أقصى للسعر (جنيه)" min="0" aria-label="حد أقصى للسعر">
<label class="check"><input type="checkbox" id="filter-5g"> يدعم 5G فقط</label>
<label class="check"><input type="checkbox" id="filter-instock"> المتوفر فقط</label>
<label class="check"><input type="checkbox" id="filter-favonly"> مفضلتي فقط</label>
<select id="sort-by" aria-label="ترتيب النتائج"><option value="newest" selected>الأحدث (سنة الإصدار)</option><option value="cheapest">الأرخص أولاً</option><option value="discount">الأكبر خصماً</option><option value="rating">الأعلى تقييماً</option><option value="latest">الأحدث تحديثاً</option></select>
</div>"""
    # الرئيسية بلا شريط فلاتر (نُقلت الفلاتر إلى صفحة «أفضل العروض»)
    toolbar_html = ""
    count_html = f'<div class="muted" id="results-count">عرض {len(MODELS)} هاتفاً</div>'
    chips_html = ""  # أزرار الماركات أعلى «أحدث المنتجات» أُزيلت بناءً على طلب المستخدم
    biggest_grid = f'<div class="section-head"><h2>{sec_icon("percent", "warm")} أكبر التخفيضات الآن</h2></div>\n<div class="grid">{"".join(card_html(m) for m in biggest)}</div>'
    biggest_row = f'<div class="section-head"><h2>{sec_icon("percent", "warm")} أكبر التخفيضات الآن</h2></div>\n<div class="row-scroll">{"".join(card_html(m) for m in biggest)}</div>'
    biggest_feat = f'<div class="section-head"><h2>{sec_icon("percent", "warm")} أكبر التخفيضات الآن</h2></div>\n<div class="grid grid-featured">{"".join(card_html(m) for m in biggest)}</div>'
    drops_sec = f'<div class="section-head"><h2>أحدث انخفاضات الأسعار</h2></div>\n{drops_html}'
    _bym = {m.model: m for m in MODELS}
    drops_models = [_bym[d["model"]] for d in drops if d["model"] in _bym]
    drops_cards = (f'<div class="section-head"><h2>أحدث انخفاضات الأسعار</h2></div>\n'
                   f'<div class="grid grid-featured">{"".join(card_html(m) for m in drops_models)}</div>'
                   if drops_models else drops_sec)
    cheapest_grid = f'<div class="section-head"><h2>أرخص الهواتف</h2></div>\n<div class="grid">{"".join(card_html(m) for m in cheapest)}</div>'
    cheapest_row = f'<div class="section-head"><h2>أرخص الهواتف</h2></div>\n<div class="row-scroll">{"".join(card_html(m) for m in cheapest)}</div>'
    latest_grid = f'<div class="section-head"><h2>أحدث المنتجات</h2></div>\n<div class="grid">{"".join(card_html(m) for m in latest)}</div>'
    latest_row = f'<div class="section-head"><h2>أحدث المنتجات</h2></div>\n<div class="row-scroll">{"".join(card_html(m) for m in latest)}</div>'
    latest_feat = f'<div class="section-head"><h2>أحدث المنتجات</h2></div>\n<div class="grid grid-featured">{"".join(card_html(m) for m in latest)}</div>'
    latest_list = f'<div class="section-head"><h2>أحدث المنتجات</h2></div>\n<div class="cards-list">{"".join(card_html(m) for m in latest)}</div>'
    all_grid = latest_grid + f'<div class="section-head" id="models"><h2>كل الهواتف ({len(MODELS)})</h2></div>\n<div class="grid" id="models-grid">{cards}</div>'
    all_row = latest_row + f'<div class="section-head" id="models"><h2>كل الهواتف ({len(MODELS)})</h2></div>\n<div class="row-scroll" id="models-grid">{cards}</div>'
    brands_html = f'<div class="section-head" id="brands"><h2>تسوق حسب الماركة</h2></div>\n<div class="chips">{brand_cards}</div>'
    brands_tiles = f'<div class="section-head" id="brands"><h2>تسوق حسب الماركة</h2></div>\n<div class="brand-tiles">{brand_cards}</div>'
    biggest_list = f'<div class="section-head"><h2>{sec_icon("percent", "warm")} أكبر التخفيضات الآن</h2></div>\n<div class="cards-list">{"".join(card_html(m) for m in biggest)}</div>'
    cheapest_list = f'<div class="section-head"><h2>أرخص الهواتف</h2></div>\n<div class="cards-list">{"".join(card_html(m) for m in cheapest)}</div>'
    cheapest_feat = f'<div class="section-head"><h2>أرخص الهواتف</h2></div>\n<div class="grid grid-featured">{"".join(card_html(m) for m in cheapest)}</div>'
    all_list = latest_list + f'<div class="section-head" id="models"><h2>كل الهواتف ({len(MODELS)})</h2></div>\n<div class="cards-list" id="models-grid">{cards}</div>'
    all_feat = latest_feat + f'<div class="section-head" id="models"><h2>كل الهواتف ({len(MODELS)})</h2></div>\n<div class="grid grid-featured" id="models-grid">{cards}</div>'
    drops_row = (f'<div class="section-head"><h2>أحدث انخفاضات الأسعار</h2></div>\n'
                 f'<div class="row-scroll">{"".join(card_html(m) for m in drops_models)}</div>'
                 if drops_models else drops_sec)
    request_html = f"""<section class="card" style="margin-top:26px">
<h2>لم تجد منتج؟ اطلبه وسنضيفه</h2>
<p>أخبرنا بالمنتج الذي تبحث عنه، وسنضيفه إلى المقارنة عند توفره.</p>
<form id="request-form">
<label for="request-model">اسم المنتج المطلوب</label>
<input type="text" id="request-model" required placeholder="مثال: Samsung Galaxy A56">
<label for="request-budget">ميزانيتك القصوى (جنيه) — اختياري</label>
<input type="number" id="request-budget" min="0" placeholder="مثال: 15000">
<label for="request-whatsapp">رقم الواتساب — اختياري (لإعلامك عند إضافته)</label>
<input type="tel" id="request-whatsapp" dir="ltr" style="text-align:right" placeholder="مثال: 01012345678">
<button class="btn" type="submit">أرسل الطلب</button>
</form>
</section>
<p style="text-align:center"><button class="btn btn-blue" id="pwa-install2" type="button" onclick="document.getElementById('pwa-install').click()">{icon("download")} ثبّت الموقع كتطبيق على هاتفك</button></p>"""
    if HOME_LAYOUT == "rows":
        # قوائم مدمجة: كل الهواتف أولاً كصف أفقي، والفلاتر في لوحة قابلة للطي
        body = (ad_slot("top")
                + f'<details class="filters-box" open><summary>الفلاتر والترتيب</summary>{toolbar_html}</details>'
                + count_html + chips_html + all_row + biggest_row + ad_slot("in_list")
                + drops_sec + cheapest_row + brands_html
                + ad_slot("bottom") + request_html)
    elif HOME_LAYOUT == "deals":
        # كل الهواتف أولاً ثم العروض ببطاقات كبيرة
        body = (ad_slot("top") + toolbar_html + count_html + chips_html
                + all_grid + biggest_feat + ad_slot("in_list") + drops_cards
                + cheapest_grid + brands_html
                + ad_slot("bottom") + request_html)
    elif HOME_LAYOUT == "store":
        # متجر: كل الهواتف أولاً ثم الماركات كبلاطات كبيرة
        body = (ad_slot("top") + toolbar_html + all_grid + brands_tiles
                + biggest_grid + ad_slot("in_list") + drops_cards
                + cheapest_grid
                + ad_slot("bottom") + request_html)
    elif HOME_LAYOUT == "compact":
        # مدمج: بطاقات أفقية مدمجة في كل الأقسام
        body = (ad_slot("top") + toolbar_html + count_html + chips_html
                + all_list + biggest_list + cheapest_list + brands_html
                + ad_slot("bottom") + request_html)
    elif HOME_LAYOUT == "luxury":
        # فاخر داكن: كل الهواتف أولاً ببطاقات كبيرة
        body = (ad_slot("top") + toolbar_html + count_html + chips_html
                + all_grid + biggest_feat + ad_slot("in_list") + drops_cards
                + cheapest_grid + brands_html
                + ad_slot("bottom") + request_html)
    elif HOME_LAYOUT == "forest":
        # أخضر: كل الهواتف أولاً ثم الأرخص
        body = (ad_slot("top") + toolbar_html + count_html + chips_html
                + all_grid + cheapest_grid + biggest_grid + ad_slot("in_list") + drops_sec
                + brands_html + ad_slot("bottom") + request_html)
    elif HOME_LAYOUT == "royal":
        # ملكي: كل الهواتف أولاً ثم الانخفاضات كبطاقات
        body = (ad_slot("top") + toolbar_html + count_html + chips_html
                + all_grid + drops_cards + biggest_feat + cheapest_grid
                + brands_html + ad_slot("bottom") + request_html)
    elif HOME_LAYOUT == "sunset":
        # غروب: كل الهواتف أولاً وشريط فلاتر ثابت
        body = (ad_slot("top") + toolbar_html + count_html + chips_html
                + all_grid + biggest_feat + ad_slot("in_list") + drops_sec
                + cheapest_grid + brands_html
                + ad_slot("bottom") + request_html)
    elif HOME_LAYOUT == "minimal":
        # بسيط: هيرو مدمج، كل الهواتف أولاً، بدون أقسام إضافية
        body = (ad_slot("top") + toolbar_html + count_html
                + all_grid + biggest_grid + brands_html
                + ad_slot("bottom") + request_html)
    elif HOME_LAYOUT == "showcase":
        # عرض كبير: كل الهواتف أولاً ببطاقات كبيرة
        body = (ad_slot("top") + toolbar_html + count_html + chips_html
                + all_feat + biggest_feat + ad_slot("in_list") + drops_cards
                + cheapest_feat + brands_tiles
                + ad_slot("bottom") + request_html)
    elif HOME_LAYOUT == "fullrows":
        # صفوف كاملة: كل الهواتف أولاً كصف أفقي
        body = (ad_slot("top")
                + f'<details class="filters-box" open><summary>الفلاتر والترتيب</summary>{toolbar_html}</details>'
                + count_html + chips_html + all_row + biggest_row + ad_slot("in_list")
                + drops_row + cheapest_row + brands_html
                + ad_slot("bottom") + request_html)
    elif HOME_LAYOUT == "quick":
        # سريع: شريط فلاتر ثابت وكل الهواتف أولاً ببطاقات مدمجة
        body = (ad_slot("top") + toolbar_html + count_html + chips_html
                + all_list + biggest_grid + cheapest_grid + brands_html
                + ad_slot("bottom") + request_html)
    else:
        # كلاسيكي: كل الهواتف أولاً ثم باقي الأقسام
        body = (ad_slot("top") + toolbar_html + count_html + chips_html
                + all_grid + biggest_grid + ad_slot("in_list") + drops_sec
                + cheapest_grid + brands_html
                + ad_slot("bottom") + request_html)
    faq_ld = {"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": [
        {"@type": "Question", "name": "كيف أقارن أسعار الهواتف في مصر؟",
         "acceptedAnswer": {"@type": "Answer", "text": "اختر الهاتف من القائمة وستظهر أسعاره في جوميا مصر وأمازون مصر ونون مصر مرتبة من الأرخص، مع تاريخ السعر ونسبة الخصم."}},
        {"@type": "Question", "name": "هل الأسعار على الموقع محدثة؟",
         "acceptedAnswer": {"@type": "Answer", "text": "نعم، تُحدَّث الأسعار كل ساعة من المتاجر، ويظهر تاريخ آخر تحديث على كل منتج."}},
        {"@type": "Question", "name": "كيف أعرف أن الخصم حقيقي؟",
         "acceptedAnswer": {"@type": "Answer", "text": "نعرض السعر الحالي بجانب السعر القديم وسجل الأسعار، فيمكنك التحقق من الانخفاض بنفسك قبل الشراء."}},
    ]}
    itemlist_ld = {"@context": "https://schema.org", "@type": "ItemList",
                   "name": "أكبر التخفيضات على الهواتف",
                   "itemListElement": [
                       {"@type": "ListItem", "position": i + 1,
                        "item": {"@type": "Product", "name": m.name_ar,
                                 "url": BASE_URL + f"/mobiles/{m.slug}/",
                                 "offers": {"@type": "Offer", "price": m.cheapest_price,
                                            "priceCurrency": "EGP"}}}
                       for i, m in enumerate(biggest)]}
    body_cls = f"layout-{HOME_LAYOUT}" + (f" theme-{HOME_THEME}" if HOME_THEME else "")
    return page_shell(
        f"{SITE_NAME} | قارن أسعار الهواتف في مصر — جوميا وأمازون ونون",
        f"قارن أسعار {len(MODELS)} موديل هاتف في جوميا مصر وأمازون مصر ونون مصر، وتابع أكبر التخفيضات وأحدث انخفاضات الأسعار.",
        BASE_URL + "/", body, hero=hero, body_class=body_cls,
        json_ld=[org_ld(), {"@context": "https://schema.org", "@type": "WebSite",
                             "name": SITE_NAME, "url": BASE_URL + "/",
                             "potentialAction": {"@type": "SearchAction",
                                               "target": BASE_URL + "/search/?q={search_term_string}",
                                               "query-input": "required name=search_term_string"}},
                 faq_ld, itemlist_ld])


# ----------------------------------------------------------------- product
def price_chart_svg(model):
    """Simple SVG line chart of daily minimum price (from سجل الأسعار)."""
    per_day = {}
    for d, p in model.history:
        per_day[d] = min(per_day.get(d, p), p)
    pts = sorted(per_day.items())
    if not pts:
        return "<p>لا يوجد تاريخ أسعار مسجل بعد لهذا الموديل.</p>"
    w, h, pad = 560, 170, 28
    prices = [p for _, p in pts]
    lo, hi = min(prices), max(prices)
    span = max(hi - lo, 1)
    if len(pts) == 1:
        d, p = pts[0]
        return (f'<svg viewBox="0 0 {w} {h}" width="100%" role="img" '
                f'aria-label="رسم بياني لتاريخ السعر"><circle cx="{w // 2}" cy="{h // 2}" r="7" fill="#0b5ed7"/>'
                f'<text x="{w // 2}" y="{h // 2 - 16}" text-anchor="middle" font-size="15" font-weight="bold">{fmt_price(p)} جنيه</text>'
                f'<text x="{w // 2}" y="{h - 8}" text-anchor="middle" font-size="13" fill="#5b6b7c">{d}</text></svg>'
                f'<p class="muted">نقطة سعر واحدة حتى الآن — بدأ تتبع هذا الهاتف في {pts[0][0]}، وستظهر حركة السعر هنا مع كل تغيّر.</p>')
    xs = [pad + i * (w - 2 * pad) / (len(pts) - 1) for i in range(len(pts))]
    ys = [h - pad - (p - lo) / span * (h - 2 * pad) for _, p in pts]
    points = " ".join(f"{x:.1f},{y:.1f}" for x, y in zip(xs, ys))
    dots = "".join(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4" fill="#0b5ed7"/>' for x, y in zip(xs, ys))
    labels = "".join(
        f'<text x="{x:.1f}" y="{h - 6}" text-anchor="middle" font-size="11" fill="#5b6b7c">{d[5:]}</text>'
        for x, (d, _) in zip(xs, pts))
    return (f'<svg viewBox="0 0 {w} {h}" width="100%" role="img" aria-label="رسم بياني لتاريخ السعر">'
            f'<polyline points="{points}" fill="none" stroke="#0b5ed7" stroke-width="2.5"/>{dots}{labels}'
            f'<text x="{pad}" y="16" font-size="13" font-weight="bold">أعلى سعر: {fmt_price(hi)} جنيه — أدنى سعر: {fmt_price(lo)} جنيه</text></svg>')


def faqs_for(model):
    cheapest = model.offers[0]
    faqs = [
        (f"ما سعر {model.name_ar} في مصر؟",
         f"أرخص سعر حالي هو {fmt_price(model.cheapest_price)} جنيه في جوميا مصر (البائع: {norm(c(cheapest, 'البائع'))})، وآخر تحديث للسعر في {model.last_update}. السعر النهائي هو سعر المتجر وقت الشراء."),
        (f"هل يدعم {model.name_ar} شبكة 5G؟",
         f"{'نعم، يدعم هذا الهاتف شبكات الجيل الخامس 5G.' if model.g5 else 'لا، هذا الهاتف لا يدعم شبكات الجيل الخامس 5G.'}"),
        (f"ما سعة بطارية {model.name_ar}؟",
         f"بطارية بسعة {norm(c(cheapest, 'البطارية'))}، وقدرة شحن {norm(c(cheapest, 'قدرة الشحن (واط)'))} واط."),
        (f"ما التخزين والرام في {model.name_ar}؟",
         f"التخزين {model.storage} والرام {model.ram}، وعدد الشرائح {norm(c(cheapest, 'عدد الشرائح'))}."),
        (f"ما الضمان على {model.name_ar}؟",
         f"{norm(c(cheapest, 'الضمان')) or 'حسب سياسة المتجر والبائع.'}"),
    ]
    return faqs


def split_list(text):
    return [p.strip() for p in re.split(r"[؛;]", str(text or "")) if p.strip()]


def build_product(model):
    cheapest = model.offers[0]
    cheapest_url = jumia_url(norm(c(cheapest, "رابط المنتج")), norm(c(cheapest, "رابط الأفلييت")))
    # badge logic (audit ت-4)
    badge = lowest_price_badge(model.history_days)
    badge_html = ""
    if badge:
        badge_html = f'<span class="lowest-badge">{badge}</span>'
    elif model.history:
        badge_html = (f'<span class="lowest-badge">أدنى سعر منذ بدء التتبع في '
                      f'{model.history[0][0]}</span>')
    verdict = discount_verdict(model.cheapest_price, model.avg_30d)
    # offers table
    rows_html = ""
    for i, r in enumerate(model.offers):
        price = num(c(r, "السعر الحالي (بعد الخصم) - جنيه"))
        old = num(c(r, "السعر قبل الخصم - جنيه"))
        gap = price - model.cheapest_price
        gap_html = ("—" if gap == 0 else
                    f'<span class="gap-up">+{fmt_price(gap)} جنيه (+{round(gap / model.cheapest_price * 100, 1)}%)</span>')
        disc = offer_discount(r)
        rating = num(c(r, "التقييم"))
        rc = int(num(c(r, "عدد التقييمات"), 0) or 0)
        rows_html += f"""<tr class="{'best-row' if i == 0 else ''}">
<td>{'<span class="best-badge">الأرخص</span>' if i == 0 else ''} {esc(norm(c(r, 'المتجر (جوميا / أمازون)')))}</td>
<td>{esc(norm(c(r, 'البائع')))}</td>
<td><strong>{fmt_price(price)} جنيه</strong></td>
<td>{fmt_price(old) + ' جنيه' if old else '—'}</td>
<td>{f'خصم {int(disc)}%' if disc else '—'}</td>
<td>{esc(availability_ar(c(r, 'التوفر')))}</td>
<td>{f'★ {rating} ({rc})' if rating else '—'}</td>
<td><a class="buy-mini" href="{esc(jumia_url(norm(c(r, 'رابط المنتج')), norm(c(r, 'رابط الأفلييت'))))}" {SPONSORED} data-store="jumia" data-model="{model.slug}" data-event="buy-click">اشترِ الآن</a></td>
</tr>"""
    # specs
    spec_rows = [
        ("الماركة", model.brand), ("الموديل", model.model),
        ("التخزين", model.storage), ("الرام", model.ram),
        ("الشاشة", norm(c(cheapest, "حجم الشاشة"))),
        ("المعالج", norm(c(cheapest, "المعالج"))),
        ("الكاميرا الخلفية", norm(c(cheapest, "الكاميرا الخلفية"))),
        ("الكاميرا الأمامية", norm(c(cheapest, "الكاميرا الأمامية"))),
        ("البطارية", norm(c(cheapest, "البطارية"))),
        ("قدرة الشحن", f"{norm(c(cheapest, 'قدرة الشحن (واط)'))} واط"),
        ("اللون", norm(c(cheapest, "اللون"))),
        ("نظام التشغيل", norm(c(cheapest, "نظام التشغيل"))),
        ("دعم 5G", "نعم" if model.g5 else "لا"),
        ("عدد الشرائح", norm(c(cheapest, "عدد الشرائح"))),
        ("سنة الإصدار", norm(c(cheapest, "سنة الإصدار"))),
        ("الضمان", norm(c(cheapest, "الضمان"))),
        ("الشحن / التوصيل", norm(c(cheapest, "الشحن / التوصيل"))),
    ]
    spec_html = "".join(
        f"<tr><td>{esc(k)}</td><td>{esc(v)}</td></tr>"
        for k, v in spec_rows if v)
    pros = split_list(c(cheapest, "المميزات"))
    cons = split_list(c(cheapest, "العيوب"))
    pros_html = ("<ul class='pros'>" + "".join(f"<li>{esc(p)}</li>" for p in pros) + "</ul>") if pros else "<p>لا توجد مميزات مسجلة بعد.</p>"
    cons_html = ("<ul class='cons'>" + "".join(f"<li>{esc(p)}</li>" for p in cons) + "</ul>") if cons else "<p>لا توجد عيوب مسجلة بعد.</p>"
    full_specs = norm(c(cheapest, "المواصفات الكاملة"))
    full_specs_html = ("<section class='card'><h2>المواصفات الكاملة</h2><p>"
                       + esc(full_specs).replace("؛", "<br>") + "</p></section>") if full_specs else ""
    # history table
    hist_rows = ""
    for d, p in sorted(model.history, reverse=True)[:30]:
        hist_rows += f"<tr><td>{d}</td><td>{fmt_price(p)} جنيه</td></tr>"
    hist_html = (f"<table class='data'><thead><tr><th>التاريخ</th><th>السعر</th></tr></thead>"
                 f"<tbody>{hist_rows}</tbody></table>") if hist_rows else "<p>لا يوجد تاريخ أسعار مسجل بعد.</p>"
    # alternative + related
    others = [m for m in MODELS if m.slug != model.slug]
    alt = min(others, key=lambda m: (0 if m.brand == model.brand else 1,
                                     abs(m.cheapest_price - model.cheapest_price)))
    related = sorted([m for m in others if m.brand == model.brand],
                     key=lambda m: abs(m.cheapest_price - model.cheapest_price))[:4]
    alt_html = card_html(alt)
    rel_html = "".join(card_html(m) for m in related)
    # back-in-stock alert: shown when the phone is out of stock, or when the
    # cheapest offer is nearly gone (<= 2 units left) — currently no model is
    # fully out of stock, so the scarce case is what renders in practice.
    _cheap_units = units_left(c(cheapest, "التوفر"))
    stock_alert_html = ""
    if not model.in_stock:
        stock_alert_html = f"""<section class="card stock-alert-box"><h2>أخبرني عند التوفر</h2>
<p>هذا الهاتف غير متوفر حالياً — اترك رقم واتساب وسنخبرك فور توفره.</p>
<form id="stock-alert-form" data-model="{model.slug}">
<label for="stock-whatsapp">رقم الواتساب</label>
<input type="tel" id="stock-whatsapp" dir="ltr" style="text-align:right" placeholder="مثال: 01012345678" required>
<button class="btn" type="submit">أخبرني عند التوفر</button>
</form>
<p class="muted">سنراسلك على واتساب فقط عند توفر الهاتف — لا رسائل دعائية.</p></section>"""
    elif _cheap_units is not None and _cheap_units <= 2:
        stock_alert_html = f"""<section class="card stock-alert-box"><h2>أخبرني عند التوفر</h2>
<p>بقي عدد محدود جداً من هذا الهاتف بأرخص سعر ({'وحدة واحدة' if _cheap_units == 1 else 'وحدتان'} فقط) — اترك رقم واتساب وسنخبرك فور توفر كمية جديدة.</p>
<form id="stock-alert-form" data-model="{model.slug}">
<label for="stock-whatsapp">رقم الواتساب</label>
<input type="tel" id="stock-whatsapp" dir="ltr" style="text-align:right" placeholder="مثال: 01012345678" required>
<button class="btn" type="submit">أخبرني عند التوفر</button>
</form>
<p class="muted">سنراسلك على واتساب فقط عند توفر الهاتف — لا رسائل دعائية.</p></section>"""
    faqs = faqs_for(model)
    faq_html = "".join(
        f"<details class='faq-item'><summary>{esc(q)}</summary><p>{esc(a)}</p></details>"
        for q, a in faqs)
    share_url = f"{BASE_URL}/mobiles/{model.slug}/"
    share_text = quote_plus(f"سعر {model.name_ar} في مصر: {fmt_price(model.cheapest_price)} جنيه — قارن الأسعار على {SITE_NAME}")
    desc = (f"سعر {model.name_ar} في مصر: أرخص سعر {fmt_price(model.cheapest_price)} جنيه "
            f"في جوميا مصر. قارن بين جوميا وأمازون ونون، وتابع تاريخ السعر والمواصفات الكاملة والمميزات والعيوب.")
    check_no_forbidden(desc, f"product {model.slug}")
    # JSON-LD
    offers_ld = []
    for r in model.offers:
        price = num(c(r, "السعر الحالي (بعد الخصم) - جنيه"))
        offers_ld.append({
            "@type": "Offer", "price": price, "priceCurrency": "EGP",
            "availability": ("https://schema.org/InStock" if availability_in_stock(c(r, "التوفر"))
                             else "https://schema.org/OutOfStock"),
            "url": jumia_url(norm(c(r, "رابط المنتج")), norm(c(r, "رابط الأفلييت"))),
            "seller": {"@type": "Organization", "name": norm(c(r, "البائع")) or "جوميا"},
        })
    product_ld = {
        "@type": "Product", "name": model.name_ar,
        "alternateName": model.name_en,
        "image": abs_image(model), "description": desc,
        "brand": {"@type": "Brand", "name": model.brand},
        "offers": {"@type": "AggregateOffer",
                   "lowPrice": model.cheapest_price,
                   "highPrice": max(o["price"] for o in offers_ld),
                   "priceCurrency": "EGP", "offerCount": len(offers_ld),
                   "offers": offers_ld},
    }
    if model.rating and model.rating_count:
        product_ld["aggregateRating"] = {
            "@type": "AggregateRating", "ratingValue": model.rating,
            "reviewCount": model.rating_count}
    json_ld = [product_ld,
               {"@context": "https://schema.org", "@type": "BreadcrumbList",
                "itemListElement": [
                    {"@type": "ListItem", "position": 1, "name": "الرئيسية",
                     "item": BASE_URL + "/"},
                    {"@type": "ListItem", "position": 2, "name": model.brand,
                     "item": f"{BASE_URL}/brand/{BRAND_SLUGS[model.brand]}/"},
                    {"@type": "ListItem", "position": 3, "name": model.name_ar,
                     "item": share_url}]},
               {"@context": "https://schema.org", "@type": "FAQPage",
                "mainEntity": [{"@type": "Question", "name": q,
                                "acceptedAnswer": {"@type": "Answer", "text": a}}
                               for q, a in faqs]}]
    body = f"""<p class="muted"><a href="/">الرئيسية</a> › <a href="/brand/{BRAND_SLUGS[model.brand]}/">{esc(model.brand)}</a> › {esc(model.name_ar)}</p>
<div class="product-top">
<div class="product-img"><img src="{esc((lambda _l, _r, _p: _l or _r)(*resolve_model_image(model)))}" alt="هاتف {esc(model.name_ar)} {esc(model.storage)} / {esc(model.ram)}" width="500" height="500"></div>
<div>
<h1>{esc(model.name_ar)}</h1>
<p class="muted">{esc(model.name_en)} • {esc(model.brand)} {esc(model.model)} • {esc(model.storage)} / {esc(model.ram)}{' • يدعم 5G' if model.g5 else ''}</p>
<div class="price-row"><span class="price" style="font-size:2rem">{fmt_price(model.cheapest_price)} جنيه</span>
{f'<span class="old-price">{fmt_price(model.old_price)} جنيه</span>' if model.old_price and model.old_price > model.cheapest_price else ''}
{f'<span class="disc-badge">خصم {int(model.discount)}%</span>' if model.discount >= 5 else ''}</div>
<p>{badge_html}</p>
<p>{'★ ' + str(model.rating) + f' ({model.rating_count} تقييمات)' if model.rating else ''} • التوفر: {esc(availability_ar(c(cheapest, 'التوفر')))}</p>
<p class="muted">آخر تحديث للسعر: <strong>{model.last_update}</strong> — المصدر: <a href="{esc(cheapest_url)}" rel="nofollow noopener" target="_blank">صفحة المنتج في جوميا</a></p>
{buy_buttons(model.slug, model.display, cheapest_url, norm(c(cheapest, "المتجر (جوميا / أمازون)")))}
<div class="share-row">
<a class="share-wa" href="https://wa.me/?text={share_text}%20{quote_plus(share_url)}" rel="nofollow noopener" target="_blank">مشاركة واتساب</a>
<a class="share-tg" href="https://t.me/share/url?url={quote_plus(share_url)}&amp;text={share_text}" rel="nofollow noopener" target="_blank">مشاركة تليجرام</a>
<a class="share-fb" href="https://www.facebook.com/sharer/sharer.php?u={quote_plus(share_url)}" rel="nofollow noopener" target="_blank">مشاركة فيسبوك</a>
<button class="btn-mini btn-fav" type="button" data-fav="{model.slug}">♡ مفضلة</button>
<button class="btn-mini btn-compare" type="button" data-compare="{model.slug}">قارن</button>
</div>
</div></div>
{ad_slot("in_product")}
<section class="card"><h2>كل العروض على {esc(model.name_ar)} — من الأرخص</h2>
<p class="muted">فرق السعر بين أرخص وأغلى عرض: {fmt_price(max(o['price'] for o in offers_ld) - model.cheapest_price)} جنيه ({round((max(o['price'] for o in offers_ld) - model.cheapest_price) / model.cheapest_price * 100, 1)}%).</p>
<div style="overflow-x:auto"><table class="offers"><thead><tr><th>المتجر</th><th>البائع</th><th>السعر</th><th>قبل الخصم</th><th>الخصم</th><th>التوفر</th><th>التقييم</th><th>شراء</th></tr></thead><tbody>{rows_html}</tbody></table></div>
<p class="muted">الأسعار استرشادية وتُحدَّث كل ساعة. السعر النهائي هو سعر المتجر وقت الشراء.</p></section>
{stock_alert_html}
<section class="card"><h2>تاريخ سعر {esc(model.name_ar)}</h2>
{price_chart_svg(model)}
{hist_html}
<p class="muted">أدنى سعر مسجل: {fmt_price(model.min_price)} جنيه — أعلى سعر مسجل: {fmt_price(model.max_price)} جنيه.</p>
{f'<p><strong>{esc(verdict)}</strong></p>' if verdict else ''}
</section>
<section class="card"><h2>المواصفات الكاملة</h2><table class="spec-table">{spec_html}</table></section>
{full_specs_html}
<section class="card"><h2>المميزات والعيوب</h2><h3>المميزات</h3>{pros_html}<h3>العيوب</h3>{cons_html}</section>
<section class="install-box"><h2>حاسبة التقسيط</h2>
<label for="inst-price">سعر الهاتف (جنيه)</label>
<input type="number" id="inst-price" value="{int(model.cheapest_price)}" min="0">
<label for="inst-months">مدة التقسيط</label>
<select id="inst-months"><option value="6">6 أشهر</option><option value="12" selected>12 شهراً</option><option value="18">18 شهراً</option><option value="24">24 شهراً</option></select>
<p class="install-result" id="inst-result"></p>
<p class="muted">أرقام تقريبية للاسترشاد فقط؛ القسط الفعلي والفوائد حسب البنك أو المتجر وقت الشراء.</p></section>
<section class="card"><h2>هاتف بديل بنفس السعر تقريباً</h2><div class="grid">{alt_html}</div></section>
<section class="card"><h2>أسئلة شائعة عن {esc(model.name_ar)}</h2>{faq_html}</section>
<section class="card"><h2>أبلغ عن سعر غير صحيح</h2>
<p>وجدت سعراً مختلفاً في المتجر؟ أخبرنا وسنراجعه فوراً.</p>
<form id="report-form" data-model="{model.slug}">
<label for="report-price">السعر الصحيح الذي وجدته (جنيه) — اختياري</label>
<input type="number" id="report-price" min="0">
<label for="report-note">ملاحظاتك</label>
<textarea id="report-note" placeholder="مثال: السعر في جوميا الآن 11,999 وليس 12,459"></textarea>
<button class="btn" type="submit">أرسل البلاغ</button>
</form></section>
{f'<div class="section-head"><h2>هواتف {esc(model.brand)} أخرى</h2></div><div class="grid">{rel_html}</div>' if related else ''}"""
    return page_shell(
        f"سعر {model.name_ar} في مصر {model.last_update[:4]} — {fmt_price(model.cheapest_price)} جنيه | {SITE_NAME}",
        desc, share_url, body, json_ld=json_ld, og_image=abs_image(model))


# ------------------------------------------------------------------- brand
def build_brand(brand):
    models = [m for m in MODELS if m.brand == brand]
    slug = BRAND_SLUGS[brand]
    cheapest = min(m.cheapest_price for m in models)
    cards = "".join(card_html(m) for m in sorted(models, key=lambda m: m.cheapest_price))
    body = f"""<p class="muted"><a href="/">الرئيسية</a> › {esc(brand)}</p>
<section class="page-hero" style="margin:0 -18px 20px;padding:22px 18px"><h1 style="margin:0">أسعار هواتف {esc(brand)} في مصر</h1>
<p>{len(models)} موديلاً — يبدأ من {fmt_price(cheapest)} جنيه. آخر تحديث: {SHEET_UPDATED_DATE}.</p></section>
<div class="grid">{cards}</div>"""
    ld = {"@context": "https://schema.org", "@type": "ItemList",
          "name": f"أسعار هواتف {brand} في مصر",
          "itemListElement": [{"@type": "ListItem", "position": i + 1,
                               "url": f"{BASE_URL}/mobiles/{m.slug}/",
                               "name": m.name_ar}
                              for i, m in enumerate(sorted(models, key=lambda m: m.cheapest_price))]}
    return page_shell(
        f"أسعار هواتف {brand} في مصر — {SITE_NAME}",
        f"قارن أسعار {len(models)} موديل من هواتف {brand} في جوميا مصر وأمازون مصر ونون مصر. يبدأ من {fmt_price(cheapest)} جنيه.",
        f"{BASE_URL}/brand/{slug}/", body, json_ld=ld)




def build_brands_index():
    """Dedicated /brands/ page: stores section on top, then a professional
    grid of ALL brands with their logos (Clearbit, text-tile fallback)."""
    stores = get_stores()
    store_cards = ""
    for i, st in enumerate(stores):
        fb_id = f"store-fb-{i}"
        store_cards += (
            f'<a class="store-card" href="{esc(st["url"])}" target="_blank" '
            f'rel="sponsored noopener">'
            f'<span class="brand-logo">'
            f'{logo_img_html(st["logo"], st["name"], fb_id)}</span>'
            f'<span class="brand-card-name">{esc(st["name"])}</span>'
            f'<span class="brand-card-count">تسوّق الآن ←</span></a>')
    stores_sec = ""
    if store_cards:
        stores_sec = (f'<div class="section-head"><h2>{sec_icon("tag")} '
                      f'المتاجر</h2></div>'
                      f'<p class="muted">تسوّق من أشهر متاجر الهواتف في مصر '
                      f'— روابط مختارة من فريق {esc(SITE_NAME)}.</p>'
                      f'<div class="store-grid">{store_cards}</div>')
    cards = ""
    for b in BRANDS:
        count = sum(1 for m in MODELS if m.brand == b)
        slug = BRAND_SLUGS[b]
        fb_id = f"brand-fb-{slug}"
        cards += (
            f'<a class="brand-card" href="/brand/{slug}/">'
            f'<span class="brand-logo">'
            f'{logo_img_html(brand_logo_url(b), b, fb_id)}</span>'
            f'<span class="brand-card-name">{esc(b)}</span>'
            f'<span class="brand-card-count">{count} موديلاً</span></a>')
    body = f"""<p class="muted"><a href="/">الرئيسية</a> › الماركات</p>
<h1>تسوق حسب الماركة</h1>
<p>كل ماركات الهواتف المتوفرة في مصر على {esc(SITE_NAME)} — اضغط على أي ماركة لعرض هواتفها وأسعارها في جوميا وأمازون ونون.</p>
{stores_sec}
<div class="section-head"><h2>{sec_icon("star")} كل الماركات ({len(BRANDS)})</h2></div>
<div class="brand-logo-grid">{cards}</div>"""
    ld = {"@context": "https://schema.org", "@type": "ItemList",
          "name": f"ماركات الهواتف في مصر — {SITE_NAME}",
          "itemListElement": [{"@type": "ListItem", "position": i + 1,
                               "url": f"{BASE_URL}/brand/{BRAND_SLUGS[b]}/",
                               "name": b}
                              for i, b in enumerate(BRANDS)]}
    return page_shell(
        f"ماركات الهواتف في مصر — {SITE_NAME}",
        f"تصفح كل ماركات الهواتف في مصر ({len(BRANDS)} ماركة): سامسونج وآيفون وشاومي وأوبو وغيرها، وقارن أسعارها في جوميا مصر وأمازون مصر ونون مصر.",
        f"{BASE_URL}/brands/", body, json_ld=ld)

# ------------------------------------------------------------------- deals
DEALS_RESET_SCRIPT = """<script>
(function () {
  var btn = document.getElementById('deals-reset');
  if (!btn) return;
  btn.addEventListener('click', function () {
    ['filter-q', 'filter-brand', 'filter-ram', 'filter-storage', 'filter-maxprice'].forEach(function (id) {
      var e = document.getElementById(id);
      if (e) { e.value = ''; e.dispatchEvent(new Event('input')); }
    });
    ['filter-5g', 'filter-instock', 'filter-favonly'].forEach(function (id) {
      var e = document.getElementById(id);
      if (e) { e.checked = false; e.dispatchEvent(new Event('change')); }
    });
    var s = document.getElementById('sort-by');
    if (s) { s.value = 'discount'; s.dispatchEvent(new Event('change')); }
  });
})();
</script>"""


def build_deals_page():
    """Dedicated /deals/ page («أفضل العروض»): ALL products as cards with a
    professional filter panel. Reuses the homepage toolbar element IDs so
    assets/app.js applyFilters() works unchanged (no JS changes needed)."""
    brands_opts = "".join(
        f'<option value="{esc(b)}">{esc(b)} ({sum(1 for m in MODELS if m.brand == b)})</option>'
        for b in BRANDS)
    rams = filter_size_opts({m.ram for m in MODELS}, 1)
    storages = filter_size_opts({m.storage for m in MODELS}, 32)
    ram_opts = "".join(f'<option value="{esc(r)}">{esc(r)}</option>' for r in rams)
    st_opts = "".join(f'<option value="{esc(s)}">{esc(s)}</option>' for s in storages)
    # best deals first: newest (release year), then cheapest
    deals = sorted(MODELS, key=lambda m: (-(m.year or 0), m.cheapest_price))
    cards = "".join(card_html(m) for m in deals)
    filters_html = f"""<section class="deals-filters" aria-label="تصفية العروض">
<div class="deals-filters-head"><h2>صفِّ العروض حسب احتياجك</h2>
<button class="deals-reset" type="button" id="deals-reset">مسح الفلاتر ✕</button></div>
<div class="deals-filters-row">
<div class="field field-search"><label for="filter-q">ابحث بالاسم</label>
<input type="search" id="filter-q" placeholder="A56" aria-label="بحث سريع"></div>
<div class="field"><label for="filter-brand">الماركة</label>
<select id="filter-brand" aria-label="الماركة"><option value="">كل الماركات</option>{brands_opts}</select></div>
<div class="field"><label for="filter-ram">الرام</label>
<select id="filter-ram" aria-label="الرام"><option value="">كل الرامات</option>{ram_opts}</select></div>
<div class="field"><label for="filter-storage">التخزين</label>
<select id="filter-storage" aria-label="التخزين"><option value="">كل التخزين</option>{st_opts}</select></div>
<div class="field"><label for="filter-maxprice">أقصى سعر</label>
<input type="number" id="filter-maxprice" placeholder="15000" min="0" aria-label="حد أقصى للسعر"></div>
<div class="field"><label for="sort-by">ترتيب النتائج</label>
<select id="sort-by" aria-label="ترتيب النتائج"><option value="newest" selected>الأحدث (سنة الإصدار)</option><option value="cheapest">الأرخص أولاً</option><option value="discount">الأكبر خصماً</option><option value="rating">الأعلى تقييماً</option><option value="latest">الأحدث تحديثاً</option></select></div>
<label class="check"><input type="checkbox" id="filter-5g"> يدعم 5G فقط</label>
<label class="check"><input type="checkbox" id="filter-instock"> المتوفر فقط</label>
<label class="check"><input type="checkbox" id="filter-favonly"> مفضلتي فقط</label>
<span class="muted" id="results-count">عرض {len(MODELS)} هاتفاً</span>
</div>
</section>"""
    body = f"""<p class="muted"><a href="/">الرئيسية</a> › أفضل العروض</p>
<h1>أفضل العروض 2026</h1>
<p>أقوى عروض وتخفيضات الهواتف في مصر لعام 2026 — قارن أسعار {len(MODELS)} هاتفاً في جوميا مصر وأمازون مصر ونون مصر، وصفِّ النتائج بالمارة والرام والتخزين والسعر ودعم 5G لتصل إلى أفضل صفقة بأسرع وقت.</p>
{filters_html}
<div class="grid" id="models-grid">{cards}</div>
{DEALS_RESET_SCRIPT}"""
    top = deals[:10]
    ld = {"@context": "https://schema.org", "@type": "ItemList",
          "name": f"أفضل عروض الهواتف في مصر 2026 — {SITE_NAME}",
          "itemListElement": [{"@type": "ListItem", "position": i + 1,
                               "url": f"{BASE_URL}/mobiles/{m.slug}/",
                               "name": m.name_ar}
                              for i, m in enumerate(top)]}
    return page_shell(
        f"أفضل العروض 2026 — {SITE_NAME}",
        f"أفضل عروض الهواتف في مصر 2026: قارن أسعار {len(MODELS)} هاتفاً في جوميا مصر وأمازون مصر ونون مصر، وصفِّ النتائج حسب الماركة والرام والتخزين والسعر ودعم 5G.",
        f"{BASE_URL}/deals/", body, json_ld=ld,
        og_image=abs_image(top[0]) if top else None)


# ----------------------------------------------------------------- coupons
# Store identity for coupon boxes: Arabic display name, local logo file,
# and the shop-button colour class. Keys are the admin form values
# (jumia/amazon/noon); STORE_ALIASES also accepts the Arabic names that
# older rows in the Sheet / coupons.json may carry.
STORE_META = {
    "jumia": ("جوميا", "/assets/store-logos/jumia.png", "shop-jumia"),
    "amazon": ("أمازون", "/assets/store-logos/amazon.svg", "shop-amazon"),
    "noon": ("نون", "/assets/store-logos/noon.svg", "shop-noon"),
}
STORE_ALIASES = {"جوميا": "jumia", "أمازون": "amazon", "امازون": "amazon",
                 "نون": "noon", "jumia": "jumia", "amazon": "amazon",
                 "noon": "noon"}


def store_home(key):
    """Tracked homepage of a store (fallback when a coupon has no
    redirect_url of its own)."""
    if key == "jumia":
        return jumia_home()
    if key == "amazon":
        return (f"https://www.amazon.eg/?tag={AMAZON_TAG}"
                if AMAZON_TAG else "https://www.amazon.eg/")
    if key == "noon":
        return "https://www.noon.com/egypt-en/"
    return ""


def coupon_is_expired(expires_at):
    """True when an expiry date (YYYY-MM-DD) has passed (today, Cairo
    calendar date — the site's audience is in Egypt)."""
    exp = (expires_at or "").strip()
    if not exp:
        return False
    try:
        d = datetime.strptime(exp[:10], "%Y-%m-%d").date()
    except ValueError:
        return False
    return d < date.today()


def build_coupons():
    data = load_json(DATA / "coupons.json")
    cards = ""
    ld_items = []
    for pos, cp in enumerate(data.get("coupons", []), 1):
        if not cp.get("active", True):
            continue
        key = STORE_ALIASES.get((cp.get("store") or "").strip().lower(), "")
        name, logo, shop_cls = STORE_META.get(
            key, (cp.get("store", ""), "", ""))
        redirect = (cp.get("redirect_url") or "").strip()
        if key == "jumia":
            # Jumia coupon -> the user's tracked Arabic homepage
            redirect = jumia_home()
        elif not redirect:
            redirect = store_home(key)
        example = ('<p><span class="example-tag">مثال — يُستبدل بكوبون حقيقي</span></p>'
                   if cp.get("is_example") else "")
        exp = (cp.get("expires_at") or "").strip()
        expired = coupon_is_expired(exp)
        desc = (cp.get("description") or "").strip()
        desc_html = (f'<p class="coupon-desc">{esc(desc)}</p>' if desc else "")
        if expired:
            exp_html = '<p class="coupon-expired-note">انتهى هذا الكوبون</p>'
            copy_html = ('<button class="coupon-copy-btn" type="button" '
                         'disabled>منتهي</button>')
        else:
            exp_html = (f'<p class="coupon-expiry">ينتهي في: '
                        f'<span class="countdown" data-countdown="{esc(exp)}">'
                        f'{esc(exp)}</span></p>' if exp else "")
            # زر واحد موحّد: ينسخ الكود ثم يحوّل إلى المتجر
            copy_html = (f'<button class="coupon-go-btn {shop_cls}" type="button" '
                         f'data-copy-code="{esc(cp.get("code", ""))}" '
                         f'data-redirect="{esc(redirect)}">'
                         f'انسخ الكود وانتقل إلى {esc(name)}</button>')
        logo_html = (f'<img src="{esc(logo)}" alt="{esc(name)}" '
                     f'loading="lazy" decoding="async">' if logo else
                     f'<span class="coupon-logo-fallback">{esc(name[:1])}</span>')
        box_cls = "coupon-box" + (" coupon-expired" if expired else "")
        # البطاقة كلها قابلة للنقر (إن لم يكن الكوبون منتهياً): نسخ الكود + فتح المتجر في تبويب جديد
        # (closest() يلتقط أقرب عنصر — الكود/الزر الداخليان أولاً، ثم البطاقة).
        card_click = (f' data-copy-code="{esc(cp.get("code", ""))}" data-redirect="{esc(redirect)}" style="cursor:pointer" title="اضغط لنسخ الكود والانتقال إلى المتجر"' if not expired else "")
        cards += f"""<article class="{box_cls}"{card_click}>
<div class="coupon-box-head">
<span class="coupon-logo">{logo_html}</span>
<div class="coupon-box-titles"><div class="coupon-store">{esc(name)}</div>
<h3>{esc(cp.get('title', ''))}</h3></div>
<div class="coupon-value">{esc(cp.get('value', ''))}</div>
</div>
{example}{desc_html}
<div class="coupon-code-row">
<span class="coupon-code coupon-code-click" dir="ltr" title="اضغط للنسخ والانتقال إلى المتجر" data-copy-code="{esc(cp.get('code', ''))}" data-redirect="{esc(redirect)}">{esc(cp.get('code', ''))}</span>
</div>
{exp_html}
{copy_html}
<p class="muted">الكوبون خاص بالمتجر، وليس بموقعنا. الضغط على الكود أو الزر ينسخ الكود ثم يحوّلك إلى موقع المتجر لاستخدامه عند الشراء.</p>
</article>"""
        ld_items.append({"@type": "ListItem", "position": pos,
                         "name": cp.get("title", ""),
                         "description": cp.get("value", "")})
    hero = """<section class="page-hero" style="margin:0 -18px 20px;padding:22px 18px"><h1 style="margin:0">كوبونات خصم الهواتف في مصر</h1>
<p>انسخ الكود بضغطة واحدة، ثم انتقل إلى المتجر واستخدمه عند الشراء.</p></section>"""
    body = hero + (f'<div class="coupons-grid">{cards}</div>' if cards else
                   '<p>لا توجد كوبونات حالياً — تابعنا، نضيف كوبونات جديدة باستمرار.</p>')
    json_ld = {"@context": "https://schema.org", "@type": "ItemList",
               "name": "كوبونات خصم الهواتف في مصر",
               "itemListElement": ld_items} if ld_items else None
    return page_shell("كوبونات خصم الهواتف في مصر | " + SITE_NAME,
                      "أكواد خصم هواتف جوميا وأمازون ونون في مصر. انسخ الكود بضغطة واحدة وانتقل إلى المتجر لاستخدامه.",
                      BASE_URL + "/coupons/", body, json_ld=json_ld)


# ------------------------------------------------------------------ guides
def guide_candidates(criterion):
    if criterion == "under_10000":
        pool = [m for m in MODELS if m.cheapest_price < 10000]
        return sorted(pool, key=lambda m: (-(m.rating or 0), m.cheapest_price))[:5]
    if criterion == "battery":
        def mah(m):
            v = num(re.sub(r"[^\d.]", "", norm(c(m.offers[0], "البطارية"))), 0) or 0
            return v
        return sorted(MODELS, key=lambda m: (-mah(m), m.cheapest_price))[:5]
    if criterion == "camera":
        def mp(m):
            mm = re.search(r"(\d+)\s*MP", norm(c(m.offers[0], "الكاميرا الخلفية")))
            return float(mm.group(1)) if mm else 0
        return sorted(MODELS, key=lambda m: (-mp(m), m.cheapest_price))[:5]
    if criterion == "gaming":
        # أقوى رام أولاً، ثم الأعلى تقييماً، ثم الأرخص
        def ram_gb(m):
            s = norm(m.ram).upper()
            mm = re.search(r"([\d.]+)\s*GB", s)
            if mm:
                return float(mm.group(1))
            mm = re.search(r"([\d.]+)\s*MB", s)
            if mm:
                return float(mm.group(1)) / 1024.0
            return 0
        return sorted(MODELS, key=lambda m: (-ram_gb(m), -(m.rating or 0),
                                             m.cheapest_price))[:5]
    return []


GUIDE_TAGS = {
    "under_10000": ["أقل من 10,000 جنيه", "هواتف اقتصادية", "دليل شراء"],
    "battery": ["بطارية كبيرة", "عمر البطارية", "دليل شراء"],
    "camera": ["كاميرا", "تصوير", "دليل شراء"],
    "gaming": ["ألعاب", "أداء قوي", "دليل شراء"],
}


def guide_tags(g):
    """Tags for a guide: explicit 'tags' field if present, else derived
    from its criterion (no invented content — only the guide's own data)."""
    tags = g.get("tags") or []
    if tags:
        return [norm(t) for t in tags if norm(t)]
    return GUIDE_TAGS.get(g.get("criterion", ""), ["دليل شراء"])


def news_tags(p, model=None):
    """Tags for a news post: explicit 'tags' field if present, else derived
    from the linked model's brand + keywords in the title."""
    tags = p.get("tags") or []
    if tags:
        return [norm(t) for t in tags if norm(t)]
    out = []
    if model:
        out.append(model.brand)
    title = p.get("title", "")
    if any(w in title for w in ("انخفاض", "خصم", "تخفيض", "رخص")):
        out.append("انخفاض الأسعار")
    if any(w in title for w in ("إطلاق", "جديد", "وصل")):
        out.append("إطلاق جديد")
    out.append("أخبار")
    return out


def tag_chips(tags):
    """Clickable tag chips (each links to a search for that tag)."""
    if not tags:
        return ""
    chips = "".join(
        f'<a class="tag-chip" href="/search/?q={quote_plus(t)}">{esc(t)}</a>'
        for t in tags)
    return f'<div class="tag-chips">{chips}</div>'


def guide_hero_image(g):
    """Header image for a guide: the first candidate phone's image
    (local watermarked file if present, else its remote URL)."""
    cands = guide_candidates(g.get("criterion", ""))
    if not cands:
        return "", ""
    local, remote, _ph = resolve_model_image(cands[0])
    src = local or remote or ""
    abs_src = (BASE_URL + src) if src.startswith("/") else src
    return src, abs_src


def build_guide(g):
    cands = guide_candidates(g.get("criterion", ""))
    rows = ""
    for m in cands:
        rows += (f"<tr><td><a href='/mobiles/{m.slug}/'>{esc(m.name_ar)}</a></td>"
                 f"<td><strong>{fmt_price(m.cheapest_price)} جنيه</strong></td>"
                 f"<td>{esc(m.storage)} / {esc(m.ram)}</td>"
                 f"<td>{'★ ' + str(m.rating) if m.rating else '—'}</td></tr>")
    table = (f"<table class='data'><thead><tr><th>الهاتف</th><th>أرخص سعر</th>"
             f"<th>التخزين / الرام</th><th>التقييم</th></tr></thead><tbody>{rows}</tbody></table>"
             if rows else "<p>لا توجد هواتف مطابقة حالياً.</p>")
    review_note = ""
    if g.get("human_review"):
        review_note = f"<section class='card'><h2>رأي فريق {SITE_NAME}</h2><p>{esc(g['human_review'])}</p></section>"
    else:
        review_note = """<section class="card"><h2>رأي فريق عروض أونلاين — بانتظار المراجعة البشرية</h2>
<p>[مسودة] لم تُضف المراجعة البشرية بعد لهذا الدليل: لماذا اخترنا هذه الهواتف؟ ما عيوب كل منها؟ ولمن يناسب كل هاتف؟ لن تُنشر هذه الصفحة لمحركات البحث قبل إكمال المراجعة.</p></section>"""
    tips_html = ""
    tips = [t for t in (g.get("tips") or []) if norm(t)]
    if tips:
        tips_html = ("<section class='card'><h2>نصائح قبل الشراء</h2><ul>"
                     + "".join(f"<li>{esc(t)}</li>" for t in tips)
                     + "</ul></section>")
    hero_src, hero_abs = guide_hero_image(g)
    hero = ""
    if hero_src:
        hero = (f'<div class="article-hero"><img src="{esc(hero_src)}" '
                f'alt="{esc(g["title"])}" loading="lazy"></div>')
    else:
        hero = (f'<div class="article-hero article-hero-fallback">'
                f'<h1 style="margin:0">{esc(g["title"])}</h1></div>')
    tags = guide_tags(g)
    ld = {"@context": "https://schema.org", "@type": "Article",
          "headline": g["title"],
          "description": g.get("description", ""),
          "datePublished": g.get("date", TODAY),
          "dateModified": g.get("date", TODAY),
          "author": {"@type": "Organization",
                     "name": g.get("author", "فريق " + SITE_NAME)},
          "publisher": {"@type": "Organization", "name": SITE_NAME,
                        "logo": {"@type": "ImageObject",
                                 "url": BASE_URL + "/assets/logo.png"}}}
    if hero_abs:
        ld["image"] = [hero_abs]
    if tags:
        ld["keywords"] = ", ".join(tags)
    body = f"""{hero}
<div class="draft-banner">{icon("alert")} مسودة — هذه الصفحة قيد المراجعة البشرية ولم تُنشر بعد لمحركات البحث. الأسعار والجداول مولّدة تلقائياً من بيانات الشيت بتاريخ {esc(g.get('date', TODAY))}.</div>
<h1>{esc(g['title'])}</h1>
<p class="muted">بقلم: {esc(g.get('author', 'فريق ' + SITE_NAME))} • التاريخ: {esc(g.get('date', TODAY))} • الحالة: مسودة</p>
{tag_chips(tags)}
<p>{esc(g.get('description', ''))}</p>
{table}
{tips_html}
{review_note}
<p><a href="/guides/">← كل أدلة الشراء</a></p>"""
    return page_shell(g["title"] + " | " + SITE_NAME,
                      g.get("description", ""), BASE_URL + "/guides/" + g["slug"] + "/",
                      body, noindex=True, json_ld=ld,
                      og_image=hero_abs or None)


def build_guides_index(guides):
    # الأدلة المخفية (مسودات جديدة قيد المراجعة) لا تظهر في الفهرس
    guides = [g for g in guides if not g.get("hidden")]
    items = ""
    for g in guides:
        hero_src, _abs = guide_hero_image(g)
        tags = guide_tags(g)
        img = (f'<a href="/guides/{g["slug"]}/"><img src="{esc(hero_src)}" '
               f'alt="{esc(g["title"])}" loading="lazy"></a>'
               if hero_src else
               f'<a href="/guides/{g["slug"]}/"><div class="article-hero-fallback" '
               f'style="height:180px;display:flex;align-items:center;justify-content:center">'
               f'<strong>{esc(g["title"])}</strong></div></a>')
        items += (f"<article class='article-card'>{img}"
                  f"<div class='article-card-body'>"
                  f"<h3><a href='/guides/{g['slug']}/'>{esc(g['title'])}</a> "
                  f"<span class='example-tag'>مسودة</span></h3>"
                  f"<p class='excerpt'>{esc(g.get('description', ''))}</p>"
                  f"<p class='meta'>{esc(g.get('date', TODAY))} • "
                  f"{esc(g.get('author', 'فريق ' + SITE_NAME))}</p>"
                  f"{tag_chips(tags)}"
                  f"<p><a href='/guides/{g['slug']}/'>اقرأ الدليل ←</a></p>"
                  f"</div></article>")
    body = f"""<h1>أدلة الشراء</h1>
<p>أدلة مبنية على أسعار حقيقية محدثة من المتاجر المصرية. الأدلة هنا مسودات قيد المراجعة البشرية قبل النشر.</p>
<div class="article-grid">{items}</div>"""
    return page_shell("أدلة الشراء | " + SITE_NAME,
                      "أدلة شراء الهواتف في مصر مبنية على أسعار حقيقية: أفضل هاتف تحت 10,000 جنيه، وأفضل بطارية، وأفضل كاميرا.",
                      BASE_URL + "/guides/", body, noindex=True)


# -------------------------------------------------------------------- news
def build_news_post(p, model=None):
    img = p.get("image", "")
    if model:
        _local, _remote, _ph = resolve_model_image(model)
        img = _local or _remote
    if not img:
        img = "/images/placeholder.jpg?v=2"
    abs_img = BASE_URL + img if img.startswith("/") else img
    example = (' <span class="example-tag">خبر مثال — يُستبدل بخبر حقيقي</span>'
               if p.get("is_example") else "")
    tags = news_tags(p, model)
    ld = {"@context": "https://schema.org", "@type": "NewsArticle",
          "headline": p["title"],
          "datePublished": p.get("date_published", TODAY),
          "dateModified": p.get("date_modified", TODAY),
          "author": {"@type": "Organization", "name": p.get("author", "فريق " + SITE_NAME)},
          "publisher": {"@type": "Organization", "name": SITE_NAME,
                        "logo": {"@type": "ImageObject", "url": BASE_URL + "/assets/logo.png"}},
          "image": [abs_img],
          "description": p.get("description", "")}
    if tags:
        ld["keywords"] = ", ".join(tags)
    hero = (f'<div class="article-hero"><img src="{esc(img)}" '
            f'alt="{esc(p["title"])}" loading="lazy"></div>')
    body = f"""{hero}
<h1>{esc(p['title'])}{example}</h1>
<p class="news-meta">بقلم: {esc(p.get('author', 'فريق ' + SITE_NAME))} • نُشر في: {esc(p.get('date_published', TODAY)[:10])}</p>
{tag_chips(tags)}
<p>{esc(p.get('body', ''))}</p>
{f'<p><a class="btn" href="/mobiles/{model.slug}/">قارن سعر {esc(model.name_ar)} الآن</a></p>' if model else ''}
<p><a href="/news/">← كل الأخبار</a></p>"""
    return page_shell(p["title"] + " | " + SITE_NAME,
                      p.get("description", ""), BASE_URL + "/news/" + p["slug"] + "/",
                      body, json_ld=ld, og_image=abs_img)


def build_news_index(posts):
    items = ""
    for p in posts:
        model = MODEL_BY_SLUG.get(p.get("model_slug", ""))
        img = p.get("image", "")
        if model:
            _local, _remote, _ph = resolve_model_image(model)
            img = _local or _remote
        if not img:
            img = "/images/placeholder.jpg?v=2"
        tags = news_tags(p, model)
        items += (f"<article class='article-card'>"
                  f"<a href='/news/{p['slug']}/'><img src='{esc(img)}' "
                  f"alt='{esc(p['title'])}' loading='lazy'></a>"
                  f"<div class='article-card-body'>"
                  f"<h3><a href='/news/{p['slug']}/'>{esc(p['title'])}</a>"
                  f"{' <span class=\"example-tag\">مثال</span>' if p.get('is_example') else ''}</h3>"
                  f"<p class='excerpt'>{esc(p.get('description', ''))}</p>"
                  f"<p class='meta'>{esc(p.get('date_published', TODAY)[:10])} • "
                  f"{esc(p.get('author', ''))}</p>"
                  f"{tag_chips(tags)}"
                  f"<p><a href='/news/{p['slug']}/'>اقرأ الخبر ←</a></p>"
                  f"</div></article>")
    body = f"""<h1>أخبار الهواتف والأسعار</h1>
<p>إطلاق الهواتف الجديدة في مصر، وأكبر انخفاضات الأسعار — أخبار أصلية يراجعها فريق {SITE_NAME}.</p>
<div class="article-grid">{items}</div>"""
    return page_shell("أخبار الهواتف والأسعار | " + SITE_NAME,
                      "أخبار إطلاق الهواتف الجديدة في مصر وأكبر انخفاضات الأسعار، من فريق عروض أونلاين.",
                      BASE_URL + "/news/", body)


# --------------------------------------------------------- compare / budget
def build_compare():
    body = """<h1>قارن بين الهواتف</h1>
<p>اختر هاتفين أو ثلاثة من أي صفحة منتج أو بطاقة (زر "قارن")، وستظهر المقارنة هنا جنباً إلى جنب.</p>
<div id="compare-root"><p>جارٍ تحميل المقارنة…</p></div>
<script>
(function () {
  var params = new URLSearchParams(location.search);
  var slugs = (params.get('m') || '').split(',').filter(Boolean).slice(0, 3);
  var root = document.getElementById('compare-root');
  if (!slugs.length) { root.innerHTML = '<p>لم تختر هواتف للمقارنة بعد. تصفح <a href="/#models">كل الهواتف</a> واضغط "قارن" على الهواتف التي تريد مقارنتها.</p>'; return; }
  fetch('/data/products.json').then(function (r) { return r.json(); }).then(function (all) {
    var items = slugs.map(function (s) { return all.find(function (p) { return p.slug === s; }); }).filter(Boolean);
    if (!items.length) { root.innerHTML = '<p>لم نعثر على الهواتف المطلوبة.</p>'; return; }
    var rows = [['السعر', function (p) { return p.price.toLocaleString('en-US') + ' جنيه'; }],
      ['الماركة', function (p) { return p.brand; }],
      ['التخزين / الرام', function (p) { return p.storage + ' / ' + p.ram; }],
      ['الشاشة', function (p) { return p.screen || '—'; }],
      ['المعالج', function (p) { return p.processor || '—'; }],
      ['البطارية', function (p) { return p.battery || '—'; }],
      ['الكاميرا الخلفية', function (p) { return p.rear_camera || '—'; }],
      ['يدعم 5G', function (p) { return p.g5 ? 'نعم' : 'لا'; }],
      ['التقييم', function (p) { return p.rating ? ('★ ' + p.rating + ' (' + p.rating_count + ')') : '—'; }]];
    var h = '<div style="overflow-x:auto"><table class="offers"><thead><tr><th>المواصفة</th>' +
      items.map(function (p) { return '<th><a href="/mobiles/' + p.slug + '/">' + p.name + '</a></th>'; }).join('') + '</tr></thead><tbody>';
    h += '<tr><td><strong>الصورة</strong></td>' + items.map(function (p) {
      return '<td>' + (p.image ? '<a href="/mobiles/' + p.slug + '/"><img src="' + p.image + '" alt="' + p.name.replace(/"/g, '') + '" loading="lazy" style="max-width:130px;height:auto;display:block;margin:0 auto"></a>' : '—') + '</td>';
    }).join('') + '</tr>';
    rows.forEach(function (row) {
      h += '<tr><td><strong>' + row[0] + '</strong></td>' +
        items.map(function (p) { return '<td>' + row[1](p) + '</td>'; }).join('') + '</tr>';
    });
    h += '<tr><td><strong>الشراء</strong></td>' + items.map(function (p) {
      return '<td><div class="compare-buy">' +
        '<a class="btn-buy btn-jumia" href="' + p.jumia_url + '" target="_blank" rel="sponsored noopener" data-store="jumia" data-model="' + p.slug + '" data-event="buy-click">اشترِ من جوميا</a>' +
        '<a class="btn-buy btn-amazon" href="' + p.amazon_url + '" target="_blank" rel="sponsored noopener" data-store="amazon" data-model="' + p.slug + '" data-event="buy-click">اشترِ من أمازون</a>' +
        '<a class="btn-buy btn-noon" href="' + p.noon_url + '" target="_blank" rel="sponsored noopener" data-store="noon" data-model="' + p.slug + '" data-event="buy-click">اشترِ من نون</a>' +
        '</div></td>';
    }).join('') + '</tr>';
    h += '</tbody></table></div><p>' + items.map(function (p) {
      return '<a class="btn" href="/mobiles/' + p.slug + '/" style="margin:4px">عرض ' + p.name + '</a>';
    }).join('') + '</p>';
    root.innerHTML = h;
  });
})();
</script>"""
    return page_shell("قارن بين الهواتف | " + SITE_NAME,
                      "قارن بين هاتفين أو ثلاثة: السعر والمواصفات والبطارية والكاميرا.",
                      BASE_URL + "/compare/", body, noindex=True)


def build_budget():
    bands = [("أقل من 10,000 جنيه", lambda p: p < 10000),
             ("من 10,000 إلى 15,000 جنيه", lambda p: 10000 <= p < 15000),
             ("من 15,000 إلى 20,000 جنيه", lambda p: 15000 <= p < 20000),
             ("أكثر من 20,000 جنيه", lambda p: p >= 20000)]
    sections = ""
    for label, fn in bands:
        pool = [m for m in MODELS if fn(m.cheapest_price)]
        pool = sorted(pool, key=lambda m: m.cheapest_price)[:6]
        if not pool:
            continue
        sections += (f'<div class="section-head"><h2>{label} ({len([m for m in MODELS if fn(m.cheapest_price)])} هاتفاً)</h2></div>'
                     f'<div class="grid">{"".join(card_html(m) for m in pool)}</div>')
    body = f"""<h1>ابحث عن هاتف بميزانيتك</h1>
<p>اكتب حدك الأقصى للسعر، واختر الرام إن أردت، وستظهر الهواتف المطابقة مرتبة من الأرخص.</p>
<p>صفحات جاهزة حسب الميزانية: <a href="/budget/under-10000/">أفضل هاتف تحت 10,000 جنيه</a> • <a href="/budget/under-15000/">أفضل هاتف تحت 15,000 جنيه</a> • <a href="/budget/under-20000/">أفضل هاتف تحت 20,000 جنيه</a> — أو جرّب <a href="/search/specs/">البحث بالمواصفات</a> (بطارية، كاميرا، رام، سعر).</p>
<form id="budget-form" class="toolbar">
<input type="number" id="budget-max" placeholder="حد أقصى للسعر (جنيه)" min="0" required style="flex:1;min-width:180px">
<select id="budget-ram"><option value="">أي رام</option><option>4GB</option><option>6GB</option><option>8GB</option><option>12GB</option></select>
<button class="btn" type="submit">ابحث</button>
</form>
<div id="budget-results"></div>
{sections}
<p class="muted">هذه الأقسام مولّدة من الأسعار الحالية في الشيت (آخر تحديث: {SHEET_UPDATED_DATE}).</p>
<script>
fetch('/data/products.json').then(function (r) {{ return r.json(); }}).then(function (d) {{ window.PRODUCTS = d; }});
</script>"""
    return page_shell("ابحث عن هاتف بميزانيتك | " + SITE_NAME,
                      "ابحث عن هاتف بحد أقصى للسعر والرام المناسبين لك، من بين كل الهواتف المتوفرة في مصر.",
                      BASE_URL + "/budget/", body)


def build_specs_search():
    brands_opts = "".join(
        f'<option value="{esc(b)}">{esc(b)}</option>' for b in BRANDS)
    body = f"""<h1>بحث بالمواصفات</h1>
<p>ابحث عن هاتف بمواصفاتك أنت — لا بالاسم: بطارية كبيرة، كاميرا قوية، رام وتخزين وسعر مناسب.</p>
<section class="deals-filters" aria-label="بحث بالمواصفات">
<div class="deals-filters-grid">
<div class="field"><label for="spec-battery">بطارية لا تقل عن (mAh)</label>
<input type="number" id="spec-battery" placeholder="مثال: 5000" min="0"></div>
<div class="field"><label for="spec-camera">كاميرا خلفية لا تقل عن (MP)</label>
<input type="number" id="spec-camera" placeholder="مثال: 50" min="0"></div>
<div class="field"><label for="spec-ram">رام لا يقل عن</label>
<select id="spec-ram"><option value="">أي رام</option><option value="4">4GB</option><option value="6">6GB</option><option value="8">8GB</option><option value="12">12GB</option></select></div>
<div class="field"><label for="spec-storage">تخزين لا يقل عن</label>
<select id="spec-storage"><option value="">أي تخزين</option><option value="64">64GB</option><option value="128">128GB</option><option value="256">256GB</option><option value="512">512GB</option></select></div>
<div class="field"><label for="spec-maxprice">حد أقصى للسعر (جنيه)</label>
<input type="number" id="spec-maxprice" placeholder="مثال: 12000" min="0"></div>
<div class="field"><label for="spec-brand">الماركة</label>
<select id="spec-brand"><option value="">كل الماركات</option>{brands_opts}</select></div>
</div>
<div class="deals-filters-checks">
<label class="check"><input type="checkbox" id="spec-5g"> يدعم 5G فقط</label>
<button class="btn" type="button" id="spec-reset">مسح الفلاتر</button>
<span id="spec-count" class="results-count">عرض 0 هاتفاً</span>
</div>
</section>
<div id="spec-results" style="margin-top:18px"></div>
<script>
(function () {{
  function toGB(s) {{
    s = (s || '').toUpperCase().replace(/,/g, '');
    var m = s.match(/([\\d.]+)\\s*TB/); if (m) return parseFloat(m[1]) * 1024;
    m = s.match(/([\\d.]+)\\s*GB/); if (m) return parseFloat(m[1]);
    m = s.match(/([\\d.]+)\\s*MB/); if (m) return parseFloat(m[1]) / 1024;
    if (s.indexOf('<1') !== -1) return 0.5;
    return 0;
  }}
  function val(id) {{ var el = document.getElementById(id); return el ? el.value : ''; }}
  function numOr(v, d) {{ var n = parseFloat(v); return isNaN(n) ? d : n; }}
  fetch('/data/products.json').then(function (r) {{ return r.json(); }}).then(function (all) {{
    var out = document.getElementById('spec-results');
    var count = document.getElementById('spec-count');
    function card(p) {{
      return '<article class="pcard"><a href="/mobiles/' + p.slug + '/"><img src="' + (p.image || '/images/placeholder.jpg?v=2') + '" alt="هاتف ' + p.name + '" loading="lazy" width="500" height="500"></a><div class="pcard-body"><h3><a href="/mobiles/' + p.slug + '/">' + p.name + '</a></h3>' +
        '<div class="brand-line">' + p.brand + ' • ' + p.storage + ' / ' + p.ram + (p.g5 ? ' • يدعم 5G' : '') + (p.year ? ' • ' + p.year : '') + '</div>' +
        '<div class="brand-line">' + (p.battery || '') + (p.rear_camera ? ' • كاميرا ' + p.rear_camera : '') + '</div>' +
        '<div class="price-row"><span class="price">' + p.price.toLocaleString('en-US') + ' جنيه</span></div>' +
        '<div class="actions"><a class="btn-mini btn-prices" href="/mobiles/' + p.slug + '/">عرض السعر</a><button class="btn-mini btn-compare" type="button" data-compare="' + p.slug + '">قارن</button><button class="btn-mini btn-fav" type="button" data-fav="' + p.slug + '">♡ مفضلة</button></div></div></article>';
    }}
    function render() {{
      var minBat = numOr(val('spec-battery'), 0);
      var minCam = numOr(val('spec-camera'), 0);
      var minRam = numOr(val('spec-ram'), 0);
      var minSto = numOr(val('spec-storage'), 0);
      var maxPrice = numOr(val('spec-maxprice'), Infinity);
      var brand = val('spec-brand');
      var g5only = document.getElementById('spec-5g').checked;
      var list = all.filter(function (p) {{
        if ((p.battery_mah || 0) < minBat) return false;
        if ((p.rear_camera_mp || 0) < minCam) return false;
        if (toGB(p.ram) < minRam) return false;
        if (toGB(p.storage) < minSto) return false;
        if (p.price > maxPrice) return false;
        if (brand && p.brand !== brand) return false;
        if (g5only && !p.g5) return false;
        return true;
      }});
      list.sort(function (a, b) {{ return (b.year || 0) - (a.year || 0) || a.price - b.price; }});
      count.textContent = 'عرض ' + list.length + ' هاتفاً';
      out.innerHTML = list.length
        ? '<div class="grid">' + list.map(card).join('') + '</div>'
        : '<p>لا توجد هواتف مطابقة — خفف بعض الشروط وجرّب مجدداً.</p>';
    }}
    ['spec-battery', 'spec-camera', 'spec-ram', 'spec-storage', 'spec-maxprice', 'spec-brand', 'spec-5g'].forEach(function (id) {{
      var el = document.getElementById(id);
      if (el) el.addEventListener(el.tagName === 'SELECT' || el.type === 'checkbox' ? 'change' : 'input', render);
    }});
    document.getElementById('spec-reset').addEventListener('click', function () {{
      ['spec-battery', 'spec-camera', 'spec-maxprice'].forEach(function (id) {{ document.getElementById(id).value = ''; }});
      ['spec-ram', 'spec-storage', 'spec-brand'].forEach(function (id) {{ document.getElementById(id).value = ''; }});
      document.getElementById('spec-5g').checked = false;
      render();
    }});
    render();
  }});
}})();
</script>"""
    return page_shell("بحث بالمواصفات | " + SITE_NAME,
                      "ابحث عن هاتف بمواصفاتك: بطارية لا تقل عن 5000mAh، كاميرا 50MP فأكثر، رام وتخزين وسعر مناسب — من بين كل الهواتف في مصر.",
                      BASE_URL + "/search/specs/", body)


def build_budget_band(limit):
    """One SEO landing page per budget band: phones at or under the limit,
    newest-first (release year desc, then cheapest)."""
    pool = [m for m in MODELS if m.cheapest_price <= limit]
    pool = sorted(pool, key=lambda m: (-(m.year or 0), m.cheapest_price))
    cards = "".join(card_html(m) for m in pool)
    cheapest = min((m.cheapest_price for m in pool), default=0)
    title = f"أفضل هاتف تحت {fmt_price(limit)} جنيه في مصر {TODAY[:4]}"
    desc = (f"أفضل {len(pool)} هاتفاً بسعر أقل من {fmt_price(limit)} جنيه في مصر "
            f"({TODAY[:4]}): قارن الأسعار في جوميا وأمازون ونون، مرتّبة من الأحدث "
            f"إصداراً، وتبدأ من {fmt_price(cheapest)} جنيه.")
    intro = (f"<p>تبحث عن هاتف بسعر أقل من <strong>{fmt_price(limit)} جنيه</strong>؟ "
             f"هذه قائمة محدّثة بأفضل {len(pool)} هاتفاً في مصر ضمن ميزانيتك، "
             f"مرتّبة من الأحدث إصداراً، مع أرخص سعر لكل هاتف في جوميا وأمازون ونون. "
             f"الأسعار محدّثة من الشيت (آخر تحديث: {SHEET_UPDATED_DATE}).</p>"
             f"<p><a href=\"/budget/\">← البحث بميزانية مخصصة</a> • "
             f"<a href=\"/budget/under-10000/\">تحت 10,000</a> • "
             f"<a href=\"/budget/under-15000/\">تحت 15,000</a> • "
             f"<a href=\"/budget/under-20000/\">تحت 20,000</a></p>")
    top = pool[:10]
    ld = {"@context": "https://schema.org", "@type": "ItemList",
          "name": title,
          "itemListElement": [{"@type": "ListItem", "position": i + 1,
                               "url": f"{BASE_URL}/mobiles/{m.slug}/",
                               "name": m.name_ar}
                              for i, m in enumerate(top)]}
    body = (f"<section class=\"page-hero\" style=\"margin:0 -18px 20px;padding:22px 18px\">"
            f"<h1 style=\"margin:0\">{esc(title)}</h1>"
            f"<p>{len(pool)} هاتفاً — تبدأ من {fmt_price(cheapest)} جنيه.</p></section>"
            f"{intro}<div class=\"grid\">{cards}</div>")
    return page_shell(title + " | " + SITE_NAME, desc,
                      f"{BASE_URL}/budget/under-{limit}/", body, json_ld=ld,
                      og_image=abs_image(top[0]) if top else None)


def build_search():
    body = """<h1>ابحث في عروض أونلاين</h1>
<p>أو جرّب <a href="/search/specs/">البحث بالمواصفات</a> — بطارية، كاميرا، رام، تخزين وسعر.</p>
<form class="search-box" onsubmit="return false">
<input type="search" id="search-q" placeholder="ابحث عن هاتف أو ماركة…" aria-label="بحث">
</form>
<div id="search-results" style="margin-top:18px"></div>
<script>
(function () {
  var q = new URLSearchParams(location.search).get('q') || '';
  var input = document.getElementById('search-q');
  var out = document.getElementById('search-results');
  input.value = q;
  fetch('/data/products.json').then(function (r) { return r.json(); }).then(function (all) {
    function render() {
      var term = input.value.trim().toLowerCase();
      if (!term) { out.innerHTML = '<p>اكتب اسم هاتف أو ماركة للبحث.</p>'; return; }
      var list = all.filter(function (p) {
        return (p.name + ' ' + p.name_en + ' ' + p.brand + ' ' + p.model).toLowerCase().indexOf(term) !== -1;
      }).slice(0, 20);
      out.innerHTML = list.length
        ? '<div class="grid">' + list.map(function (p) {
            return '<article class="pcard"><a href="/mobiles/' + p.slug + '/"><img src="' + (p.image || '/images/placeholder.jpg?v=2') + '" alt="هاتف ' + p.name + '" loading="lazy" width="500" height="500"></a><div class="pcard-body"><h3><a href="/mobiles/' + p.slug + '/">' + p.name + '</a></h3>' +
              '<div class="price-row"><span class="price">' + p.price.toLocaleString('en-US') + ' جنيه</span></div>' +
              '<div class="brand-line">' + p.brand + ' • ' + p.storage + ' / ' + p.ram + '</div>' +
              '<div class="actions"><a class="btn-mini btn-prices" href="/mobiles/' + p.slug + '/">عرض السعر</a><button class="btn-mini btn-compare" type="button" data-compare="' + p.slug + '">قارن</button></div></div></article>';
          }).join('') + '</div>'
        : '<p>لا توجد نتائج مطابقة لـ "' + input.value + '". جرّب اسماً آخر، أو <a href="/contact/">اطلب الهاتف</a> وسنضيفه.</p>';
    }
    input.addEventListener('input', render);
    render();
  });
})();
</script>"""
    return page_shell("بحث | " + SITE_NAME, "ابحث عن أي هاتف في عروض أونلاين.",
                      BASE_URL + "/search/", body, noindex=True)


# ------------------------------------------------------------- data output
def parse_battery_mah(text):
    """Battery capacity in mAh from a raw spec string ('5000 mAh',
    '5000 مللي أمبير'). 0 if unknown."""
    v = num(re.sub(r"[^\d.]", "", norm(text)), 0) or 0
    return int(v)


def parse_rear_camera_mp(text):
    """Rear camera resolution in MP from a raw spec string ('50MP',
    '50 ميغابكسل'). 0 if unknown."""
    m = re.search(r"(\d+(?:\.\d+)?)\s*MP", norm(text))
    if m:
        return float(m.group(1))
    m = re.search(r"(\d+(?:\.\d+)?)\s*ميغابكسل", norm(text))
    if m:
        return float(m.group(1))
    return 0


def size_to_gb(text):
    """Parse a size string ('4GB', '512MB', '1TB', '<1GB') into GB (float).
    Returns None if unparseable. '<1GB' counts as below 1GB."""
    if not text:
        return None
    s = str(text).strip().upper()
    if s.startswith("<"):
        return 0.5
    m = re.match(r"^([\d.]+)\s*(TB|GB|MB|KB)?$", s)
    if not m:
        return None
    val = float(m.group(1))
    unit = m.group(2) or "GB"
    if unit == "TB":
        return val * 1024
    if unit == "GB":
        return val
    if unit == "MB":
        return val / 1024
    if unit == "KB":
        return val / (1024 * 1024)
    return None


def filter_size_opts(values, min_gb):
    """Filter size strings to >= min_gb and sort ascending by numeric size.
    Returns the original display strings in ascending order."""
    parsed = []
    for v in values:
        gb = size_to_gb(v)
        if gb is not None and gb >= min_gb:
            parsed.append((gb, v))
    parsed.sort(key=lambda x: (x[0], x[1]))
    return [v for _, v in parsed]


def products_json():
    out = []
    for m in MODELS:
        r0 = m.offers[0]
        _img_local, _img_remote, _img_ph = resolve_model_image(m)
        out.append({
            "slug": m.slug, "name": m.name_ar, "name_en": m.name_en,
            "brand": m.brand, "model": m.model, "storage": m.storage,
            "ram": m.ram, "year": m.year, "price": m.cheapest_price,
            "old_price": m.old_price, "discount": m.discount,
            "rating": m.rating, "rating_count": m.rating_count,
            "g5": m.g5, "in_stock": m.in_stock,
            "screen": norm(c(r0, "حجم الشاشة")),
            "processor": norm(c(r0, "المعالج")),
            "battery": norm(c(r0, "البطارية")),
            "battery_mah": parse_battery_mah(c(r0, "البطارية")),
            "rear_camera": norm(c(r0, "الكاميرا الخلفية")),
            "rear_camera_mp": parse_rear_camera_mp(c(r0, "الكاميرا الخلفية")),
            "front_camera": norm(c(r0, "الكاميرا الأمامية")),
            "image": _img_local or _img_remote,
            "jumia_url": jumia_url(norm(c(r0, "رابط المنتج")), norm(c(r0, "رابط الأفلييت"))),
            "amazon_url": amazon_url(m.display, m.slug),
            "noon_url": noon_url(m.display),
            "url": f"/mobiles/{m.slug}/",
        })
    return out


# -------------------------------------------------------------- sitemaps
def write_sitemap(pages_meta, news_posts):
    urls = []
    for loc, meta in sorted(pages_meta.items()):
        entry = f"  <url><loc>{esc(loc)}</loc><lastmod>{meta['lastmod']}</lastmod>"
        if "/mobiles/" in loc:
            slug = loc.rstrip("/").rsplit("/", 1)[-1]
            img_file = SITE / "images" / "products" / f"{slug}.jpg"
            img = (f"{BASE_URL}/images/products/{slug}.jpg" if img_file.exists()
                   else f"{BASE_URL}/images/placeholder.jpg?v=2")
            m = next((x for x in MODELS if x.slug == slug), None)
            entry += (f"<image:image><image:loc>{esc(img)}</image:loc>"
                      + (f"<image:title>{esc(m.name_ar)}</image:title>" if m else "")
                      + "</image:image>")
        entry += "</url>"
        urls.append(entry)
    (SITE / "sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" xmlns:image="http://www.google.com/schemas/sitemap-image/1.1">\n'
        + "\n".join(urls) + "\n</urlset>\n", encoding="utf-8")
    news_urls = []
    for p in news_posts:
        d = p.get("date_published", TODAY)[:10]
        news_urls.append(
            f"  <url><loc>{BASE_URL}/news/{p['slug']}/</loc>"
            f"<news:news><news:publication><news:name>{esc(SITE_NAME)}</news:name>"
            f"<news:language>ar</news:language></news:publication>"
            f"<news:publication_date>{d}</news:publication_date>"
            f"<news:title>{esc(p['title'])}</news:title></news:news></url>")
    (SITE / "news-sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" '
        'xmlns:news="http://www.google.com/schemas/sitemap-news/0.9">\n'
        + "\n".join(news_urls) + "\n</urlset>\n", encoding="utf-8")
    (SITE / "robots.txt").write_text(
        "User-agent: *\nAllow: /\nDisallow: /adamwnor/\nDisallow: /search/\n"
        "Disallow: /compare/\nDisallow: /guides/\n"
        f"Sitemap: {BASE_URL}/sitemap.xml\n", encoding="utf-8")


def write_manifest():
    (SITE / "manifest.json").write_text(json.dumps({
        "name": SITE_NAME, "short_name": "عروضي",
        "description": "قارن أسعار الهواتف في جوميا مصر وأمازون مصر ونون مصر.",
        "start_url": "/", "scope": "/", "display": "standalone",
        "dir": "rtl", "lang": "ar",
        "background_color": "#0a2540", "theme_color": "#0b5ed7",
        "icons": [{"src": "/assets/icon-192.png", "sizes": "192x192", "type": "image/png"},
                  {"src": "/assets/icon-512.png", "sizes": "512x512", "type": "image/png"}],
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    (SITE / "sw.js").write_text(
        "const CACHE='r3de-v8';const CORE=['/','/assets/style.css','/assets/app.js',"
        "'/assets/logo.png','/assets/icon-192.png','/assets/icon-512.png'];\n"
        "self.addEventListener('install',e=>{e.waitUntil(caches.open(CACHE).then(c=>c.addAll(CORE)).then(()=>self.skipWaiting()));});\n"
        "self.addEventListener('activate',e=>{e.waitUntil(caches.keys().then(ks=>Promise.all(ks.filter(k=>k!==CACHE).map(k=>caches.delete(k)))).then(()=>self.clients.claim()));});\n"
        "self.addEventListener('fetch',e=>{const u=new URL(e.request.url);if(e.request.method!=='GET')return;"
        "if(u.pathname.startsWith('/assets/')||u.pathname.startsWith('/images/')){e.respondWith(caches.match(e.request).then(r=>r||fetch(e.request).then(res=>{const cp=res.clone();caches.open(CACHE).then(c=>c.put(e.request,cp));return res;}).catch(()=>caches.match('/'))));return;}"
        "e.respondWith(fetch(e.request).catch(()=>caches.match('/')));});\n",
        encoding="utf-8")


# -------------------------------------------------------------------- main
def main():
    global SITE
    out = Path(sys.argv[sys.argv.index("--out") + 1]) if "--out" in sys.argv else SITE
    SITE = out
    # rebuild cleanly, but PRESERVE downloaded product images
    # (sync.py downloads + watermarks them into site/images/)
    images_backup = None
    if (SITE / "images").exists():
        import tempfile
        images_backup = Path(tempfile.mkdtemp(prefix="r3de-images-")) / "images"
        shutil.copytree(SITE / "images", images_backup)
    if SITE.exists():
        shutil.rmtree(SITE)
    (SITE / "mobiles").mkdir(parents=True)
    (SITE / "brand").mkdir(parents=True)
    (SITE / "coupons").mkdir(parents=True)
    (SITE / "guides").mkdir(parents=True)
    (SITE / "news").mkdir(parents=True)
    (SITE / "compare").mkdir(parents=True)
    (SITE / "budget").mkdir(parents=True)
    (SITE / "search").mkdir(parents=True)
    (SITE / "data").mkdir(parents=True)
    (SITE / "assets").mkdir(parents=True)
    (SITE / "images" / "products").mkdir(parents=True)
    (SITE / "images" / "originals").mkdir(parents=True)

    # assets (copy, don't regenerate)
    for f in ["style.css", "app.js", "logo.png", "icon-192.png", "icon-512.png", "favicon.png"]:
        shutil.copy2(BASE / "assets" / f, SITE / "assets" / f)
    # self-hosted Tajawal fonts (woff2)
    shutil.copytree(BASE / "assets" / "fonts", SITE / "assets" / "fonts", dirs_exist_ok=True)
    # self-hosted brand + store logos (SVG/PNG)
    shutil.copytree(BASE / "assets" / "brand-logos", SITE / "assets" / "brand-logos", dirs_exist_ok=True)
    shutil.copytree(BASE / "assets" / "store-logos", SITE / "assets" / "store-logos", dirs_exist_ok=True)
    # restore preserved product images from the previous build
    if images_backup is not None:
        shutil.copytree(images_backup, SITE / "images", dirs_exist_ok=True)
        shutil.rmtree(images_backup.parent, ignore_errors=True)
    pages = {}  # loc -> html (for sitemap lastmod hashing)

    def emit(rel_path, html_text):
        p = SITE / rel_path
        p.parent.mkdir(parents=True, exist_ok=True)
        check_no_forbidden(html_text, str(rel_path))
        p.write_text(html_text, encoding="utf-8")
        loc = BASE_URL + "/" + str(rel_path).replace("index.html", "").replace("\\", "/")
        if not loc.endswith("/"):
            loc += "/"
        pages[loc] = html_text

    emit("index.html", build_index())
    for m in MODELS:
        emit(f"mobiles/{m.slug}/index.html", build_product(m))
    for b in BRANDS:
        emit(f"brand/{BRAND_SLUGS[b]}/index.html", build_brand(b))
    emit("brands/index.html", build_brands_index())
    emit("deals/index.html", build_deals_page())
    emit("coupons/index.html", build_coupons())
    guides = load_json(DATA / "guides.json")["guides"]
    emit("guides/index.html", build_guides_index(guides))
    for g in guides:
        emit(f"guides/{g['slug']}/index.html", build_guide(g))
    news = load_json(DATA / "news.json")["posts"]
    emit("news/index.html", build_news_index(news))
    for p in news:
        model = MODEL_BY_SLUG.get(p.get("model_slug", ""))
        emit(f"news/{p['slug']}/index.html", build_news_post(p, model))
    emit("compare/index.html", build_compare())
    emit("budget/index.html", build_budget())
    for _limit in (10000, 15000, 20000):
        emit(f"budget/under-{_limit}/index.html", build_budget_band(_limit))
    emit("search/index.html", build_search())
    emit("search/specs/index.html", build_specs_search())

    # policy pages (already built — copy as-is)
    policy_map = {"privacy": "privacy", "terms": "terms",
                  "affiliate-disclosure": "affiliate-disclosure",
                  "cookies": "cookies", "about": "about", "contact": "contact"}
    for src, slug in policy_map.items():
        src_path = BASE / "pages" / f"{src}.html"
        text = src_path.read_text(encoding="utf-8")
        check_no_forbidden(text, f"pages/{src}.html")
        dest = SITE / slug / "index.html"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(text, encoding="utf-8")
        pages[f"{BASE_URL}/{slug}/"] = text

    # data + pwa
    (SITE / "data" / "products.json").write_text(
        json.dumps(products_json(), ensure_ascii=False), encoding="utf-8")
    write_manifest()

    # sitemap lastmod: only on real content change (audit ت-13)
    meta_file = DATA / "page-meta.json"
    old_meta = load_json(meta_file) if meta_file.exists() else {}
    new_meta = {}
    for loc, text in pages.items():
        h = hashlib.sha256(text.encode("utf-8")).hexdigest()
        if loc in old_meta and old_meta[loc].get("hash") == h:
            lastmod = old_meta[loc]["lastmod"]
        else:
            lastmod = TODAY
        new_meta[loc] = {"hash": h, "lastmod": lastmod}
    meta_file.write_text(json.dumps(new_meta, ensure_ascii=False, indent=1),
                         encoding="utf-8")
    # drafts + tools are NOT in the sitemap (but /search/specs/ IS a content
    # page, so only the bare /search/ tool page is excluded)
    sitemap_meta = {loc: m for loc, m in new_meta.items()
                    if not any(x in loc for x in ("/guides/", "/compare/"))
                    and not loc.rstrip("/").endswith("/search")}
    write_sitemap(sitemap_meta, news)

    print(f"models: {len(MODELS)}  offers: {len(ROWS)}  brands: {len(BRANDS)}")
    print(f"product pages: {len(MODELS)}  brand pages: {len(BRANDS)}  "
          f"guides: {len(guides)} (drafts, noindex)  news posts: {len(news)}  "
          f"policy pages: {len(policy_map)}")
    print(f"pages emitted: {len(pages)}  sitemap urls: {len(sitemap_meta)}")
    print(f"site written to: {SITE}")
    if DEAD_IMAGES:
        print(f"WARNING: {len(DEAD_IMAGES)} model(s) have DEAD sheet image URLs "
              f"(404 even at original size) — placeholder used, admin must fix "
              f"the sheet URL: {', '.join(sorted(set(DEAD_IMAGES)))}")
    print(f"amazon tag in use: {AMAZON_TAG or '(none — plain search links)'}")
    print("jumia: JForce deep links from Sheet column AU (رابط الأفلييت); "
          "fallback build_jumia_product_url when empty "
          f"(short link: {AFF.get('jumia_jforce_link', '(not set)')})")
    print(f"jumia sub_id: {JUMIA_SUB_ID or '(none)'}  noon tag: {NOON_TAG or '(none)'}")


if __name__ == "__main__":
    main()
