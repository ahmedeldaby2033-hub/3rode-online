#!/usr/bin/env python3
"""Sync helpers for 3rde.online — approved audit fixes, applied 2026-11-19.

Fixes implemented here (see docs/audit.md):
  ت-3  Price history is recorded ONLY when the price actually changes
       (hourly sync must not create 24 rows/day per product).
  ت-5  Product images are upgraded automatically: shortpixel w_270 -> w_800
       during sync (sheet images are only 270px; Discover needs 1200px,
       product pages need >= 800px).
  ت-6  Every affiliate link carries rel="sponsored" (Google link policy).
  ت-8  No "fake discount" wording anywhere: only neutral numbers,
       e.g. "price is X% above the 30-day average".

Usage: import these functions in the sync script (scripts/sync.py).
Run this file directly for a self-test.
"""
import re

# ---------------------------------------------------------------- images
SHORTPIXEL_W = re.compile(r"(spai/)w_\d+(\+)")


def upgrade_image_url(url: str) -> str:
    """Return the largest usable variant of a product image URL.

    - Mobizil shortpixel CDN: w_270 -> w_800 (same file, bigger size).
    - Anything else: returned unchanged.
    """
    if not url:
        return url
    upgraded, n = SHORTPIXEL_W.subn(r"\1w_800\2", url, count=1)
    return upgraded if n else url


def image_is_large_enough(url: str) -> bool:
    """True if the URL requests a width of at least 800px."""
    m = re.search(r"w_(\d+)", url or "")
    return bool(m and int(m.group(1)) >= 800)


# ---------------------------------------------------------- price history
def should_log_price(old_price, new_price) -> bool:
    """ت-3: log a price-history row ONLY when the price really changed."""
    if old_price is None or new_price is None:
        return False
    try:
        return float(old_price) != float(new_price)
    except (TypeError, ValueError):
        return old_price != new_price


def price_change(old_price, new_price):
    """Return (diff_egp, diff_pct) or (0, 0.0) when unchanged."""
    if not should_log_price(old_price, new_price):
        return 0, 0.0
    diff = float(new_price) - float(old_price)
    pct = (diff / float(old_price) * 100) if float(old_price) else 0.0
    return diff, round(pct, 1)


# ------------------------------------------------------- neutral wording
def discount_verdict(current_price, avg_30d):
    """ت-8: neutral, number-only wording. Never 'fake discount'.

    Returns an Arabic sentence, or '' when there is no basis to judge.
    """
    if not current_price or not avg_30d:
        return ""
    try:
        cur, avg = float(current_price), float(avg_30d)
    except (TypeError, ValueError):
        return ""
    if avg <= 0:
        return ""
    pct = round((cur - avg) / avg * 100, 1)
    if pct <= -5:
        return f"السعر الحالي أقل من متوسط آخر 30 يوماً بنسبة {abs(pct)}%."
    if pct >= 5:
        return f"السعر الحالي أعلى من متوسط آخر 30 يوماً بنسبة {pct}%."
    return "السعر الحالي قريب من متوسط آخر 30 يوماً."


def lowest_price_badge(days_of_history: int) -> str:
    """ت-4: the 'lowest price in 3 months' badge needs 90 days of history."""
    if days_of_history >= 90:
        return "أدنى سعر في آخر 3 أشهر"
    return ""  # before 90 days: show "أدنى سعر منذ بدء التتبع" instead.


# ------------------------------------------------------------- affiliate
AFFILIATE_REL = 'rel="sponsored noopener"'
AFFILIATE_ATTRS = 'rel="sponsored noopener" target="_blank"'


def affiliate_link_attrs() -> str:
    """ت-6: attributes every buy/coupon link must carry. No exceptions."""
    return AFFILIATE_ATTRS


