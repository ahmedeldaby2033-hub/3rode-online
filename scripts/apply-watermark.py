#!/usr/bin/env python3
"""Watermark setup for 3rde.online (عروض أونلاين).

Source logo: assets/logo.png — the second upload
(Glossy_Arabic_Online_Shopping_Logo.png), 2132x737 RGBA, natively
transparent. This is the correct source; the first upload had a baked-in
grey checkerboard and was only usable after background removal
(see assets/logo-transparent.png, the cleaned version of the first file).

Three watermark styles are produced from the same logo:
  A) full logo, bottom corner (default)
  B) "3rde.online" text only, centred in a dark strip at the bottom
  C) cart icon only, bottom corner

The hourly sync will call apply_to_product() for every downloaded
product image: download -> watermark -> save to hosting -> keep the
original unwatermarked copy as backup. If a download fails, the site
shows the original URL without a watermark and logs it.

Usage:
  python3 apply-watermark.py --demo     # rebuild demo images
  python3 apply-watermark.py in.jpg out.jpg --style A
"""
import argparse
import pathlib

from PIL import Image, ImageDraw, ImageOps

BASE = pathlib.Path(__file__).resolve().parent.parent
ASSETS = BASE / "assets"
SAMPLES = BASE / "watermark-samples"

# ---------------------------------------------------------------- config
# Width of the watermark as a fraction of the product-image width.
FULL_WIDTH_FRAC = 0.25     # style A: full logo
TEXT_WIDTH_FRAC = 0.62     # style B: "3rde.online" text in the strip
ICON_WIDTH_FRAC = 0.15     # style C: cart icon
OPACITY = 0.92             # watermark opacity (1.0 = fully opaque)
PADDING_FRAC = 0.04        # padding from the image edge, as fraction of width
POSITION = "bottom-right"  # or "bottom-left" — change in settings later
DEFAULT_STYLE = "B"        # chosen by the user 2026-11-19: text strip


def load_logo() -> Image.Image:
    logo = Image.open(ASSETS / "logo.png").convert("RGBA")
    return logo


def trim(img: Image.Image) -> Image.Image:
    """Crop to the bounding box of non-transparent pixels."""
    bbox = img.getbbox()
    return img.crop(bbox) if bbox else img


def with_opacity(img: Image.Image, opacity: float) -> Image.Image:
    img = img.copy()
    alpha = img.getchannel("A").point(lambda p: int(p * opacity))
    img.putalpha(alpha)
    return img


def build_assets() -> dict:
    """Create the three watermark PNGs in assets/ and return their paths."""
    logo = load_logo()

    full = trim(logo)
    full.save(ASSETS / "watermark-full.png")

    # "3rde.online" text lives in the lower band of the logo.
    w, h = logo.size
    text = trim(logo.crop((int(w * 0.32), int(h * 0.60), w, h)))
    text.save(ASSETS / "watermark-text.png")

    # Cart (with % tag) lives in the left part of the logo.
    icon = trim(logo.crop((0, 0, int(w * 0.38), int(h * 0.78))))
    icon.save(ASSETS / "watermark-icon.png")

    return {
        "A": ASSETS / "watermark-full.png",
        "B": ASSETS / "watermark-text.png",
        "C": ASSETS / "watermark-icon.png",
    }


def _scaled(wm: Image.Image, target_w: int) -> Image.Image:
    ratio = target_w / wm.width
    return wm.resize((target_w, max(1, int(wm.height * ratio))),
                     Image.LANCZOS)


def apply_to_product(product: Image.Image, style: str = "A") -> Image.Image:
    """Return a watermarked copy of a product image (RGB)."""
    base = product.convert("RGB")
    w, h = base.size
    pad = int(w * PADDING_FRAC)
    assets = build_assets()

    if style == "A":
        wm = with_opacity(Image.open(assets["A"]).convert("RGBA"), OPACITY)
        wm = _scaled(wm, int(w * FULL_WIDTH_FRAC))
        x = w - wm.width - pad if POSITION == "bottom-right" else pad
        y = h - wm.height - pad
        base.paste(wm, (x, y), wm)

    elif style == "B":
        wm = with_opacity(Image.open(assets["B"]).convert("RGBA"), OPACITY)
        wm = _scaled(wm, int(w * TEXT_WIDTH_FRAC))
        bar_h = wm.height + pad
        bar = Image.new("RGBA", (w, bar_h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(bar)
        draw.rounded_rectangle([0, 0, w, bar_h], radius=bar_h // 3,
                               fill=(10, 20, 40, 150))
        overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
        overlay.paste(bar, (0, h - bar_h))
        base = Image.alpha_composite(base.convert("RGBA"), overlay).convert("RGB")
        x = (w - wm.width) // 2
        y = h - bar_h + (bar_h - wm.height) // 2
        base.paste(wm, (x, y), wm)

    elif style == "C":
        wm = with_opacity(Image.open(assets["C"]).convert("RGBA"), OPACITY)
        wm = _scaled(wm, int(w * ICON_WIDTH_FRAC))
        x = w - wm.width - pad if POSITION == "bottom-right" else pad
        y = h - wm.height - pad
        base.paste(wm, (x, y), wm)

    else:
        raise ValueError(f"unknown style {style!r}")
    return base


def demo() -> None:
    SAMPLES.mkdir(parents=True, exist_ok=True)
    sample = SAMPLES / "sample-product.jpg"
    if not sample.exists():
        raise SystemExit(f"sample product image missing: {sample}\n"
                         "Download one from the sheet first, e.g. the "
                         "OPPO A6 Mobizil image, and save it there.")
    product = Image.open(sample)
    for style, name in (("A", "full-logo"), ("B", "text-strip"),
                        ("C", "cart-icon")):
        out = apply_to_product(product, style)
        out.save(SAMPLES / f"demo-{style}-{name}.jpg", quality=92)
        print(f"demo {style} ({name}):", SAMPLES / f"demo-{style}-{name}.jpg")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("input", nargs="?")
    ap.add_argument("output", nargs="?")
    ap.add_argument("--style", default=DEFAULT_STYLE,
                    choices=["A", "B", "C"])
    ap.add_argument("--demo", action="store_true")
    args = ap.parse_args()
    if args.demo:
        demo()
    elif args.input and args.output:
        apply_to_product(Image.open(args.input), args.style) \
            .save(args.output, quality=92)
        print("saved", args.output)
    else:
        ap.print_help()
