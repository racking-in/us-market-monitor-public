import json
import os
import sys
from datetime import datetime, time
from zoneinfo import ZoneInfo

from market_scan import analyze, atr, fetch, pct, rsi, sma

ET = ZoneInfo("America/New_York")
SGT = ZoneInfo("Asia/Singapore")

MARKET = ["SPY", "QQQ", "DIA", "IWM", "^VIX", "^TNX", "SOXX", "ES=F", "NQ=F"]

US_HOLIDAYS_2026 = {
    "2026-01-01",
    "2026-01-19",
    "2026-02-16",
    "2026-04-03",
    "2026-05-25",
    "2026-06-19",
    "2026-07-03",
    "2026-09-07",
    "2026-11-26",
    "2026-12-25",
}


def session_name(now_et):
    if now_et.weekday() >= 5:
        return "周末休市"
    d = now_et.date().isoformat()
    if d in US_HOLIDAYS_2026:
        return "美股假日休市"
    t = now_et.time()
    if time(4, 0) <= t < time(9, 30):
        return "盘前"
    if time(9, 30) <= t < time(16, 0):
        return "常规交易"
    if time(16, 0) <= t < time(20, 0):
        return "盘后"
    return "隔夜/休市"


def load_portfolio():
    raw = os.environ.get("PORTFOLIO_JSON")
    if raw:
        return json.loads(raw)
    path = os.path.join(os.path.dirname(__file__), "portfolio.json")
    if not os.path.exists(path):
        return {"nav_usd": None, "risk_per_trade_pct": 0.5, "max_positions": 2, "positions": []}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def fmt(v, digits=2):
    if v is None:
        return "-"
    return f"{v:,.{digits}f}"


def latest_price(x):
    value = x.get("extended_last")
    return value if value is not None else x["last"]


def analyze_symbol(symbol):
    meta, daily = fetch(symbol, "1d", "1y")
    item = analyze(symbol, daily, meta)
    try:
        _, intra = fetch(symbol, "60m", "5d", prepost=True)
        if intra:
            item["extended_last"] = intra[-1]["c"]
            item["extended_time_et"] = datetime.fromtimestamp(int(intra[-1]["t"]), ET).isoformat()
    except Exception:
        item["extended_last"] = None
        item["extended_time_et"] = None
    return item