# ------------------------------------------------- Jumia Egypt affiliate
# Official portal: https://affiliate.jumia.com/ (free, manual approval).
# Commission up to 13% by category; 7-day cookie.
# Jumia links are per-product TRACKING links built in the Jumia dashboard
# Link Builder (paste a product URL -> get a tracking link). There is no
# single tag appended to every URL, so the system stores the full tracking
# link as the offer's product URL. SUB ID is an optional campaign marker.
#
# USER'S ACTUAL PROGRAM (verified 2026-11-19): Jumia JForce (agent
# program). Personal short link https://jforce.jumia.com.eg/s/C4i51XK
# redirects via Adjust to the jumia.com.eg homepage with:
#   utm_source=JFORCE, utm_medium=JF_Affiliate,
#   utm_campaign=JF_Affiliate_EG,
#   adj_label=casid*cf5c450e-259d-49d2-889e-95c558384bcd^type*jforce
# The same parameters can be appended to product URLs for deep links;
# attribution should be verified once in the JForce dashboard.
JUMIA_JFORCE_LINK = "https://jforce.jumia.com.eg/s/C4i51XK"
JUMIA_TRACKING_PARAMS = {
    "utm_source": "JFORCE",
    "utm_medium": "JF_Affiliate",
    "utm_campaign": "JF_Affiliate_EG",
    "adj_label": "casid*cf5c450e-259d-49d2-889e-95c558384bcd^type*jforce",
}


def jumia_tracking_url(product_url: str, sub_id: str = "") -> str:
    """Return a Jumia Egypt product URL unchanged (tracking links are
    generated per product in the Jumia dashboard). The sub_id is kept
    for campaign reporting; it is NOT appended blindly because Jumia
    tracking links already carry their own parameters."""
    return (product_url or "").strip()


def build_jumia_product_url(product_url: str) -> str:
    """Append the user's JForce tracking parameters to a plain Jumia
    Egypt product URL, producing a trackable deep link. If the URL
    already carries tracking parameters, it is returned unchanged.
    Jumia Egypt product URLs are normalised to the Arabic version
    (/ar/ — the site is Arabic): a URL without a locale prefix gets
    /ar/ inserted after the host."""
    from urllib.parse import urlparse, parse_qsl, urlencode, urlunparse
    url = (product_url or "").strip()
    if not url:
        return url
    parsed = urlparse(url)
    query = dict(parse_qsl(parsed.query))
    if "utm_source" in query or "adj_label" in query:
        return url
    path = parsed.path
    if parsed.netloc.endswith("jumia.com.eg") and not (
            path.startswith("/ar/") or path.startswith("/en/")):
        path = "/ar" + (path if path.startswith("/") else "/" + path)
    query.update(JUMIA_TRACKING_PARAMS)
    return urlunparse(parsed._replace(path=path, query=urlencode(query)))


def build_jumia_search_url(query: str) -> str:
    """Admin helper (added 2026-11-19 at the user's request): a Jumia
    Egypt search link for a product name, with the user's JForce
    tracking parameters. Used by the 'بحث تلقائي في جوميا' button in
    the admin product form so the admin can find the real product
    link and paste it back. Arabic catalog (/ar/catalog/?q=)."""
    from urllib.parse import quote_plus, urlencode
    params = {"q": query.strip()}
    params.update(JUMIA_TRACKING_PARAMS)
    return "https://www.jumia.com.eg/ar/catalog/?" + urlencode(params)


# ----------------------------------------------- Amazon Egypt Associates
# Official portal: https://affiliate-program.amazon.eg/
# Tag MUST end with -21 (Egypt/Europe). A -20 (US) tag earns NOTHING
# on amazon.eg. Link format: https://www.amazon.eg/dp/ASIN/?tag=TAG-21
# OneLink does NOT support amazon.eg.
AMAZON_EG_HOST = "https://www.amazon.eg"


def amazon_tag_is_valid(tag: str) -> bool:
    """An Amazon Egypt Associates tag must end with -21."""
    return bool(tag) and tag.strip().endswith("-21")


def build_amazon_product_url(asin: str, tag: str) -> str:
    """Build a tagged Amazon Egypt product link from an ASIN."""
    if not asin:
        raise ValueError("ASIN is required for an Amazon product link")
    if not amazon_tag_is_valid(tag):
        raise ValueError(
            f"Amazon Egypt tag {tag!r} is invalid: it must end with -21 "
            "(a -20 US tag earns nothing on amazon.eg)")
    return f"{AMAZON_EG_HOST}/dp/{asin.strip()}/?tag={tag.strip()}"


