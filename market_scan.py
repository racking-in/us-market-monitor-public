import json
import math
import sys
import time
from datetime import datetime
from urllib.parse import quote
from zoneinfo import ZoneInfo

import requests

ET = ZoneInfo("America/New_York")
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}


def fetch(symbol, interval="1d", range_="1y", prepost=False):
    url = (
        "https://query1.finance.yahoo.com/v8/finance/chart/"
        + quote(symbol, safe="")
        + f"?interval={interval}&range={range_}"
    )
    if prepost:
        url += "&includePrePost=true"
    resp = requests.get(url, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    data = resp.json()["chart"]["result"][0]
    ts = data.get("timestamp") or []
    q = data["indicators"]["quote"][0]
    rows = []
    for i, t in enumerate(ts):
        o, h, l, c, v = (q[k][i] for k in ("open", "high", "low", "close", "volume"))
        if None in (o, h, l, c):
            continue
        rows.append({"t": t, "o": o, "h": h, "l": l, "c": c, "v": v or 0})
    return data["meta"], rows


def sma(values, n):
    if len(values) < n:
        return None
    return sum(values[-n:]) / n


def rsi(values, n=14):
    if len(values) <= n:
        return None
    gains, losses = [], []
    for i in range(-n, 0):
        diff = values[i] - values[i - 1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))
    ag, al = sum(gains) / n, sum(losses) / n
    if al == 0:
        return 100.0
    return 100 - 100 / (1 + ag / al)


