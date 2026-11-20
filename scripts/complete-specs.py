#!/usr/bin/env python3
"""Complete missing specs in the Sheet (الورقة1) from Mobizil search/pages.

THE RULE: never overwrite a non-empty cell. Only empty cells are filled.
- Reads live rows from the Sheet (valueRenderOption=FORMULA).
- For each row with empty spec cells: find the Mobizil specs page
  (col 38 if set, else Mobizil site search), fetch + parse it, and fill
  ONLY the empty cells among cols 15-22, 31-33, 38-42 (+ stamp col 25).
- Writes back ONLY cols O:AP (15-42) of that row, from a fresh read.
  AU (46), price/store cols (0-14) and ratings are NEVER touched.
- Polite: ~2s between requests, --limit per run, resumable JSON log.

Usage:
  python3 scripts/complete-specs.py [--limit N] [--dry-run] [--row R]
    --limit N   max rows to process (default 25)
    --dry-run   report what WOULD be filled, write nothing
    --row R     process a single 1-based Sheet row (e.g. 1707)
"""
import argparse, json, re, subprocess, sys, time, unicodedata
from datetime import date
from urllib.parse import quote_plus
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

SHEET_ID = "1VeOXP8ly-W0dwT0QQK9kqf9z_834zok9ekIqGjfPNdE"
TAB = "الورقة1"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"}
SLEEP = 2.0
TODAY_SERIAL = (date.today() - date(1899, 12, 30)).days

# Sheet columns filled by this script (0-based index)
TARGETS = [15, 16, 17, 18, 19, 20, 22, 31, 32, 33, 38, 39, 40, 41, 42]
HEADERS = ["اسم الموبايل", "الاسم باللغة العربية", "الماركة", "الموديل",
           "رابط المنتج", "المتجر (جوميا / أمازون)", "البائع",
           "السعر الحالي (بعد الخصم) - جنيه", "السعر قبل الخصم - جنيه",
           "نسبة الخصم %", "التوفر", "التقييم", "عدد التقييمات", "التخزين",
           "الرام", "حجم الشاشة", "المعالج", "الكاميرا الخلفية",
           "الكاميرا الأمامية", "البطارية", "قدرة الشحن (واط)", "اللون",
           "نظام التشغيل", "الضمان", "الشحن / التوصيل", "تاريخ آخر تحديث",
           "ملاحظات", "مكرر؟", "رقم مجموعة التكرار",
           "ترتيب السعر داخل المجموعة", "رابط صورة المنتج", "دعم 5G",
           "عدد الشرائح", "سنة الإصدار", "كود المنتج في المتجر",
           "مصداقية الخصم", "فرق السعر بين أرخص وأغلى عرض - جنيه",
           "فرق السعر بين أرخص وأغلى عرض - %", "رابط صفحة موبيزل",
           "المواصفات الكاملة", "المميزات", "العيوب", "روابط صور إضافية",
           "تقييم موبيزل", "يوجد اختلاف بين مواصفات الشيت وموبيزل؟",
           "تفاصيل الاختلاف بين مواصفات الشيت وموبيزل", "رابط الأفلييت"]

# ---------------------------------------------------------------- sheets
def gws(*args):
    cmd = ["hatch_gws_cli"] + list(args)
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    if out.returncode != 0:
        raise RuntimeError(f"gws {' '.join(args[:4])} failed: {out.stderr[-500:]}")
    return json.loads(out.stdout)

def read_sheet():
    d = gws("sheets", "spreadsheets", "values", "get", "--params",
            json.dumps({"spreadsheetId": SHEET_ID, "range": f"{TAB}!A1:AV",
                        "valueRenderOption": "FORMULA"}))
    vals = d.get("values", [])
    return vals[0], vals[1:]

def read_row(sheet_row):
    d = gws("sheets", "spreadsheets", "values", "get", "--params",
            json.dumps({"spreadsheetId": SHEET_ID,
                        "range": f"{TAB}!A{sheet_row}:AV{sheet_row}",
                        "valueRenderOption": "FORMULA"}))
    vals = d.get("values", [])
    return vals[0] if vals else []

def col_letter(i):
    s = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s

