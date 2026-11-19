#!/usr/bin/env python3
"""Hourly sync for 3rde.online (عروض أونلاين).

What it does, in order:
  1. Refresh data/raw/*.json from the Google Sheet when possible
     (hatch_gws_cli on this machine, or the Apps Script export endpoint
     when settings.admin.apps_script_url is set). On shared hosting
     neither may exist — then it reuses the exported JSON files.
  2. Diff offers against data/last-sync.json (by product URL).
     Price-history rows are appended ONLY when a price actually
     changed (sync-helpers.should_log_price — audit ت-3).
  3. Download product images that are missing locally:
     try the w_800 upgrade, fall back to the original URL, and if both
     fail mark the image DEAD in data/image-status.json so the build
     uses the placeholder and the admin can fix the sheet URL.
     Downloaded images get the full-logo watermark badge (style A, scripts/apply-watermark.py)
     and the original is kept under site/images/originals/.
  4. Rebuild the site (scripts/build.py).
  5. Write data/sync-log.json (timestamp, counts, changes, failures).

Run by cron on the hosting, hourly:
    0 * * * * /usr/bin/python3 /home/<user>/3rode-online/scripts/sync.py

It never writes to the Sheet itself (audit ت-11: the Sheet is written
only by hand or by the Apps Script admin backend, never by this sync).
"""
import importlib.util
import json
import pathlib
import shutil
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone

BASE = pathlib.Path(__file__).resolve().parent.parent
DATA = BASE / "data"
RAW = DATA / "raw"
SITE = BASE / "site"
SCRIPTS = BASE / "scripts"


