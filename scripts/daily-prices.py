#!/usr/bin/env python3
"""Daily prices fetcher for 3rde.online (gold + USD).

Run: python3 scripts/daily-prices.py   (from the repo root)
Writes: data/daily-prices.json + data/daily-prices-history.json

FIXED SOURCES (one per topic — never mix sources between days):
  - gold: https://market.isagha.com/ (iSagha) — stable URL, buy/sell
    table per karat. Validated live 2026-11-25.
  - usd: https://api.exchangerate-api.com/v4/latest/USD — free, no key,
    market mid-rate. The Central Bank's own page rejects automated
    requests (HTTP 403 via curl + "Request Rejected" in the browser,
    2026-11-25), so the page labels this honestly as a market rate
    until CBE access opens up.

GOLDEN RULE: a failed fetch never writes a new date with old prices.
On failure the old file stays untouched and the pages show the last
successful date with a clear warning. History is appended only on
successful fetches. A topic already fresh today is skipped (the sync
loop runs sync.py up to 8 times per sync).
"""

import json
import re
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
DATA = BASE / "data"
CAIRO = timezone(timedelta(hours=2))
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
ISAGHA_URL = "https://market.isagha.com/"
USD_API_URL = "https://api.exchangerate-api.com/v4/latest/USD"


def fetch_text(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        if resp.status != 200:
            raise RuntimeError("HTTP " + str(resp.status))
        return resp.read().decode("utf-8", errors="ignore")


def parse_isagha(html):
    """Parse the iSagha board table: one <tr data-unit="24|21|18|pound">
    per unit, with board-buy / board-sell price figures inside."""
    out = {}
    for m in re.finditer(r'<tr[^>]*data-unit="([^"]+)"[^>]*>(.*?)</tr>',
                         html, re.S):
        unit, block = m.group(1), m.group(2)
        if unit not in ("24", "21", "18", "pound"):
            continue
        buy = re.search(r'board-buy.*?price-figure[^>]*>([\d,]+(?:\.\d+)?)<',
                        block, re.S)
        sell = re.search(r'board-sell.*?price-figure[^>]*>([\d,]+(?:\.\d+)?)<',
                         block, re.S)
        if not buy or not sell:
            continue
        out[unit] = {"buy": int(round(float(buy.group(1).replace(",", "")))),
                     "sell": int(round(float(sell.group(1).replace(",", ""))))}
    # validation: all three karats present, buy < sell, 24 > 21 > 18,
    # and the pound (when present) is ~21 x 8
    for u in ("24", "21", "18"):
        if u not in out:
            raise RuntimeError("iSagha: missing karat " + u)
        if out[u]["buy"] >= out[u]["sell"]:
            raise RuntimeError("iSagha: buy >= sell for " + u)
    if not (out["24"]["sell"] > out["21"]["sell"] > out["18"]["sell"]):
        raise RuntimeError("iSagha: karat order wrong")
    if "pound" in out:
        expect = out["21"]["sell"] * 8
        if abs(out["pound"]["sell"] - expect) > expect * 0.02:
            raise RuntimeError("iSagha: pound price inconsistent")
    return out


def fetch_gold():
    return parse_isagha(fetch_text(ISAGHA_URL))


def fetch_usd():
    d = json.loads(fetch_text(USD_API_URL))
    rate = float(d["rates"]["EGP"])
    if not 40 < rate < 70:
        raise RuntimeError("USD rate out of range: " + str(rate))
    return {"rate": round(rate, 2)}


def _load_json(name):
    p = DATA / name
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - corrupt file is treated as missing
        return None


def main():
    now = datetime.now(CAIRO)
    today = now.strftime("%Y-%m-%d")
    fetched_at = now.strftime("%Y-%m-%d %H:%M")
    data = _load_json("daily-prices.json") or {}
    topics = data.get("topics", {}) if isinstance(data, dict) else {}
    history = _load_json("daily-prices-history.json") or []
    if not isinstance(history, list):
        history = []
    ok = []
    fail = []
    if topics.get("gold", {}).get("date") == today:
        ok.append("gold (cached)")
    else:
        try:
            gold = fetch_gold()
            topics["gold"] = {"date": today, "fetched_at": fetched_at,
                              "source_name": "آي صاغة",
                              "source_url": ISAGHA_URL, "prices": gold}
            history.append({"topic": "gold", "date": today, "prices": gold})
            ok.append("gold")
        except Exception as e:  # noqa: BLE001 - keep last good data
            fail.append("gold: " + str(e))
    if topics.get("usd", {}).get("date") == today:
        ok.append("usd (cached)")
    else:
        try:
            usd = fetch_usd()
            topics["usd"] = {"date": today, "fetched_at": fetched_at,
                             "source_name": "سعر السوق العالمي (ExchangeRate-API)",
                             "source_url": USD_API_URL, "prices": usd}
            history.append({"topic": "usd", "date": today, "prices": usd})
            ok.append("usd")
        except Exception as e:  # noqa: BLE001 - keep last good data
            fail.append("usd: " + str(e))
    # dedupe history by (topic, date): keep the latest row per day
    seen = {}
    for row in history:
        seen[(row.get("topic"), row.get("date"))] = row
    history = [seen[k] for k in sorted(seen)]
    if ok and not all("(cached)" in o for o in ok):
        (DATA / "daily-prices.json").write_text(
            json.dumps({"topics": topics}, ensure_ascii=False, indent=1),
            encoding="utf-8")
        (DATA / "daily-prices-history.json").write_text(
            json.dumps(history, ensure_ascii=False, indent=1),
            encoding="utf-8")
    print("daily-prices: ok=" + ",".join(ok) +
          (" | fail=" + "; ".join(fail) if fail else ""))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
