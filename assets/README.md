# عروض أونلاين — 3rode.online — assets

Prepared 2026-11-19 (research stage, before build go-ahead).

## Files
- `logo-transparent.png` — transparent (RGBA) version of the uploaded logo,
  2135×736, made from
  `~/workspace/user/media_library/image/Glossy_Arabic_Ecommerce_Shopping_Logo.png`
  (original: RGB, no alpha, grey checkerboard background baked in).
  Method: removed all near-neutral grey pixels (R≈G≈B, 120–225) — first by
  flood-fill from the border, then a second pass for enclosed checker pockets
  (25,093 px) and edge fringe — plus a 0.6 px alpha feather.
- `preview-on-white.png`, `preview-on-black.png` — watermark test: logo at
  180 px wide (≈18% of a 1000 px product image), bottom-right corner.
  Verified 2026-11-19: no grey box on white or black; logo stays legible.
  At full size on a dark background a faint light fringe is visible on some
  edges; at watermark size it is not noticeable.

## Watermark setup (done 2026-11-19, at the user's request)

- Source: `logo.png` — the SECOND upload
  (`Glossy_Arabic_Online_Shopping_Logo.png`), 2132×737 RGBA, natively
  transparent. This supersedes `logo-transparent.png` (the cleaned version
  of the first upload, which had a baked-in grey checkerboard and a faint
  fringe on dark backgrounds). The native file has no fringe problem.
- Script: `../scripts/apply-watermark.py` — builds the three watermark
  assets and applies them. Config at the top of the file: size as a
  fraction of the product-image width, opacity 0.92, padding 4%,
  position bottom-right (changeable in settings later).
- Watermark assets (all built from `logo.png`):
  `watermark-full.png` (whole logo), `watermark-text.png`
  ("3rode.online" text only), `watermark-icon.png` (cart with % tag only).
- Demos (real product photo: OPPO A6 from the sheet's Mobizil image,
  500×500): `../watermark-samples/demo-A-full-logo.jpg`,
  `demo-B-text-strip.jpg`, `demo-C-cart-icon.jpg`. Visually verified
  2026-11-19: no grey box on any style; A is small and legible in the
  bottom-right corner; B's dark strip is the most visible but covers the
  bottom ~12% of the product photo; C is the most discreet.
- **Style chosen by the user 2026-11-19: B** — "3rode.online" text in a
  dark strip at the bottom. The script default is now B; the strip was
  refined the same day (slimmer bar, text widened to 62% of image width)
  and the final demo re-verified visually.

## Still undecided — do not build on assumptions
- The WordPress "W" in the cart is still in this transparent version.
  User has not yet answered: keep the W, or replace it with a generic cart
  icon. A W-free variant needs redrawing/inpainting — not done here.
- Build go-ahead itself is still pending (asked in main chat 2026-11-19).
- Domain 3rode.online: no live site found in web search 2026-11-19;
  registration status was NOT verified — check at the registrar before
  assuming it is owned/available.
