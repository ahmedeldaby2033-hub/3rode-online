#!/usr/bin/env python3
"""Download product images found by web image search for the models whose
Mobizil/Jumia image URLs are dead. Each URL was picked by hand from the
search results (front view, or front+back where available). The image is
converted to RGB JPEG, watermarked (style A, full logo badge) and saved as
the product image; image-status.json is updated. Models with no usable
image keep the placeholder (the 3rde.online logo badge).

Usage: python3 scripts/fetch-found-images.py
"""
import importlib.util
import io
import json
import pathlib
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


WM = load_helper("watermark", SCRIPTS / "apply-watermark.py")

# slug -> (image url, source page) — front view preferred, else front+back
IMAGES = {
    "samsung-galaxy-a18-128gb-4gb": (
        "https://www.affordablemobiles.co.uk/files/images/handsets/samsung/1_a18_front-and-back-w-logo_silver_400x600.png",
        "https://www.affordablemobiles.co.uk/samsung/samsung-galaxy-a18-4g-128gb-silver"),
    "samsung-galaxy-a18-256gb-8gb": (
        "https://www.affordablemobiles.co.uk/files/images/handsets/samsung/1_a18_front-and-back-w-logo_silver_400x600.png",
        "https://www.affordablemobiles.co.uk/samsung/samsung-galaxy-a18-4g-128gb-silver"),
    "tecno-camon-40-pro-256gb-12gb": (
        "https://www.ufoelektronika.com/image/cache/catalog/product/TECNO-CAMON-40-2-1000x1000.jpg",
        "https://www.ufoelektronika.com/tecno-camon-40-pro-5g-8256-gb-mediatek-d7300-ultimate-6.78-fhd-144hz-3d-curved-amoled-50mp-sony-8mp-ultra-wide-camera-50mp-front-camera-5200mah-ip6869-camon40pro5gram8256"),
    "tecno-spark-40-pro-128gb-8gb": (
        "https://d13pvy8xd75yde.cloudfront.net/global/spark-40-pro/KM6%20%E9%92%9B.png",
        "https://www.tecno-mobile.com/"),
    "tecno-spark-slim-256gb-8gb": (
        "https://fonexpress.net/wp-content/uploads/2025/11/Tecno-Spark-Slim-500x500.jpg",
        "https://fonexpress.net/"),
    "tecno-spark-50-128gb-6gb": (
        "https://matendes-marketplace1.s3.eu-north-1.amazonaws.com/uploads/all/MOndFaZXYczYKr438FOtp0G1ygrcKO5gZngdjr2R.webp",
        "https://matendes-marketplace1.s3.eu-north-1.amazonaws.com/"),
    "vivo-y31d-128gb-6gb": (
        "https://m.media-amazon.com/images/I/71aQp3CRLiL._SL1500_.jpg",
        "https://www.amazon.com/"),
    "xiaomi-redmi-15-128gb-6gb": (
        "https://www.mojandroid.sk/wp-content/uploads/2025/08/redmi15_03.jpg",
        "https://www.mojandroid.sk/"),
    "xiaomi-redmi-turbo-5-256gb-12gb": (
        "https://d2cdo4blch85n8.cloudfront.net/wp-content/uploads/2026/04/Redmi-Turbo-5-Smartphone-1-1024x1024.jpg",
        "https://d2cdo4blch85n8.cloudfront.net/"),
    "nokia-105": (
        "https://media-ik.croma.com/Croma%20Assets/Communication/Mobiles/Images/274279_fsoyg0.png",
        "https://www.croma.com/"),
    "nokia-106-4mb": (
        "https://img-prd-pim.poorvika.com/product/nokia-106-2023-single-sim-black-front-backv-iew.png",
        "https://www.poorvika.com/"),
    "nokia-106-4g-4mb": (
        "https://img-prd-pim.poorvika.com/product/nokia-106-2023-single-sim-black-front-backv-iew.png",
        "https://www.poorvika.com/"),
    "nokia-150": (
        "https://cdn.shopify.com/s/files/1/0690/1150/5372/files/3_ae5b68ec-ab21-4f6a-9fd6-0a0dbe4b9b0a.png?v=1776247195",
        "https://cdn.shopify.com/"),
    "nokia-5310-16mb-8mb": (
        "https://sosukeblog.com/wp-content/uploads/2020/03/20200329_301.jpg",
        "https://sosukeblog.com/"),
    "itel-a200-128gb-3gb": (
        "https://img.gsmchoice.com/phones/itel_a200/phone_bigx2/itel_a200-big.jpg",
        "https://www.gsmchoice.com/"),
    "itel-p40-128gb-8gb": (
        "https://mobileinto.com/images/largepic/large_itel-p40_3.jpg",
        "https://mobileinto.com/"),
    "micromax-x412-32mb": (
        "https://kimostore.net/cdn/shop/files/MicromaxX412DualSIM_32MB32MBRam1.77Inch2G_2_5dcb13fa-80d5-452d-9d4f-10929b79e0a6_1024x.jpg?v=1776857886",
        "https://kimostore.net/"),
    "micromax-x415-32mb": (
        "https://m.media-amazon.com/images/I/51Ba05XOqRL._SL1500_.jpg",
        "https://www.amazon.com/"),
    "girasole-g30": (
        "https://f.nooncdn.com/p/pzsku/ZE6F657736F5AD790DB1EZ/45/_/1701868704/a26047d6-6afb-4652-9588-7f263332e213.jpg?width=800",
        "https://www.noon.com/"),
    "girasole-g30-32gb-32mb": (
        "https://f.nooncdn.com/p/pzsku/ZE6F657736F5AD790DB1EZ/45/_/1701868704/a26047d6-6afb-4652-9588-7f263332e213.jpg?width=800",
        "https://www.noon.com/"),
    "pluzz-hero-600s-24mb": (
        "https://strgimgr.b-cdn.net/sized/840/608631-8200e9ce6dffa9ba73eb4cc1ca9ea675.jpg?width=384&height=384&quality=90",
        "https://strgimgr.b-cdn.net/"),
    "sary-s101-32gb": (
        "https://mobilaty.com/wp-content/uploads/2026/10/SaryS101Bk_1-1.png",
        "https://mobilaty.com/"),
    "sary-s201": (
        "https://eg.jumia.is/unsafe/fit-in/520x520/filters:fill(white)/product/84/6281531/1.jpg?4474",
        "https://www.jumia.com.eg/"),
    "shitel-trend-16gb-2gb": (
        "https://api.cezma.cloud/storage/thumbnails/products/web/17907827391000097413.png",
        "https://api.cezma.cloud/"),
    "hope-k19-64mb-64mb": (
        "https://alsyaad.com/cdn/shop/files/rn-image_picker_lib_temp_3e589b70-b503-46cf-bb1b-82c6a55e0cf6.png?v=1787114384&width=1254",
        "https://alsyaad.com/"),
    "i-pro-a7-mini-1gb-1gb": (
        "https://www.electrochaabani.com/images/upload/telephoneportableiproa7mininoirbleu-652975b26a5ae0.60856091.jpg?v19",
        "https://www.electrochaabani.com/"),
    "tag-phone-specialtagphone-128gb-6gb": (
        "https://tagtech.global/wp-content/uploads/2023/03/Plus-Brown-3-430x351.png",
        "https://tagtech.global/"),
}