def atr(rows, n=14):
    trs = []
    for i in range(1, len(rows)):
        h, l, pc = rows[i]["h"], rows[i]["l"], rows[i - 1]["c"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    if len(trs) < n:
        return None
    return sum(trs[-n:]) / n


def pct(a, b):
    if not b:
        return None
    return (a / b - 1) * 100


def weekly_closes(rows):
    buckets = {}
    order = []
    for r in rows:
        dt = datetime.fromtimestamp(int(r["t"]), ET)
        key = tuple(dt.isocalendar()[:2])
        if key not in buckets:
            buckets[key] = []
            order.append(key)
        buckets[key].append(r)
    out = []
    for key in order:
        group = buckets[key]
        out.append({
            "t": group[-1]["t"],
            "c": group[-1]["c"],
            "h": max(x["h"] for x in group),
            "l": min(x["l"] for x in group),
        })
    return out


def swing_points(rows, lookback=80, order=2):
    recent = rows[-lookback:]
    highs, lows = [], []
    for i in range(order, len(recent) - order):
        h, l = recent[i]["h"], recent[i]["l"]
        if all(h >= recent[j]["h"] for j in range(i - order, i + order + 1) if j != i):
            highs.append(h)
        if all(l <= recent[j]["l"] for j in range(i - order, i + order + 1) if j != i):
            lows.append(l)
    return highs, lows


def support_resistance(rows, last, smas, weekly_smas):
    candidates = []
    for label, value in smas.items():
        if value:
            candidates.append((value, label))
    for label, value in weekly_smas.items():
        if value:
            candidates.append((value, label))
    candidates.append((max(r["h"] for r in rows[-20:]), "20日高"))
    candidates.append((min(r["l"] for r in rows[-20:]), "20日低"))
    candidates.append((max(r["h"] for r in rows[-50:]), "50日高"))
    candidates.append((min(r["l"] for r in rows[-50:]), "50日低"))
    swing_highs, swing_lows = swing_points(rows)
    for value in swing_highs[-5:]:
        if value >= last:
            candidates.append((value, "前高"))
    for value in swing_lows[-5:]:
        if value <= last:
            candidates.append((value, "前低"))
    prev = rows[-2] if len(rows) > 1 else rows[-1]
    pivot = (prev["h"] + prev["l"] + prev["c"]) / 3
    candidates.extend([
        (pivot, "Pivot P"),
        (2 * pivot - prev["h"], "Pivot S1"),
        (2 * pivot - prev["l"], "Pivot R1"),
    ])
    dedup = {}
    for value, label in candidates:
        if value is None:
            continue
        key = round(value, 2)
        if key not in dedup:
            dedup[key] = label
    below = [(v, l) for v, l in dedup.items() if v < last]
    above = [(v, l) for v, l in dedup.items() if v > last]
    support = max(below) if below else (min(dedup.items()) if dedup else (None, ""))
    resistance = min(above) if above else (max(dedup.items()) if dedup else (None, ""))
    return support, resistance, pivot


def analyze(symbol, daily_rows, meta, intraday_rows=None):
    closes = [r["c"] for r in daily_rows]
    last = closes[-1]
    prev = closes[-2] if len(closes) > 1 else None
    s3, s5, s10 = sma(closes, 3), sma(closes, 5), sma(closes, 10)
    s20, s50, s200 = sma(closes, 20), sma(closes, 50), sma(closes, 200)
    weekly = weekly_closes(daily_rows)
    weekly_closes_list = [x["c"] for x in weekly]
    w5, w10, w20 = sma(weekly_closes_list, 5), sma(weekly_closes_list, 10), sma(weekly_closes_list, 20)
    if w5 and w10 and w20:
        if weekly_closes_list[-1] > w5 > w10 > w20:
            weekly_trend = "周线强上升"
        elif weekly_closes_list[-1] < w5 < w10 < w20:
            weekly_trend = "周线下降"
        else:
            weekly_trend = "周线震荡"
    else:
        weekly_trend = "周线数据不足"
    support, resistance, pivot = support_resistance(
        daily_rows,
        last,
        {"SMA3": s3, "SMA5": s5, "SMA10": s10, "SMA20": s20, "SMA50": s50, "SMA200": s200},
        {"周SMA5": w5, "周SMA10": w10, "周SMA20": w20},
    )
    a14 = atr(daily_rows, 14)
    r14 = rsi(closes, 14)
    hi20 = max(r["h"] for r in daily_rows[-20:])
    lo20 = min(r["l"] for r in daily_rows[-20:])
    hi52 = max(r["h"] for r in daily_rows[-252:])
    lo52 = min(r["l"] for r in daily_rows[-252:])
    vol_avg = sum(r["v"] for r in daily_rows[-21:-1]) / 20 if len(daily_rows) >= 21 else None
    vol_ratio = daily_rows[-1]["v"] / vol_avg if vol_avg else None
    if s20 and s50 and s200:
        if last > s20 > s50 > s200:
            trend = "强上升"
        elif last > s20 and s20 > s50:
            trend = "上升"
        elif last < s20 < s50 < s200:
            trend = "强下降"
        elif last < s20 and s20 < s50:
            trend = "下降"
        else:
            trend = "震荡/转换"
    else:
        trend = "数据不足"
    intraday = None
    if intraday_rows:
        intraday = {
            "last": intraday_rows[-1]["c"],
            "last_time_et": datetime.fromtimestamp(intraday_rows[-1]["t"], ET).isoformat(),
        }
    return {
        "symbol": symbol,
        "name": meta.get("shortName") or meta.get("longName") or symbol,
        "last": last,
        "prev_close": prev,
        "chg_1d_pct": pct(last, prev),
        "chg_5d_pct": pct(last, closes[-6]) if len(closes) > 6 else None,
        "chg_20d_pct": pct(last, closes[-21]) if len(closes) > 21 else None,
        "sma20": s20,
        "sma50": s50,
        "sma200": s200,
        "sma3": s3,
        "sma5": s5,
        "sma10": s10,
        "weekly_last": weekly_closes_list[-1] if weekly_closes_list else None,
        "weekly_sma5": w5,
        "weekly_sma10": w10,
        "weekly_sma20": w20,
        "weekly_trend": weekly_trend,
        "support": support[0],
        "support_label": support[1],
        "resistance": resistance[0],
        "resistance_label": resistance[1],
        "pivot": pivot,
        "pivot_s1": 2 * pivot - daily_rows[-2]["h"] if len(daily_rows) > 1 else None,
        "pivot_r1": 2 * pivot - daily_rows[-2]["l"] if len(daily_rows) > 1 else None,
        "atr14": a14,
        "atr_pct": (a14 / last * 100) if a14 else None,
        "rsi14": r14,
        "hi20": hi20,
        "lo20": lo20,
        "hi52": hi52,
        "lo52": lo52,
        "from_hi20_pct": pct(last, hi20),
        "vol_ratio": vol_ratio,
        "trend": trend,
        "intraday": intraday,
        "last_bar_et": datetime.fromtimestamp(int(daily_rows[-1]["t"]), ET).isoformat(),
    }


SYMBOLS = [
    ("SPY", "1d", "1y"),
    ("QQQ", "1d", "1y"),
    ("DIA", "1d", "1y"),
    ("IWM", "1d", "1y"),
    ("^VIX", "1d", "1y"),
    ("^TNX", "1d", "1y"),
    ("SOXX", "1d", "1y"),
    ("ES=F", "60m", "5d"),
    ("NQ=F", "60m", "5d"),
    ("YM=F", "60m", "5d"),
    ("RTY=F", "60m", "5d"),
    ("DX-Y.NYB", "1d", "1y"),
    ("CL=F", "1d", "1y"),
    ("GC=F", "1d", "1y"),
]


def main():
    out = []
    for sym, interval, rng in SYMBOLS:
        try:
            meta, rows = fetch(sym, interval, rng)
            # For futures, daily bars are needed for indicators; fetch them too.
            if interval != "1d":
                _, daily = fetch(sym, "1d", "1y")
                item = analyze(sym, daily, meta, rows)
                item["intraday_last"] = rows[-1]["c"]
                item["intraday_time_et"] = datetime.fromtimestamp(int(rows[-1]["t"]), ET).isoformat()
            else:
                item = analyze(sym, rows, meta)
            out.append(item)
        except Exception as exc:
            out.append({"symbol": sym, "error": str(exc)})
        time.sleep(0.3)

    with open("work/market_scan.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print("symbol | last | 1d% | 5d% | 20d% | SMA20 | SMA50 | SMA200 | ATR14 | RSI14 | 20dHi | 20dLo | volX | trend")
    for x in out:
        if "error" in x:
            print(f"{x['symbol']} | ERROR: {x['error']}")
            continue
        def f(v, d=2):
            return "-" if v is None else f"{v:,.{d}f}"
        print(
            f"{x['symbol']} | {f(x['last'])} | {f(x['chg_1d_pct'])} | {f(x['chg_5d_pct'])} | "
            f"{f(x['chg_20d_pct'])} | {f(x['sma20'])} | {f(x['sma50'])} | {f(x['sma200'])} | "
            f"{f(x['atr14'])} | {f(x['rsi14'],1)} | {f(x['hi20'])} | {f(x['lo20'])} | "
            f"{f(x['vol_ratio'],1)} | {x['trend']}"
        )
        if x.get("intraday_last"):
            print(f"   intraday {f(x['intraday_last'])} at {x['intraday_time_et']}")


if __name__ == "__main__":
    main()