def write_row(sheet_row, row_values, lo=14, hi=42):
    """Write cols lo..hi (0-based) of one row. row_values is the FULL row
    list (fresh read); only the slice is sent."""
    rng = f"{TAB}!{col_letter(lo)}{sheet_row}:{col_letter(hi)}{sheet_row}"
    vals = [(row_values[i] if i < len(row_values) else "") for i in range(lo, hi + 1)]
    gws("sheets", "spreadsheets", "values", "update", "--params",
        json.dumps({"spreadsheetId": SHEET_ID, "range": rng,
                    "valueInputOption": "RAW"}),
        "--json", json.dumps({"values": [vals]}))

# ---------------------------------------------------------------- fetch
def fetch(url, timeout=30):
    req = Request(url, headers=UA)
    with urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="ignore")

def strip_tags(s):
    s = re.sub(r"<[^>]+>", " ", s)
    s = s.replace("&nbsp;", " ").replace("&#8211;", "-").replace("&amp;", "&")
    return re.sub(r"\s+", " ", s).strip()

# ---------------------------------------------------------------- mobizil
def norm_tokens(s):
    s = unicodedata.normalize("NFKD", str(s or "").lower())
    s = re.sub(r"[^a-z0-9\u0600-\u06ff]+", " ", s)
    return [t for t in s.split() if t]

VARIANT_WORDS = {"pro", "max", "ultra", "plus", "lite", "fe", "mini", "x"}
# NOTE: 4g/5g are NOT variant words — a 4G-only model's Mobizil slug
# legitimately carries "-4g" (e.g. infinix-smart-20-4g-specs).

def mobizil_search(query):
    html = fetch(f"https://mobizil.com/?s={quote_plus(query)}")
    links = re.findall(r'href="(https://mobizil\.com/[^"]+-specs/)"', html)
    seen, out = set(), []
    for l in links:
        if l not in seen:
            seen.add(l)
            out.append(l)
    return out

def pick_mobizil_url(brand, model, candidates):
    """Pick the candidate whose slug matches brand+model exactly.
    Reject variants (Pro/Lite/Max/...) that the Sheet model does not have."""
    model_toks = [t for t in norm_tokens(model)]
    brand_toks = [t for t in norm_tokens(brand)]
    want = brand_toks + model_toks
    best, best_score = None, float("-inf")
    for url in candidates:
        slug = re.sub(r"^https://mobizil\.com/|\-specs/$", "", url)
        slug_toks = norm_tokens(slug.replace("-", " "))
        if not all(t in slug_toks for t in want):
            continue
        # extra variant words in the slug that the model lacks -> reject
        extra = [t for t in slug_toks if t not in want and t in VARIANT_WORDS]
        if extra:
            continue
        # prefer the shortest (most exact) slug
        score = -len(slug_toks)
        if score > best_score:
            best, best_score = url, score
    return best