UA = {"User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                     "AppleWebKit/537.36 (KHTML, like Gecko) "
                     "Chrome/120.0 Safari/537.36"),
      "Accept": "image/png,image/jpeg,image/gif,image/webp,image/*;q=0.5"}


def main():
    from PIL import Image
    status_file = DATA / "image-status.json"
    status = json.loads(status_file.read_text(encoding="utf-8"))
    done, failed = [], []
    for slug, (url, referer) in IMAGES.items():
        try:
            headers = dict(UA)
            headers["Referer"] = referer
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=30) as r:
                ctype = r.headers.get("Content-Type", "")
                data = r.read()
            if "image" not in ctype and not data[:4] in (
                    b"\xff\xd8\xff\xe0", b"\xff\xd8\xff\xe1", b"\x89PNG",
                    b"RIFF"):
                raise ValueError(f"not an image (content-type {ctype})")
            im = Image.open(io.BytesIO(data))
            if im.mode in ("RGBA", "LA", "PA"):
                bg = Image.new("RGB", im.size, (255, 255, 255))
                bg.paste(im, mask=im.split()[-1])
                im = bg
            else:
                im = im.convert("RGB")
            orig = SITE / "images" / "originals" / f"{slug}.jpg"
            orig.parent.mkdir(parents=True, exist_ok=True)
            im.save(orig, quality=92)
            target = SITE / "images" / "products" / f"{slug}.jpg"
            WM.apply_to_product(im, "A").save(target, quality=92)
            status[slug] = {"local": True, "working_url": url,
                            "note": "web image search + watermark A"}
            done.append(slug)
            print(f"OK   {slug} ({im.size[0]}x{im.size[1]})")
        except HTTPError as e:
            failed.append((slug, f"HTTP {e.code}"))
            print(f"FAIL {slug}: HTTP {e.code}")
        except (URLError, OSError, ValueError) as e:
            failed.append((slug, str(e)[:100]))
            print(f"FAIL {slug}: {e}")
        except Exception as e:  # noqa: BLE001
            failed.append((slug, str(e)[:100]))
            print(f"FAIL {slug}: {e}")
        time.sleep(0.5)
    status_file.write_text(json.dumps(status, ensure_ascii=False, indent=1),
                           encoding="utf-8")
    print(f"\ndownloaded: {len(done)}  failed: {len(failed)}")
    for slug, why in failed:
        print(f"  - {slug}: {why}")


if __name__ == "__main__":
    main()