def main():
    now_et = datetime.now(ET)
    now_sgt = datetime.now(SGT)
    session = session_name(now_et)
    portfolio = load_portfolio()
    symbols = list(MARKET)
    for p in portfolio.get("positions", []):
        s = p.get("symbol")
        if s and s not in symbols:
            symbols.append(s)
    for s in portfolio.get("watchlist", []):
        if s and s not in symbols:
            symbols.append(s)

    data = {}
    errors = []
    for s in symbols:
        try:
            data[s] = analyze_symbol(s)
        except Exception as exc:
            errors.append(f"{s}: {exc}")

    alerts = []
    if "^VIX" in data:
        vix = data["^VIX"]
        vix_last = latest_price(vix)
        if vix_last >= 22.31:
            alerts.append(f"VIX {fmt(vix_last)} 已到/超过 22.31（20日高），风险厌恶升温")
        elif vix_last <= 14.68:
            alerts.append(f"VIX {fmt(vix_last)} 已到/低于 14.68（20日低），市场偏自满")
    for s in ["SPY", "QQQ"]:
        if s in data:
            x = data[s]
            last = latest_price(x)
            if x.get("sma200") and last < x["sma200"]:
                alerts.append(f"{s} 跌破 SMA200 {fmt(x['sma200'])}，中期趋势转弱")
            if last <= x["lo20"]:
                alerts.append(f"{s} 触及/跌破 20 日低点 {fmt(x['lo20'])}")
            if last >= x["hi20"]:
                alerts.append(f"{s} 触及/突破 20 日高点 {fmt(x['hi20'])}")
    for s, x in data.items():
        if s in MARKET:
            continue
        last = latest_price(x)
        if last <= x["lo20"]:
            alerts.append(f"{s} 跌破 20 日低点 {fmt(x['lo20'])}")
        if last >= x["hi20"]:
            alerts.append(f"{s} 突破 20 日高点 {fmt(x['hi20'])}")

    lines = []
    lines.append("# 美股监控报告")
    lines.append("")
    lines.append(f"- 生成时间：{now_sgt.strftime('%Y-%m-%d %H:%M')} SGT / {now_et.strftime('%Y-%m-%d %H:%M')} ET")
    lines.append(f"- 市场时段：{session}")
    lines.append("- 行情源：Yahoo Finance chart API；最新价为最近可得价格（含盘前/盘后），可能延迟约 15 分钟，非 IBKR 实时报价")
    lines.append(f"- 账户净值：{fmt(portfolio.get('nav_usd')) if portfolio.get('nav_usd') else '未提供'}")
    lines.append("")

    lines.append("## 大盘")
    lines.append("")
    lines.append("| 标的 | 最新 | 1日% | SMA20 | SMA50 | SMA200 | ATR14 | RSI14 | 20日低 | 20日高 | 趋势 |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|")
    for s in MARKET:
        x = data.get(s)
        if not x:
            continue
        last = latest_price(x)
        chg = pct(last, x.get("prev_close")) if x.get("prev_close") else x["chg_1d_pct"]
        lines.append(
            f"| {s} | {fmt(last)} | {fmt(chg)} | {fmt(x['sma20'])} | "
            f"{fmt(x['sma50'])} | {fmt(x['sma200'])} | {fmt(x['atr14'])} | {fmt(x['rsi14'],1)} | "
            f"{fmt(x['lo20'])} | {fmt(x['hi20'])} | {x['trend']} |"
        )
    lines.append("")

    key_levels = []
    for s in ["SPY", "QQQ", "IWM", "SOXX"] + [p.get("symbol") for p in portfolio.get("positions", [])]:
        if s and s not in key_levels:
            key_levels.append(s)
    lines.append("## 均线与关键位")
    lines.append("")
    lines.append("| 标的 | 最新 | 3日均 | 5日均 | 20日均 | 周5 | 周10 | 周20 | 支撑 | 压力 | 周线趋势 |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|")
    for s in key_levels:
        x = data.get(s)
        if not x:
            continue
        last = latest_price(x)
        support = f"{fmt(x.get('support'))} {x.get('support_label') or ''}".strip()
        resistance = f"{fmt(x.get('resistance'))} {x.get('resistance_label') or ''}".strip()
        lines.append(
            f"| {s} | {fmt(last)} | {fmt(x.get('sma3'))} | {fmt(x.get('sma5'))} | {fmt(x.get('sma20'))} | "
            f"{fmt(x.get('weekly_sma5'))} | {fmt(x.get('weekly_sma10'))} | {fmt(x.get('weekly_sma20'))} | "
            f"{support} | {resistance} | {x.get('weekly_trend') or '-'} |"
        )
    lines.append("")

    watchlist = portfolio.get("watchlist", [])
    if watchlist:
        lines.append("## 自选观察")
        lines.append("")
        lines.append("| 代码 | 最新 | 1日% | SMA20 | SMA50 | RSI14 | 20日低 | 20日高 | 趋势 |")
        lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---|")
        for s in watchlist:
            x = data.get(s)
            if not x:
                continue
            last = latest_price(x)
            chg = pct(last, x.get("prev_close")) if x.get("prev_close") else x["chg_1d_pct"]
            lines.append(
                f"| {s} | {fmt(last)} | {fmt(chg)} | {fmt(x['sma20'])} | "
                f"{fmt(x['sma50'])} | {fmt(x['rsi14'],1)} | {fmt(x['lo20'])} | {fmt(x['hi20'])} | {x['trend']} |"
            )
        lines.append("")

    positions = portfolio.get("positions", [])
    if positions:
        lines.append("## 持仓")
        lines.append("")
        lines.append("| 代码 | 股数 | 成本 | 最新 | 盈亏% | 止损 | 止盈 | 距止损% | 建议股数(0.5%风险) |")
        lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|")
        nav = portfolio.get("nav_usd")
        risk_pct = float(portfolio.get("risk_per_trade_pct", 0.5))
        for p in positions:
            s = p.get("symbol")
            x = data.get(s)
            if not x:
                continue
            last = latest_price(x)
            shares = float(p.get("shares") or 0)
            cost = float(p.get("avg_cost") or 0)
            stop = p.get("stop")
            target = p.get("target")
            if stop is None:
                stop = last - 1.5 * x["atr14"] if x.get("atr14") else None
            if target is None:
                target = last + 2 * (last - stop) if stop else None
            pnl = pct(last, cost) if cost else None
            dist = pct(last, stop) if stop else None
            if nav and stop:
                size = int((float(nav) * risk_pct / 100) / max(last - stop, 0.01))
            else:
                size = None
            lines.append(
                f"| {s} | {shares:g} | {fmt(cost)} | {fmt(last)} | {fmt(pnl)} | {fmt(stop)} | "
                f"{fmt(target)} | {fmt(dist)} | {size if size is not None else '-'} |"
            )
            if stop and last <= stop * 1.005:
                alerts.append(f"{s} 已接近/跌破止损 {fmt(stop)}")
            if target and last >= target * 0.995:
                alerts.append(f"{s} 已接近/触及止盈 {fmt(target)}")
        lines.append("")
    else:
        lines.append("## 持仓")
        lines.append("")
        lines.append("尚未提供持仓。请在 work/portfolio.json 或 PORTFOLIO_JSON secret 中填入 positions；watchlist 数组可放自选代码。")
        lines.append("")

    if alerts:
        lines.append("## 触发提醒")
        for a in alerts:
            lines.append(f"- {a}")
        lines.append("")

    if errors:
        lines.append("## 数据错误")
        for e in errors:
            lines.append(f"- {e}")
        lines.append("")

    report = "\n".join(lines)
    out_path = os.path.join(os.path.dirname(__file__), "monitor_report.md")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(report)
    with open(os.path.join(os.path.dirname(__file__), "monitor_output.json"), "w", encoding="utf-8") as f:
        json.dump({"generated_sgt": now_sgt.isoformat(), "session": session, "alerts": alerts, "portfolio": portfolio, "data": data}, f, ensure_ascii=False, indent=2)
    print(report)
    if alerts:
        print("\nALERT_COUNT=" + str(len(alerts)))
    else:
        print("\nALERT_COUNT=0")


if __name__ == "__main__":
    main()