def parse_mobizil(html):
    """Return dict of parsed spec fields from a Mobizil specs page.
    Specs are kept PER GROUP (labels repeat across groups, e.g. 'النوع')."""
    out = {}
    # features list: <strong>LABEL</strong>: <span>VALUE</span>
    m = re.search(r'aps-features-list">(.*?)</ul>', html, re.S)
    feats = {}
    if m:
        for k, v in re.findall(r"<strong>(.*?)</strong>:\s*<span>(.*?)</span>", m.group(1), re.S):
            feats[strip_tags(k)] = strip_tags(v)
    out["features"] = feats
    # spec groups: <div class="aps-group"><h3 ...>GROUP</h3><ul ...> rows
    groups = {}
    for gm in re.finditer(
            r'<div class="aps-group">\s*<h3[^>]*>([^<]+).*?<ul class="aps-specs-list">(.*?)</ul>',
            html, re.S):
        gname = strip_tags(gm.group(1))
        rows = {}
        for k, v in re.findall(
                r'<strong class="aps-term[^"]*">(.*?)</strong>.*?<span class="aps-1co">(.*?)</span>',
                gm.group(2), re.S):
            k = strip_tags(k)
            if "aps-icon-check" in v:
                val = "YES"
            elif "aps-icon-cancel" in v or "aps-icon-cross" in v:
                val = "NO"
            else:
                val = strip_tags(v)
            if k and val:
                rows[k] = val
        if rows:
            groups[gname] = rows
    out["groups"] = groups
    # flat fallback (last group wins — only for legacy lookups)
    flat = {}
    for g in groups.values():
        flat.update(g)
    out["specs"] = flat
    # announced date -> year
    ann = groups.get("معلومات عامة", {}).get("أعلن عنه", "")
    ym = re.search(r"(20\d\d)", ann)
    out["year"] = int(ym.group(1)) if ym else None
    # pros / cons: <h4 ...>مميزات ... :-</h4> then <ul class="bs-shortcode-list ...">
    for label, key in (("مميزات", "pros"), ("عيوب", "cons")):
        items = []
        mm = re.search(r"<h4[^>]*>[^<]*" + label + r"[^<]*</h4>\s*<ul[^>]*>(.*?)</ul>", html, re.S)
        if mm:
            for li in re.findall(r"<li>(.*?)</li>", mm.group(1), re.S):
                t = strip_tags(li)
                if t:
                    items.append(t)
        out[key] = items
    # gallery images (Mobizil uploads)
    imgs = re.findall(r"https://cdn\.shortpixel\.ai/spai/[^\"'\s]+\.jpg", html)
    imgs += re.findall(r"https://mobizil\.com/wp-content/uploads/[^\"'\s]+\.jpg", html)
    seen, uniq = set(), []
    for u in imgs:
        if u not in seen:
            seen.add(u)
            uniq.append(u)
    out["images"] = uniq[:5]
    # page model name (معلومات عامة -> موديل الموبايل)
    out["page_model"] = groups.get("معلومات عامة", {}).get("موديل الموبايل", "")
    return out

# ---------------------------------------------------------------- mapping
def norm_cpu(v):
    v = (v or "").strip()
    if not v:
        return ""
    # strip core-count prefix ("ثماني النواة ...") and normalize the process node
    v = re.sub(r"^(?:ثماني|عشاري|سداسي|رباعي)\s+(?:النواة|الانوية)\s+", "", v)
    v = re.sub(r"\s*بتكنولوجيا\s+(\d+)\s*نانو", r" (\1 نانو)", v)
    if re.search(r"Snapdragon", v, re.I) and not re.search(r"Qualcomm|كوالكوم", v, re.I):
        v = "Qualcomm " + v
    elif re.search(r"Dimensity", v, re.I) and not re.search(r"MediaTek|ميدياتك", v, re.I):
        v = "MediaTek " + v
    elif re.search(r"Exynos", v, re.I) and not re.search(r"Samsung|سامسونج", v, re.I):
        v = "Samsung " + v
    elif re.search(r"Tensor", v, re.I) and not re.search(r"Google|جوجل", v, re.I):
        v = "Google " + v
    return v

def norm_battery(v):
    v = (v or "").strip()
    m = re.search(r"(\d[\d,]*)\s*(?:مللي أمبير|mAh|مللي امبير)", v, re.I)
    if m:
        return f"{m.group(1).replace(',', '')} mAh"
    return v

def norm_screen(groups, feats):
    scr = groups.get("الشاشة", {})
    stype = scr.get("نوع الشاشة", "") or scr.get("النوع", "")
    size = scr.get("المقاس", "") or scr.get("الحجم", "")
    res = scr.get("الدقة", "")
    refresh = scr.get("خصائص أخري", "") or scr.get("معدل التحديث", "")
    if size or res:
        parts = []
        if stype:
            parts.append(stype)
        if size:
            parts.append(size if "بوصة" in size else size + " بوصة")
        if res:
            parts.append(res.replace("x", "×").replace(" بكسل", ""))
        txt = " ".join(parts)
        if refresh and ("Hz" in refresh or "هرتز" in refresh):
            txt += "، " + refresh
        return txt
    return feats.get("الشاشة", "")

def parse_watts(v):
    v = (v or "").strip()
    if not v or re.search(r"لا يدعم|غير مدعوم|No", v, re.I):
        return None
    m = re.search(r"(\d+)\s*واط", v)
    if m:
        return int(m.group(1))
    m = re.search(r"(\d+)\s*W\b", v, re.I)
    return int(m.group(1)) if m else None