def load_helper(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


SH = load_helper("sync_helpers", SCRIPTS / "sync-helpers.py")
WM = load_helper("watermark", SCRIPTS / "apply-watermark.py")
SETTINGS = json.loads((BASE / "settings.json").read_text(encoding="utf-8"))

LOG = {"started_at": datetime.now(timezone.utc).isoformat(),
       "steps": [], "price_changes": [], "image_downloads": [],
       "image_failures": [], "errors": []}


def log(step, detail=""):
    LOG["steps"].append(f"{step}: {detail}" if detail else step)
    print(f"[{step}] {detail}")


def refresh_from_sheet():
    """Try to re-export the sheet tabs. Returns True if anything refreshed."""
    refreshed = False
    sheet_id = SETTINGS.get("sheet_id") or ""
    if not sheet_id:
        m = __import__("re").search(r"/d/([A-Za-z0-9_-]+)",
                                    SETTINGS.get("sheet_url", ""))
        sheet_id = m.group(1) if m else ""
    cli = pathlib.Path("/opt/hatch/bin/hatch_gws_cli")
    tabs = {"sheet1.json": "الورقة1", "summary.json": "ملخص",
            "price_history.json": "سجل الأسعار", "duplicates.json": "المكرر فقط"}
    if cli.exists() and sheet_id:
        for fname, tab in tabs.items():
            try:
                out = subprocess.run(
                    [str(cli), "sheets", "spreadsheets", "values", "get",
                     "--params", json.dumps(
                         {"spreadsheetId": sheet_id, "range": tab})],
                    capture_output=True, text=True, timeout=60)
                if out.returncode == 0 and out.stdout.strip():
                    (RAW / fname).write_text(out.stdout, encoding="utf-8")
                    refreshed = True
            except Exception as e:  # noqa: BLE001 - sync must not die
                LOG["errors"].append(f"sheet export {tab}: {e}")
    if not refreshed:
        apps_url = SETTINGS.get("admin", {}).get("apps_script_url", "")
        if apps_url:
            try:
                with urllib.request.urlopen(
                        apps_url + "?action=export", timeout=60) as r:
                    payload = json.loads(r.read().decode("utf-8"))
                for fname, values in payload.get("tabs", {}).items():
                    (RAW / fname).write_text(
                        json.dumps({"values": values}, ensure_ascii=False),
                        encoding="utf-8")
                    refreshed = True
                # Adopt the homepage layout chosen in the admin panel
                # (Sheet tab "الإعدادات" -> settings.json -> build.py).
                _hl = str((payload.get("settings") or {}).get(
                    "home_layout", "") or "").strip().lower()
                if _hl in ("classic", "rows", "deals", "store", "compact",
                          "luxury", "forest", "royal", "sunset", "minimal",
                          "showcase", "fullrows", "quick"):
                    if SETTINGS.get("home_layout", "classic") != _hl:
                        SETTINGS["home_layout"] = _hl
                        (BASE / "settings.json").write_text(
                            json.dumps(SETTINGS, ensure_ascii=False, indent=2),
                            encoding="utf-8")
                        log("home-layout", f"adopted {_hl} from Sheet settings")
            except Exception as e:  # noqa: BLE001
                LOG["errors"].append(f"apps script export: {e}")
    log("refresh-sheet", "refreshed" if refreshed else "kept existing exports")
    return refreshed


def _num(v, default=None):
    """Parse a number, tolerating Arabic-Indic digits and Arabic separators
    (same logic as build.py num(); sync-helpers has no number parser)."""
    if v is None or str(v).strip() == "":
        return default
    s = str(v).strip()
    for i, d in enumerate("٠١٢٣٤٥٦٧٨٩"):
        s = s.replace(d, str(i))
    s = s.replace("٫", ".").replace("٬", "").replace(",", "").replace(" ", "")
    try:
        return float(s)
    except ValueError:
        return default


def diff_prices():
    """Compare current sheet offers with the last snapshot; return changes."""
    rows = json.loads((RAW / "sheet1.json").read_text(encoding="utf-8"))["values"]
    header = [str(h).strip() for h in rows[0]]
    col = {name: i for i, name in enumerate(header)}
    cur = {}
    for r in rows[1:]:
        if not any(str(c).strip() for c in r):
            continue
        url = r[col["رابط المنتج"]]
        cur[url] = _num(r[col["السعر الحالي (بعد الخصم) - جنيه"]])
    snap_file = DATA / "last-sync.json"
    prev = json.loads(snap_file.read_text(encoding="utf-8")) if snap_file.exists() else {}
    changes = []
    for url, price in cur.items():
        old = prev.get(url)
        if old is not None and SH.should_log_price(old, price):
            diff, pct = SH.price_change(old, price)
            changes.append({"url": url, "old": old, "new": price,
                            "diff": diff, "pct": pct,
                            "date": datetime.now().date().isoformat()})
    snap_file.write_text(json.dumps(cur, ensure_ascii=False), encoding="utf-8")
    LOG["price_changes"] = changes
    log("diff-prices", f"{len(changes)} price change(s) — history rows only for these")
    return changes


def download_images(limit_per_run=20):
    """Download missing model images (w_800, fallback original), full-logo watermark (style A).
    Only models without a local file are attempted; at most `limit_per_run`
    new downloads per run so an hourly cron stays fast."""
    import build as buildmod  # reuse the generator's model list
    status_file = DATA / "image-status.json"
    status = json.loads(status_file.read_text(encoding="utf-8")) if status_file.exists() else {}
    done = 0
    for m in buildmod.MODELS:
        if done >= limit_per_run:
            break
        target = SITE / "images" / "products" / f"{m.slug}.jpg"
        if target.exists():
            continue
        st = status.get(m.slug, {})
        if st.get("local") is False and st.get("tried_at") == datetime.now().date().isoformat():
            continue  # already failed today; retry tomorrow
        urls = [m.image_remote]
        raw = buildmod.norm(buildmod.c(m.offers[0], "رابط صورة المنتج"))
        if raw and raw != m.image_remote:
            urls.append(raw)
        ok = False
        for url in urls:
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=30) as r:
                    data = r.read()
                from PIL import Image
                import io
                im = Image.open(io.BytesIO(data))
                orig = SITE / "images" / "originals" / f"{m.slug}.jpg"
                orig.parent.mkdir(parents=True, exist_ok=True)
                im.convert("RGB").save(orig, quality=92)
                WM.apply_to_product(im, "A").save(target, quality=92)
                status[m.slug] = {"local": True, "working_url": url,
                                  "note": "downloaded + watermarked A"}
                LOG["image_downloads"].append(m.slug)
                ok = True
                done += 1
                break
            except Exception as e:  # noqa: BLE001
                continue
        if not ok:
            status[m.slug] = {"local": False, "working_url": urls[-1],
                              "tried_at": datetime.now().date().isoformat(),
                              "note": "both w_800 and original URLs failed (404?) — placeholder used"}
            LOG["image_failures"].append(m.slug)
    status_file.write_text(json.dumps(status, ensure_ascii=False, indent=1),
                           encoding="utf-8")
    log("download-images", f"{done} new, {len(LOG['image_failures'])} failed")


def main():
    sys.path.insert(0, str(SCRIPTS))
    try:
        refresh_from_sheet()
        changes = diff_prices()
        if changes:
            # append to the local price-history file (merged by build.py
            # via data/raw/price_history.json on next export; the Sheet tab
            # itself is updated by the Apps Script admin backend)
            hist_file = DATA / "price_history_local.json"
            hist = json.loads(hist_file.read_text(encoding="utf-8")) if hist_file.exists() else []
            hist.extend(changes)
            hist_file.write_text(json.dumps(hist, ensure_ascii=False, indent=1),
                                 encoding="utf-8")
        download_images()
        r = subprocess.run([sys.executable, str(SCRIPTS / "build.py")],
                           capture_output=True, text=True, timeout=600)
        print(r.stdout)
        if r.returncode != 0:
            LOG["errors"].append(f"build.py failed: {r.stderr[-2000:]}")
            print(r.stderr, file=sys.stderr)
        else:
            log("build", "site rebuilt OK")
    except Exception as e:  # noqa: BLE001 - always write the log
        LOG["errors"].append(str(e))
        print(f"SYNC ERROR: {e}", file=sys.stderr)
    LOG["finished_at"] = datetime.now(timezone.utc).isoformat()
    (DATA / "sync-log.json").write_text(json.dumps(LOG, ensure_ascii=False, indent=1),
                                        encoding="utf-8")
    print(f"sync log: {DATA / 'sync-log.json'}")
    return 0 if not LOG["errors"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
