#!/usr/bin/env python3
"""Fetch product images for models whose Mobizil image URL is dead.

For each model with image-status local == False, the script fetches the
Jumia product page (the product URL from the Sheet) and takes its main
image (og:image — usually the phone's front view), downloads it, applies
the full-logo watermark (style A) and saves it as the product image.
Models that still have no image keep the placeholder (the 3rde.online
logo badge) — see site/images/placeholder.jpg.

Usage: python3 scripts/fetch-jumia-images.py [--slugs a,b,c]
"""
import importlib.util
import io
import json
import pathlib
import re
import sys
import time
import urllib.request
from urllib.error import HTTPError, URLError

BASE = pathlib.Path(__file__).resolve().parent.parent
DATA = BASE / "data"
SITE = BASE / "site"
SCRIPTS = BASE / "scripts"


def load_helper(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


SH = load_helper("sync_helpers", SCRIPTS / "sync-helpers.py")
WM = load_helper("watermark", SCRIPTS / "apply-watermark.py")
sys.path.insert(0, str(SCRIPTS))
import build as buildmod  # noqa: E402

UA = {"User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                     "AppleWebKit/537.36 (KHTML, like Gecko) "
                     "Chrome/120.0 Safari/537.36"),
      "Accept-Language": "ar-EG,ar;q=0.9,en;q=0.8"}


def fetch_page(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "ignore")


def extract_image(html):
    # og:image first (the product's main photo, usually the front view)
    m = re.search(r'<meta\s+property="og:image"\s+content="([^"]+)"', html)
    if m:
        return m.group(1)
    # JSON-LD fallback
    m = re.search(r'"image"\s*:\s*"([^"]+)"', html)
    if m:
        return m.group(1)
    m = re.search(r'"image"\s*:\s*\[\s*"([^"]+)"', html)
    if m:
        return m.group(1)
    return None


def main():
    only = set()
    if "--slugs" in sys.argv:
        only = set(sys.argv[sys.argv.index("--slugs") + 1].split(","))
    status_file = DATA / "image-status.json"
    status = json.loads(status_file.read_text(encoding="utf-8"))
    from PIL import Image

    done, failed = [], []
    for m in buildmod.MODELS:
        if only and m.slug not in only:
            continue
        st = status.get(m.slug, {})
        if st.get("local") is True:
            continue
        url = buildmod.norm(buildmod.c(m.offers[0], "رابط المنتج"))
        if not url:
            failed.append((m.slug, "no product URL"))
            continue
        try:
            html = fetch_page(url)
            img_url = extract_image(html)
            if not img_url:
                failed.append((m.slug, "no og:image on product page"))
                continue
            img_url = img_url.replace("&amp;", "&")
            req = urllib.request.Request(img_url, headers=UA)
            with urllib.request.urlopen(req, timeout=30) as r:
                data = r.read()
            im = Image.open(io.BytesIO(data))
            orig = SITE / "images" / "originals" / f"{m.slug}.jpg"
            orig.parent.mkdir(parents=True, exist_ok=True)
            im.convert("RGB").save(orig, quality=92)
            target = SITE / "images" / "products" / f"{m.slug}.jpg"
            WM.apply_to_product(im, "A").save(target, quality=92)
            status[m.slug] = {"local": True, "working_url": img_url,
                              "note": "jumia product page og:image + watermark A"}
            done.append(m.slug)
            print(f"OK   {m.slug}  <- {img_url[:90]}")
        except HTTPError as e:
            failed.append((m.slug, f"product page HTTP {e.code}"))
            print(f"FAIL {m.slug}: product page HTTP {e.code}")
        except (URLError, OSError) as e:
            failed.append((m.slug, f"fetch error: {e}"))
            print(f"FAIL {m.slug}: {e}")
        except Exception as e:  # noqa: BLE001
            failed.append((m.slug, str(e)[:100]))
            print(f"FAIL {m.slug}: {e}")
        time.sleep(0.7)
    status_file.write_text(json.dumps(status, ensure_ascii=False, indent=1),
                           encoding="utf-8")
    print(f"\ndownloaded: {len(done)}  failed: {len(failed)}")
    for slug, why in failed:
        print(f"  - {slug}: {why}")


if __name__ == "__main__":
    main()
