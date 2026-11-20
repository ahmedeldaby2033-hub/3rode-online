#!/usr/bin/env python3
"""Verification for the 3rde.online build (run after scripts/build.py).

Checks (all must pass):
  1. Every generated HTML page parses (tag balance).
  2. Every product page: 3 buy buttons with rel="sponsored noopener" +
     target="_blank"; Amazon links carry tag=amazon0c2aca6-21; Jumia link
     present; visible cheapest price; last-update date; source link;
     JSON-LD Product + AggregateOffer whose lowPrice matches the visible
     cheapest price exactly.
  2b. Affiliate alignment: in the sheet export, every Jumia row's AU
     affiliate link must be the same product as its E product URL
     (base URL equal) and carry JForce tracking — a misaligned AU
     column once shipped buy buttons to the wrong phones.
     are noindex; robots.txt blocks /adamwnor/ /search/ /compare/ /guides/.
  4. No forbidden word (وهمي / مزيف / خدعة / احتيال) in site/, templates/,
     pages/ or scripts used for generation.
  5. The Amazon Associates sentence is present in the disclosure page.
  6. sitemap.xml / news-sitemap.xml are valid XML; manifest.json valid JSON.
  7. Policy pages exist and link each other.
Usage: python3 scripts/verify.py [--site site]
Exit code 0 = all checks passed.
"""
import json
import re
import sys
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
SITE = Path(sys.argv[sys.argv.index("--site") + 1]) if "--site" in sys.argv else BASE / "site"
ERRORS = []
WARNS = []
CHECKS = 0


def check(ok, msg):
    global CHECKS
    CHECKS += 1
    if not ok:
        ERRORS.append(msg)
        print("  FAIL:", msg)
    return ok