def norm_os(v):
    v = (v or "").strip()
    v = re.sub(r"[اأإآ]ندرويد", "Android", v)
    return v

def split_camera(feats):
    """Features 'الكاميرا' value like 'خلفية مزدوجة 50+2 م.ب. / امامية 8 م.ب.'"""
    v = feats.get("الكاميرا", "")
    if "/" in v:
        a, b = v.split("/", 1)
        return a.strip(), b.strip()
    return v, ""

def build_fills(row, parsed, mob_url):
    """Return {col_index: value} for EMPTY cells only."""
    groups, feats = parsed["groups"], parsed["features"]
    hw = groups.get("هارد وير", {})
    cam = groups.get("الكاميرا", {})
    bat = groups.get("البطارية", {})
    sw = groups.get("سوفت وير", {})
    net = groups.get("الشبكة", {})

    def empty(i):
        return i >= len(row) or not str(row[i]).strip()
    fills = {}
    screen = norm_screen(groups, feats)
    cpu = norm_cpu(hw.get("المعالج", "") or feats.get("المعالج", ""))
    rear = cam.get("الكاميرا الخلفية", "") or cam.get("الكاميرا الرئيسية", "")
    front = cam.get("الكاميرا الأمامية", "") or cam.get("كاميرا السيلفي", "")
    if not rear or not front:
        fr, ff = split_camera(feats)
        rear = rear or fr
        front = front or ff
    batt = norm_battery(bat.get("السعة", "") or feats.get("البطارية", ""))
    watts = parse_watts(bat.get("قوة الشاحن", "") or bat.get("الشحن", "")
                        or bat.get("سرعة الشحن", ""))
    os_v = norm_os(sw.get("نظام التشغيل", "") or feats.get("نظام التشغيل", ""))
    g5 = net.get("شبكة 5G", "")
    g5v = "نعم" if g5 == "YES" else ("لا" if g5 == "NO" else "")
    sim = net.get("ثنائي الشريحة", "")
    simv = 2 if sim == "YES" else (1 if sim == "NO" else None)
    year = parsed.get("year")
    cands = {15: screen, 16: cpu, 17: rear, 18: front, 19: batt, 20: watts,
             22: os_v, 31: g5v, 32: simv, 33: year, 38: mob_url}
    for i, v in cands.items():
        if v in (None, ""):
            continue
        if empty(i):
            fills[i] = v
    # full specs paragraph (col 39) composed from parsed values
    if empty(39):
        parts = []
        if cpu:
            parts.append(f"المعالج {cpu}")
        stor = (row[13] if len(row) > 13 else "") or ""
        ram = (row[14] if len(row) > 14 else "") or ""
        if stor or ram:
            parts.append(f"التخزين/الرام {stor} مع {ram} رام")
        if rear:
            parts.append(f"الكاميرا الخلفية {rear}" + (f" والأمامية {front}" if front else ""))
        if screen:
            parts.append(f"الشاشة {screen}")
        if os_v:
            parts.append(f"نظام التشغيل {os_v}")
        if batt:
            parts.append(f"البطارية {batt}" + (f" مع شحن سريع {watts} واط" if watts else ""))
        if parts:
            fills[39] = "؛ ".join(parts) + "."
    if empty(40) and parsed.get("pros"):
        fills[40] = "؛ ".join(parsed["pros"][:5])
    if empty(41) and parsed.get("cons"):
        fills[41] = "؛ ".join(parsed["cons"][:5])
    if empty(42) and parsed.get("images"):
        fills[42] = "؛ ".join(parsed["images"])
    return fills

def model_matches(page_model, brand, model):
    """Verify the fetched page is really the Sheet model (token overlap)."""
    pm = norm_tokens(page_model)
    want = norm_tokens(brand) + norm_tokens(model)
    if not pm or not want:
        return False
    hit = sum(1 for t in want if t in pm)
    return hit / len(want) >= 0.8

# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=25)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--row", type=int, default=0, help="1-based Sheet row")
    args = ap.parse_args()

    header, rows = read_sheet()
    print(f"sheet rows: {len(rows)} (header: {header[0]}...)")
    log = {"started": time.strftime("%Y-%m-%d %H:%M"), "rows": []}
    page_cache = {}  # (brand, model) -> (mob_url, parsed) — many rows share a model
    done = 0
    todo = []
    for idx, r in enumerate(rows):
        sheet_row = idx + 2
        if args.row and sheet_row != args.row:
            continue
        if any((i >= len(r) or not str(r[i]).strip()) for i in TARGETS):
            todo.append((sheet_row, r))
    print(f"rows with gaps: {len(todo)}")
    for sheet_row, r in todo[: args.limit]:
        brand = r[2] if len(r) > 2 else ""
        model = r[3] if len(r) > 3 else ""
        name = f"{brand} {model}".strip()
        entry = {"row": sheet_row, "model": name}
        mob_url = (r[38] if len(r) > 38 else "") or ""
        try:
            cache_key = (brand, model, mob_url)
            if cache_key in page_cache:
                mob_url, parsed = page_cache[cache_key]
            else:
                if not mob_url:
                    cands = mobizil_search(f"{brand} {model}")
                    time.sleep(SLEEP)
                    mob_url = pick_mobizil_url(brand, model, cands) or ""
                    if not mob_url:
                        entry["status"] = "no-source"
                        entry["searched"] = len(cands)
                        entry["candidates"] = cands[:10]
                        log["rows"].append(entry)
                        print(f"[{sheet_row}] {name}: NO Mobizil page found ({len(cands)} candidates)")
                        continue
                html = fetch(mob_url)
                time.sleep(SLEEP)
                parsed = parse_mobizil(html)
                if parsed.get("page_model") and not model_matches(parsed["page_model"], brand, model):
                    entry["status"] = "model-mismatch"
                    entry["url"] = mob_url
                    entry["page_model"] = parsed["page_model"]
                    log["rows"].append(entry)
                    print(f"[{sheet_row}] {name}: MISMATCH page model '{parsed['page_model']}' — skipped")
                    continue
                page_cache[cache_key] = (mob_url, parsed)
            fills = build_fills(r, parsed, mob_url)
            entry["url"] = mob_url
            entry["fills"] = {HEADERS[i]: v for i, v in sorted(fills.items())}
            if not fills:
                entry["status"] = "nothing-new"
                print(f"[{sheet_row}] {name}: page OK, nothing to fill")
            elif args.dry_run:
                entry["status"] = "dry-run"
                print(f"[{sheet_row}] {name}: WOULD fill {list(entry['fills'])}")
            else:
                # fresh re-read, apply fills, write cols O:AP (14..42)
                fresh = read_row(sheet_row)
                new_row = list(fresh) + [""] * max(0, 43 - len(fresh))
                for i, v in fills.items():
                    if i < len(new_row) and str(new_row[i]).strip():
                        raise RuntimeError(f"SAFETY: cell {sheet_row} col {i} became non-empty — abort row")
                    new_row[i] = v
                new_row[25] = TODAY_SERIAL  # stamp last-update (col Z, inside range)
                write_row(sheet_row, new_row, lo=14, hi=42)
                # verify
                back = read_row(sheet_row)
                ok = all((str(back[i]).strip() == str(v).strip()) if i < len(back) else False
                         for i, v in fills.items())
                entry["status"] = "written" if ok else "VERIFY-FAILED"
                print(f"[{sheet_row}] {name}: wrote {len(fills)} cells -> {entry['status']}")
                done += 1
            log["rows"].append(entry)
        except Exception as e:
            entry["status"] = "error"
            entry["error"] = str(e)[:200]
            log["rows"].append(entry)
            print(f"[{sheet_row}] {name}: ERROR {e}")
    log["done"] = done
    with open("/home/hatch/workspace/3rode-online/data/complete-specs-log.json", "w", encoding="utf-8") as f:
        json.dump(log, f, ensure_ascii=False, indent=1)
    print(f"done: {done} rows written; log: data/complete-specs-log.json")

if __name__ == "__main__":
    main()
