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
            "price_history.json": "سجل الأسعار", "duplicates.json": "المكرر فقط",
            "coupons.json": "الكوبونات", "redirects.json": "إعادة التوجيه",
            # Guides + news were missing here (2026-11-25): their raw files
            # only refreshed via the Apps Script fallback, which never runs
            # when the CLI succeeds — so local syncs built stale guides
            # (the 3 guides stayed "draft" with empty reviews even though
            # the Sheet said "published"). The VPS never hit this because
            # hatch_gws_cli does not exist there, so it always uses the
            # Apps Script export. Refreshing them here makes local syncs
            # match the VPS.
            "guides.json": "الأدلة", "news.json": "الأخبار"}
    if cli.exists() and sheet_id:
        for fname, tab in tabs.items():
            try:
                # valueRenderOption FORMULA: the default FORMATTED_VALUE read
                # returns STALE values for recently-written cells (verified
                # 2026-11-20: ratings written minutes earlier read back as
                # old 1.2/1.3). FORMULA returns the actual stored content.
                out = subprocess.run(
                    [str(cli), "sheets", "spreadsheets", "values", "get",
                     "--params", json.dumps(
                         {"spreadsheetId": sheet_id, "range": tab,
                          "valueRenderOption": "FORMULA"})],
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
                # Adopt the stores chosen in the admin panel
                # (Sheet tab "الإعدادات" -> settings.json -> build.py).
                _stores_raw = str((payload.get("settings") or {}).get(
                    "stores_json", "") or "").strip()
                if _stores_raw:
                    try:
                        _stores = json.loads(_stores_raw)
                        if (isinstance(_stores, list)
                                and SETTINGS.get("stores") != _stores):
                            SETTINGS["stores"] = _stores
                            (BASE / "settings.json").write_text(
                                json.dumps(SETTINGS, ensure_ascii=False,
                                           indent=2),
                                encoding="utf-8")
                            log("stores",
                                f"adopted {len(_stores)} stores from "
                                "Sheet settings")
                    except Exception:
                        pass
                # Adopt the brand order chosen in the admin panel
                # (Sheet tab "الإعدادات" -> settings.json -> build.py).
                _brands_raw = str((payload.get("settings") or {}).get(
                    "brand_order_json", "") or "").strip()
                if _brands_raw:
                    try:
                        _brands = json.loads(_brands_raw)
                        if (isinstance(_brands, list)
                                and all(isinstance(b, str)
                                        for b in _brands)
                                and SETTINGS.get("brand_order") != _brands):
                            SETTINGS["brand_order"] = _brands
                            (BASE / "settings.json").write_text(
                                json.dumps(SETTINGS, ensure_ascii=False,
                                           indent=2),
                                encoding="utf-8")
                            log("brand-order",
                                f"adopted {len(_brands)} brands from "
                                "Sheet settings")
                    except Exception:
                        pass
            except Exception as e:  # noqa: BLE001
                LOG["errors"].append(f"apps script export: {e}")
    log("refresh-sheet", "refreshed" if refreshed else "kept existing exports")
    return refreshed


def _tags_list(v):
    """Split a tags cell on comma or Arabic comma into a list."""
    if isinstance(v, list):
        return [str(t).strip() for t in v if str(t).strip()]
    return [t.strip() for t in str(v or "").replace("،", ",").split(",")
            if t.strip()]


def sync_guides_from_raw():
    """Convert the Sheet's «الأدلة» tab export into data/guides.json
    (the file build.py reads). Mirrors sync_coupons_from_raw().
    SAFETY: if the raw tab has fewer than 2 rows (header only / empty),
    the local file is NOT overwritten — a fresh/empty tab must never
    wipe the site's guides. Merge-preserve by slug from the existing
    local file: guides keep local-only 'hidden', 'tips', 'is_example'."""
    src = None
    for cand in (RAW / "guides.json", RAW / "الأدلة"):
        if cand.exists():
            src = cand
            break
    if src is None:
        return
    try:
        raw = json.loads(src.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        LOG["errors"].append(f"guides raw parse: {e}")
        return
    values = raw.get("values", []) if isinstance(raw, dict) else raw
    if not isinstance(values, list) or len(values) < 2:
        log("guides", f"raw {src.name} has <2 rows — keeping local file")
        return
    header = [str(h).strip() for h in values[0]]

    def col(row, name, default=""):
        try:
            i = header.index(name)
        except ValueError:
            return default
        return row[i] if i < len(row) else default

    existing = {}
    note = None
    gf = DATA / "guides.json"
    if gf.exists():
        try:
            old = json.loads(gf.read_text(encoding="utf-8"))
            note = old.get("note")
            for g in old.get("guides", []):
                existing[g.get("slug")] = g
        except Exception:  # noqa: BLE001
            pass
    guides = []
    for row in values[1:]:
        slug = str(col(row, "slug", "")).strip()
        if not slug:
            continue
        prev = existing.get(slug, {})
        st = str(col(row, "status", "")).strip() or "draft"
        guides.append({
            "slug": slug,
            "title": str(col(row, "title", "")).strip(),
            "criterion": str(col(row, "criterion", "")).strip(),
            "description": str(col(row, "description", "")).strip(),
            "human_review": str(col(row, "human_review", "")).strip(),
            "status": st,
            "author": str(col(row, "author", "")).strip() or "فريق عروض أونلاين",
            "date": str(col(row, "date", "")).strip(),
            "publish_at": str(col(row, "publish_at", "")).strip(),
            "image": str(col(row, "image", "")).strip(),
            "image_alt": str(col(row, "image_alt", "")).strip(),
            "keyword": str(col(row, "keyword", "")).strip(),
            "meta_title": str(col(row, "meta_title", "")).strip(),
            "meta_desc": str(col(row, "meta_desc", "")).strip(),
            "tags": _tags_list(col(row, "tags", "")),
            # A guide marked published in the Sheet must never stay hidden:
            # otherwise "نشر" from the panel silently changes nothing on
            # the site (hit 2026-11-25 with the gaming/camera/battery guides).
            "hidden": bool(prev.get("hidden", False)) and st != "published",
            "tips": prev.get("tips", []),
            "is_example": bool(prev.get("is_example", False)),
        })
    out = {"guides": guides}
    if note:
        out["note"] = note
    gf.write_text(json.dumps(out, ensure_ascii=False, indent=1),
                  encoding="utf-8")
    log("guides", f"synced {len(guides)} guides from {src.name}")


def sync_news_from_raw():
    """Convert the Sheet's «الأخبار» tab export into data/news.json
    (the file build.py reads). Mirrors sync_coupons_from_raw().
    SAFETY: same <2-rows guard as guides — an empty tab must never
    wipe the site's news. Merge-preserve by slug: news keeps local-only
    'date_modified'."""
    src = None
    for cand in (RAW / "news.json", RAW / "الأخبار"):
        if cand.exists():
            src = cand
            break
    if src is None:
        return
    try:
        raw = json.loads(src.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        LOG["errors"].append(f"news raw parse: {e}")
        return
    values = raw.get("values", []) if isinstance(raw, dict) else raw
    if not isinstance(values, list) or len(values) < 2:
        log("news", f"raw {src.name} has <2 rows — keeping local file")
        return
    header = [str(h).strip() for h in values[0]]

    def col(row, name, default=""):
        try:
            i = header.index(name)
        except ValueError:
            return default
        return row[i] if i < len(row) else default

    existing = {}
    note = None
    nf = DATA / "news.json"
    if nf.exists():
        try:
            old = json.loads(nf.read_text(encoding="utf-8"))
            note = old.get("note")
            for p in old.get("posts", []):
                existing[p.get("slug")] = p
        except Exception:  # noqa: BLE001
            pass
    posts = []
    for row in values[1:]:
        slug = str(col(row, "slug", "")).strip()
        if not slug:
            continue
        prev = existing.get(slug, {})
        act = col(row, "is_example", False)
        is_ex = act not in (False, "false", "FALSE", "0", "no", "No", "NO", "")
        posts.append({
            "slug": slug,
            "title": str(col(row, "title", "")).strip(),
            "description": str(col(row, "description", "")).strip(),
            "body": str(col(row, "body", "")).strip(),
            "model_slug": str(col(row, "model_slug", "")).strip(),
            "author": str(col(row, "author", "")).strip() or "فريق عروض أونلاين",
            "date_published": str(col(row, "date_published", "")).strip(),
            "date_modified": prev.get("date_modified") or str(col(row, "date_published", "")).strip(),
            "is_example": is_ex,
            "publish_at": str(col(row, "publish_at", "")).strip(),
            "image": str(col(row, "image", "")).strip(),
            "image_alt": str(col(row, "image_alt", "")).strip(),
            "keyword": str(col(row, "keyword", "")).strip(),
            "meta_title": str(col(row, "meta_title", "")).strip(),
            "meta_desc": str(col(row, "meta_desc", "")).strip(),
            "tags": _tags_list(col(row, "tags", "")),
            "category": str(col(row, "category", "")).strip(),
        })
    out = {"posts": posts}
    if note:
        out["note"] = note
    nf.write_text(json.dumps(out, ensure_ascii=False, indent=1),
                  encoding="utf-8")
    log("news", f"synced {len(posts)} news posts from {src.name}")


def sync_coupons_from_raw():
    """Convert the Sheet's «الكوبونات» tab export into data/coupons.json
    (the file build.py reads). The admin panel writes coupons to the
    Sheet; without this step they would never reach the site.
    Raw source: data/raw/coupons.json (CLI path) or data/raw/الكوبونات
    (Apps Script export path, which files exports by tab name).
    Keeps the existing file's note and per-id is_example flags."""
    src = None
    for cand in (RAW / "coupons.json", RAW / "الكوبونات"):
        if cand.exists():
            src = cand
            break
    if src is None:
        return
    try:
        raw = json.loads(src.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        LOG["errors"].append(f"coupons raw parse: {e}")
        return
    values = raw.get("values", []) if isinstance(raw, dict) else raw
    if not isinstance(values, list) or len(values) < 2:
        return
    header = [str(h).strip() for h in values[0]]

    def col(row, name, default=""):
        try:
            i = header.index(name)
        except ValueError:
            return default
        return row[i] if i < len(row) else default

    existing = {}
    note = ("كوبونات تُدار من لوحة التحكم (تبويب الكوبونات في الشيت).")
    cf = DATA / "coupons.json"
    if cf.exists():
        try:
            old = json.loads(cf.read_text(encoding="utf-8"))
            note = old.get("note", note)
            for c in old.get("coupons", []):
                existing[c.get("id")] = c
        except Exception:  # noqa: BLE001
            pass
    coupons = []
    for row in values[1:]:
        cid = str(col(row, "id", "")).strip()
        if not cid and not str(col(row, "code", "")).strip():
            continue
        act = col(row, "active", True)
        active = act not in (False, "false", "FALSE", "0", "no", "No", "NO")
        coupons.append({
            "id": cid or ("cp-" + str(col(row, "code", "")).strip()),
            "title": str(col(row, "title", "")).strip(),
            "store": str(col(row, "store", "")).strip(),
            "code": str(col(row, "code", "")).strip(),
            "value": str(col(row, "value", "")).strip(),
            "description": str(col(row, "description", "")).strip(),
            "redirect_url": str(col(row, "redirect_url", "")).strip(),
            "expires_at": str(col(row, "expires_at", "")).strip(),
            "active": active,
            "is_example": bool(existing.get(cid, {}).get("is_example", False)),
        })
    cf.write_text(json.dumps({"coupons": coupons, "note": note},
                             ensure_ascii=False, indent=1), encoding="utf-8")
    log("coupons", f"synced {len(coupons)} coupons from {src.name}")


def sync_redirects_from_raw():
    """Convert the Sheet's «إعادة التوجيه» tab export into data/redirects.json
    (the file build.py reads to generate nginx redirects.conf).
    Raw source: data/raw/redirects.json (CLI path) or data/raw/إعادة التوجيه
    (Apps Script export path, which files exports by tab name).
    Columns: from, to, code (301/302), enabled. Only enabled rows are kept;
    duplicates keep the last occurrence; from == to rows are dropped."""
    src = None
    for cand in (RAW / "redirects.json", RAW / "إعادة التوجيه"):
        if cand.exists():
            src = cand
            break
    if src is None:
        return
    try:
        raw = json.loads(src.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        LOG["errors"].append(f"redirects raw parse: {e}")
        return
    values = raw.get("values", []) if isinstance(raw, dict) else raw
    if not isinstance(values, list) or len(values) < 2:
        return
    header = [str(h).strip() for h in values[0]]

    def col(row, name, default=""):
        try:
            i = header.index(name)
        except ValueError:
            return default
        return row[i] if i < len(row) else default

    by_from = {}
    for row in values[1:]:
        frm = str(col(row, "from", "")).strip()
        to = str(col(row, "to", "")).strip()
        if not frm or not to or frm == to:
            continue
        if not frm.startswith("/"):
            frm = "/" + frm
        try:
            code = int(str(col(row, "code", 301)).strip() or 301)
        except ValueError:
            code = 301
        code = 302 if code == 302 else 301
        act = col(row, "enabled", True)
        enabled = act not in (False, "false", "FALSE", "0", "no", "No", "NO")
        if not enabled:
            continue
        by_from[frm] = {"from": frm, "to": to, "code": code}
    redirects = [by_from[k] for k in sorted(by_from)]
    (DATA / "redirects.json").write_text(
        json.dumps({"redirects": redirects,
                    "note": "إعادة توجيه تُدار من لوحة التحكم (تبويب إعادة التوجيه في الشيت)."},
                   ensure_ascii=False, indent=1), encoding="utf-8")
    log("redirects", f"synced {len(redirects)} redirects from {src.name}")


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
                wm = WM.apply_to_product(im, "A")
                # cap at 600px (display size) + q82, matching the optimized set
                w, h = wm.size
                mx = max(w, h)
                if mx > 600:
                    sc = 600 / mx
                    wm = wm.resize((max(1, int(w * sc)), max(1, int(h * sc))),
                                   Image.LANCZOS)
                wm.save(target, quality=82, optimize=True)
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


def append_history_to_sheet(changes):
    """Append new price changes to the Sheet «سجل الأسعار» tab so the
    admin price-drop radar's 7/30-day windows fill over time.
    Best-effort only: needs hatch_gws_cli (absent on the VPS sync app —
    then it silently skips) and never raises into the sync. Only moves
    of >= 1% are appended, to keep noise (e.g. 0.04% rounding moves)
    out of the tab. Rows match the tab's 12 columns: date, name, model,
    storage, ram, store, seller, url, old, new, diff, pct (diff/pct
    signed: negative = drop)."""
    if not changes:
        return
    try:
        cli = pathlib.Path("/opt/hatch/bin/hatch_gws_cli")
        sheet_id = SETTINGS.get("sheet_id") or ""
        if not cli.exists() or not sheet_id:
            return
        rows = json.loads((RAW / "sheet1.json").read_text(encoding="utf-8"))["values"]
        header = [str(h).strip() for h in rows[0]]
        col = {name: i for i, name in enumerate(header)}
        by_url = {}
        for r in rows[1:]:
            if not any(str(c).strip() for c in r):
                continue
            by_url[r[col["رابط المنتج"]]] = r
        values = []
        for c in changes:
            diff, pct = SH.price_change(c["old"], c["new"])
            if abs(pct) < 1:
                continue
            r = by_url.get(c["url"])
            if not r:
                continue
            values.append([
                c["date"],
                r[col["اسم الموبايل"]], r[col["الموديل"]],
                r[col["التخزين"]], r[col["الرام"]],
                r[col["المتجر (جوميا / أمازون)"]], r[col["البائع"]],
                c["url"], c["old"], c["new"], diff, pct,
            ])
        if not values:
            return
        out = subprocess.run(
            [str(cli), "sheets", "spreadsheets", "values", "append",
             "--params", json.dumps(
                 {"spreadsheetId": sheet_id, "range": "سجل الأسعار",
                  "valueInputOption": "USER_ENTERED",
                  "insertDataOption": "INSERT_ROWS"}),
             "--json", json.dumps({"values": values})],
            capture_output=True, text=True, timeout=60)
        if out.returncode == 0:
            log("history-append", f"{len(values)} change(s) appended to سجل الأسعار")
        else:
            log("history-append", f"skipped (CLI error): {out.stderr[-300:]}")
    except Exception as e:  # noqa: BLE001 - best-effort, never break the sync
        log("history-append", f"skipped: {e}")


def refresh_daily_prices():
    """Refresh gold/USD daily prices when today's data is missing.

    Best-effort: scripts/daily-prices.py fetches live prices and writes
    data/daily-prices.json. On ANY failure the old file stays untouched
    (the pages show the last successful date — never a stale price under
    a new date). Never fails the sync."""
    try:
        r = subprocess.run([sys.executable, str(SCRIPTS / "daily-prices.py")],
                           capture_output=True, text=True, timeout=180)
        out = (r.stdout or "").strip()
        if out:
            log("daily-prices", out[-500:])
        if r.returncode != 0:
            log("daily-prices", "fetcher failed — keeping last good data")
    except Exception as e:  # noqa: BLE001 - best-effort by design
        log("daily-prices", "skipped: " + str(e))


def main():
    sys.path.insert(0, str(SCRIPTS))
    try:
        refresh_from_sheet()
        sync_coupons_from_raw()
        sync_redirects_from_raw()
        sync_guides_from_raw()
        sync_news_from_raw()
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
        append_history_to_sheet(changes)
        refresh_daily_prices()
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