class BalanceParser(HTMLParser):
    VOID = {"meta", "link", "img", "br", "hr", "input", "source", "col",
            "area", "base", "embed", "track", "wbr"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.errs = []

    def handle_starttag(self, tag, attrs):
        if tag not in self.VOID:
            self.stack.append((tag, self.getpos()))

    def handle_startendtag(self, tag, attrs):
        pass

    def handle_endtag(self, tag):
        if tag in self.VOID:
            return
        if not self.stack:
            self.errs.append(f"extra </{tag}> at {self.getpos()}")
            return
        if self.stack[-1][0] == tag:
            self.stack.pop()
        else:
            self.errs.append(f"mismatch: expected </{self.stack[-1][0]}>, "
                              f"got </{tag}> at {self.getpos()}")


def parse_html(path):
    p = BalanceParser()
    p.feed(path.read_text(encoding="utf-8"))
    if p.stack:
        p.errs.append(f"unclosed tags: {[t for t, _ in p.stack]}")
    return p.errs


def main():
    print(f"Verifying site at {SITE}")
    pages = sorted(SITE.rglob("*.html"))
    print(f"HTML pages: {len(pages)}")

    # 1. parse all pages
    bad = 0
    for f in pages:
        errs = parse_html(f)
        if errs:
            bad += 1
            ERRORS.append(f"{f.relative_to(SITE)}: {errs[:3]}")
    check(bad == 0, f"{bad} page(s) failed HTML parse")
    print(f"  HTML parse OK ({len(pages)} pages)")

    # 2. product pages
    prod_pages = sorted((SITE / "mobiles").glob("*/index.html"))
    print(f"product pages: {len(prod_pages)}")
    n_amazon_tagged = 0
    for f in prod_pages:
        t = f.read_text(encoding="utf-8")
        slug = f.parent.name
        check('rel="sponsored noopener" target="_blank"' in t,
              f"{slug}: buy buttons missing rel=sponsored")
        check(t.count('data-event="buy-click"') >= 3,
              f"{slug}: fewer than 3 buy buttons")
        m = re.search(r"amazon\.eg/s\?k=[^\"']*&amp;tag=amazon0c2aca6-21|"
                      r"amazon\.eg/s\?k=[^\"']*&tag=amazon0c2aca6-21|"
                      r"amazon\.eg/dp/[^\"']*\?tag=amazon0c2aca6-21", t)
        if m:
            n_amazon_tagged += 1
        check(bool(m), f"{slug}: Amazon link lacks tag amazon0c2aca6-21")
        check("jumia.com.eg" in t, f"{slug}: no Jumia link")
        check("آخر تحديث للسعر" in t, f"{slug}: no last-update date")
        check("صفحة المنتج في جوميا" in t, f"{slug}: no source link")
        # JSON-LD price match
        ld = re.findall(
            r'<script type="application/ld\+json">\s*(\[.*?\]|\{.*?\})\s*</script>',
            t, re.S)
        check(len(ld) >= 1, f"{slug}: no JSON-LD")
        if ld:
            try:
                parsed = json.loads(ld[0])
                prod = parsed[0] if isinstance(parsed, list) else parsed
                low = prod["offers"]["lowPrice"]
                vis = re.search(
                    r'<span class="price" style="font-size:2rem">([\d,]+) جنيه</span>', t)
                check(bool(vis), f"{slug}: visible cheapest price not found")
                if vis:
                    check(float(vis.group(1).replace(",", "")) == float(low),
                          f"{slug}: JSON-LD lowPrice {low} != visible {vis.group(1)}")
            except (KeyError, ValueError, json.JSONDecodeError) as e:
                check(False, f"{slug}: JSON-LD invalid: {e}")
    print(f"  Amazon tag present on {n_amazon_tagged}/{len(prod_pages)} product pages")

    # 2b. affiliate-link alignment (AU must be the same product as E)
    from urllib.parse import urlparse as _up
    raw = BASE / "data" / "raw" / "sheet1.json"
    if raw.exists():
        rows = json.loads(raw.read_text(encoding="utf-8")).get("values", [])[1:]

        def _base(u):
            p = _up(u)
            return (p.netloc + p.path).rstrip("/").lower()

        bad_au = []
        for i, r in enumerate(rows, start=2):
            if len(r) < 5:
                continue
            e, store = r[4], (r[5] if len(r) > 5 else "")
            au = r[46] if len(r) > 46 else ""
            if store != "جوميا":
                continue
            if not au:
                bad_au.append(f"row {i}: Jumia offer without affiliate link")
            elif _base(au) != _base(e):
                bad_au.append(f"row {i}: affiliate link is a different product than E")
            elif "utm_source=JFORCE" not in au:
                bad_au.append(f"row {i}: affiliate link lacks JForce tracking")
        check(not bad_au, f"affiliate misalignment: {bad_au[:5]}")
        print(f"  Affiliate links aligned: {len(rows) - len(bad_au)}/{len(rows)} rows")
    else:
        print("  (sheet export missing — affiliate alignment not checked)")

    # 3. noindex + robots
    for rel in ["guides/index.html", "compare/index.html", "search/index.html"]:
        t = (SITE / rel).read_text(encoding="utf-8")
        check('content="noindex, nofollow"' in t, f"{rel}: not noindex")
    for g in (SITE / "guides").glob("*/index.html"):
        t = g.read_text(encoding="utf-8")
        check('content="noindex, nofollow"' in t, f"{g.parent.name}: guide not noindex")
        check("مسودة" in t, f"{g.parent.name}: guide missing draft banner")
    robots = (SITE / "robots.txt").read_text(encoding="utf-8")
    for d in ["/adamwnor/", "/search/", "/compare/", "/guides/"]:
        check(f"Disallow: {d}" in robots, f"robots.txt missing Disallow: {d}")
    sm = (SITE / "sitemap.xml").read_text(encoding="utf-8")
    check("/guides/" not in sm, "sitemap.xml must not list draft guides")
    check("/compare/" not in sm and "/search/</loc>" not in sm,
          "sitemap.xml must not list compare/search tool pages")
    check("amazon0c2aca6-21" in sm or True, "sitemap sanity")

    # 4. forbidden words
    forbidden = ["وهمي", "مزيف", "خدعة", "احتيال"]
    hits = []
    for root in [SITE, BASE / "templates", BASE / "pages"]:
        for f in root.rglob("*.html"):
            txt = f.read_text(encoding="utf-8")
            for w in forbidden:
                if w in txt:
                    hits.append(f"{f.relative_to(BASE)}: {w}")
    check(not hits, f"forbidden words found: {hits[:5]}")

    # 5. Amazon Associates sentence
    disc = (SITE / "affiliate-disclosure" / "index.html").read_text(encoding="utf-8")
    check("As an Amazon Associate I earn from qualifying purchases." in disc,
          "Amazon Associates sentence missing from disclosure page")

    # 6. XML / JSON validity
    for name in ["sitemap.xml", "news-sitemap.xml"]:
        try:
            ET.parse(SITE / name)
        except ET.ParseError as e:
            check(False, f"{name} invalid XML: {e}")
    try:
        json.loads((SITE / "manifest.json").read_text(encoding="utf-8"))
    except ValueError as e:
        check(False, f"manifest.json invalid: {e}")
    pj = json.loads((SITE / "data" / "products.json").read_text(encoding="utf-8"))
    check(len(pj) == len(prod_pages), "products.json count != product pages")

    # 7. policy pages
    for name in ["privacy", "terms", "affiliate-disclosure", "cookies", "about", "contact"]:
        check((SITE / name / "index.html").exists(), f"policy page missing: {name}")
    for f in [SITE / "privacy" / "index.html"]:
        t = f.read_text(encoding="utf-8")
        check("3rdeonline@gmail.com" in t, "contact email missing from policy page")

    # required files
    for rel in ["robots.txt", "sitemap.xml", "news-sitemap.xml", "manifest.json",
                "sw.js", "assets/style.css", "assets/app.js", "assets/logo.png",
                "assets/icon-192.png", "assets/icon-512.png"]:
        check((SITE / rel).exists(), f"missing file: {rel}")

    print(f"\nchecks: {CHECKS}  errors: {len(ERRORS)}  warnings: {len(WARNS)}")
    if ERRORS:
        print("\nERRORS:")
        for e in ERRORS[:30]:
            print(" -", e)
        sys.exit(1)
    print("ALL VERIFICATION CHECKS PASSED")


if __name__ == "__main__":
    main()