def build_amazon_search_url(query: str, tag: str) -> str:
    """Build a tagged Amazon Egypt search link (used until real product
    links exist in the sheet)."""
    from urllib.parse import quote_plus
    if not amazon_tag_is_valid(tag):
        raise ValueError(
            f"Amazon Egypt tag {tag!r} is invalid: it must end with -21")
    return (f"{AMAZON_EG_HOST}/s?k={quote_plus(query.strip())}"
            f"&tag={tag.strip()}")


# ---------------------------------------------------------------- self-test
if __name__ == "__main__":
    # ت-5: image upgrade
    u = ("https://cdn.shortpixel.ai/spai/w_270+q_glossy+ret_img+to_webp/"
         "mobizil.com/wp-content/uploads/2026/02/Oppo-A6-4G.jpg")
    up = upgrade_image_url(u)
    assert "w_800" in up and "w_270" not in up, up
    assert image_is_large_enough(up) and not image_is_large_enough(u)
    assert upgrade_image_url("https://example.com/pic.jpg") == \
        "https://example.com/pic.jpg"
    print("image upgrade OK:", up)

    # ت-3: history only on change
    assert should_log_price(12459, 11999) is True
    assert should_log_price(12459, 12459) is False
    assert should_log_price(None, 11999) is False
    assert price_change(12459, 11999) == (-460, -3.7)
    assert price_change(12459, 12459) == (0, 0.0)
    print("price-history rule OK: log only on change")

    # ت-8: neutral wording
    assert "وهمي" not in discount_verdict(15000, 12000)
    assert discount_verdict(15000, 12000) == \
        "السعر الحالي أعلى من متوسط آخر 30 يوماً بنسبة 25.0%."
    assert discount_verdict(11000, 12000) == \
        "السعر الحالي أقل من متوسط آخر 30 يوماً بنسبة 8.3%."
    print("neutral wording OK:", discount_verdict(15000, 12000))

    # ت-4: badge gating
    assert lowest_price_badge(90) == "أدنى سعر في آخر 3 أشهر"
    assert lowest_price_badge(12) == ""
    print("badge gating OK")

    # ت-6: affiliate attrs
    assert "sponsored" in affiliate_link_attrs()
    print("affiliate attrs OK:", affiliate_link_attrs())

    # Affiliate systems (docs/affiliate-setup.md): Jumia + Amazon Egypt
    assert jumia_tracking_url("https://www.jumia.com.eg/oppo-a6-123.html") == \
        "https://www.jumia.com.eg/oppo-a6-123.html"
    deep = build_jumia_product_url(
        "https://www.jumia.com.eg/oppo-a6-123.html")
    assert "utm_source=JFORCE" in deep and "adj_label=" in deep, deep
    assert build_jumia_product_url(deep) == deep  # already tracked: unchanged
    print("Jumia JForce deep link OK:", deep)
    js = build_jumia_search_url("OPPO A6")
    assert js.startswith("https://www.jumia.com.eg/ar/catalog/?q=OPPO+A6"), js
    assert "utm_source=JFORCE" in js
    print("Jumia auto-search link OK:", js)
    ams = build_amazon_search_url("OPPO A6", "amazon0c2aca6-21")
    assert ams == "https://www.amazon.eg/s?k=OPPO+A6&tag=amazon0c2aca6-21", ams
    print("Amazon auto-search link OK:", ams)
    assert build_amazon_product_url("B0CX123456", "3rde-21") == \
        "https://www.amazon.eg/dp/B0CX123456/?tag=3rde-21"
    assert build_amazon_search_url("OPPO A6", "3rde-21") == \
        "https://www.amazon.eg/s?k=OPPO+A6&tag=3rde-21"
    assert amazon_tag_is_valid("3rde-21") is True
    assert amazon_tag_is_valid("3rde-20") is False  # US tag: earns nothing on .eg
    try:
        build_amazon_product_url("B0CX123456", "3rde-20")
        raise AssertionError("a -20 tag must be rejected")
    except ValueError as e:
        print("Amazon -20 tag rejected OK:", e)
    print("ALL SYNC-HELPER TESTS PASSED")
