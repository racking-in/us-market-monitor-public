import base64
import html as html_lib
import io
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter

from market_scan import fetch, sma, weekly_closes

ET = ZoneInfo("America/New_York")
SGT = ZoneInfo("Asia/Singapore")

UP = "#dc2626"
DOWN = "#16a34a"
INK = "#0f172a"
MUTED = "#64748b"
BORDER = "#e2e8f0"
BLUE = "#2563eb"
AMBER = "#d97706"
PURPLE = "#7c3aed"
SLATE = "#64748b"
SUPPORT = "#0ea5e9"
RESIST = "#f97316"

ROW_CACHE = {}


def get_rows(symbol):
    if symbol not in ROW_CACHE:
        _, rows = fetch(symbol, "1d", "1y")
        ROW_CACHE[symbol] = rows
    return ROW_CACHE[symbol]


def rolling(values, n):
    out = [None] * len(values)
    for i in range(n - 1, len(values)):
        out[i] = sum(values[i - n + 1 : i + 1]) / n
    return out


def fmt(value, digits=2):
    if value is None:
        return "-"
    return f"{value:,.{digits}f}"


def money(value):
    if value is None:
        return "-"
    return f"{value:,.2f}"


def pct_color(value):
    if value is None:
        return MUTED
    return UP if value >= 0 else DOWN


def latest_price(item):
    value = item.get("extended_last")
    return value if value is not None else item["last"]


def chart_daily(ax, symbol, rows, info, position=None, lookback=140):
    subset = rows[-lookback:]
    closes = [r["c"] for r in subset]
    dates = [datetime.fromtimestamp(int(r["t"]), ET) for r in subset]
    full_closes = [r["c"] for r in rows]
    s3 = rolling(full_closes, 3)[-len(subset):]
    s5 = rolling(full_closes, 5)[-len(subset):]
    s20 = rolling(full_closes, 20)[-len(subset):]
    s50 = rolling(full_closes, 50)[-len(subset):]

    ax.plot(dates, closes, color=INK, linewidth=1.4, label="Close")
    ax.plot(dates, s3, color=AMBER, linewidth=1.0, label="SMA3")
    ax.plot(dates, s5, color=BLUE, linewidth=1.0, label="SMA5")
    ax.plot(dates, s20, color=PURPLE, linewidth=1.0, label="SMA20")
    ax.plot(dates, s50, color=SLATE, linewidth=1.0, label="SMA50")

    if info.get("support"):
        ax.axhline(info["support"], color=SUPPORT, linewidth=0.9, linestyle="--")
    if info.get("resistance"):
        ax.axhline(info["resistance"], color=RESIST, linewidth=0.9, linestyle="--")

    if position:
        cost = position.get("avg_cost")
        stop = position.get("stop")
        target = position.get("target")
        if cost:
            ax.axhline(cost, color=INK, linewidth=0.8, linestyle=":")
        if stop:
            ax.axhline(stop, color=DOWN, linewidth=0.8, linestyle=":")
        if target:
            ax.axhline(target, color=UP, linewidth=0.8, linestyle=":")

    last = latest_price(info)
    chg = ((last / info["prev_close"] - 1) * 100) if info.get("prev_close") else info.get("chg_1d_pct")
    title = f"{symbol}  {last:.2f}  {chg:+.2f}%" if chg is not None else f"{symbol}  {last:.2f}"
    ax.set_title(title, loc="left", fontsize=9, fontweight="bold", color=INK)
    ax.grid(True, color="#e2e8f0", linewidth=0.5, alpha=0.7)
    ax.tick_params(labelsize=6, colors=MUTED)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d"))
    ax.xaxis.set_major_locator(mdates.AutoDateLocator(maxticks=6))
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, p: f"{v:,.0f}" if abs(v) >= 100 else f"{v:,.2f}"))
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    ax.spines["left"].set_color(BORDER)
    ax.spines["bottom"].set_color(BORDER)
    ax.legend(loc="best", fontsize=5, ncol=5, frameon=False, handlelength=1.4)


def chart_weekly(ax, symbol, rows, info):
    weeks = weekly_closes(rows)[-104:]
    closes = [x["c"] for x in weeks]
    dates = [datetime.fromtimestamp(int(x["t"]), ET) for x in weeks]
    w5 = rolling(closes, 5)
    w10 = rolling(closes, 10)
    w20 = rolling(closes, 20)
    ax.plot(dates, closes, color=INK, linewidth=1.4, label="Weekly close")
    ax.plot(dates, w5, color=AMBER, linewidth=1.0, label="SMA5W")
    ax.plot(dates, w10, color=BLUE, linewidth=1.0, label="SMA10W")
    ax.plot(dates, w20, color=PURPLE, linewidth=1.0, label="SMA20W")
    ax.set_title(f"{symbol} Weekly  {closes[-1]:.2f}", loc="left", fontsize=9, fontweight="bold", color=INK)
    ax.grid(True, color="#e2e8f0", linewidth=0.5, alpha=0.7)
    ax.tick_params(labelsize=6, colors=MUTED)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%y-%m"))
    ax.xaxis.set_major_locator(mdates.AutoDateLocator(maxticks=6))
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, p: f"{v:,.0f}" if abs(v) >= 100 else f"{v:,.2f}"))
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    ax.spines["left"].set_color(BORDER)
    ax.spines["bottom"].set_color(BORDER)
    ax.legend(loc="best", fontsize=5, ncol=3, frameon=False, handlelength=1.4)


def to_png(fig):
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=125, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return buf.getvalue()


def chart_market(data):
    symbols = [s for s in ("SPY", "QQQ", "IWM", "SOXX") if s in data]
    if not symbols:
        return None
    fig, axes = plt.subplots(2, 2, figsize=(12, 7.2), dpi=120)
    for ax, symbol in zip(axes.flat, symbols):
        chart_daily(ax, symbol, get_rows(symbol), data[symbol])
    for ax in axes.flat[len(symbols):]:
        ax.axis("off")
    fig.suptitle("Market dashboard - daily close, SMA3/5/20/50, support and resistance", x=0.01, ha="left", fontsize=11, color=INK)
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    return to_png(fig)


def chart_holdings(portfolio, data):
    positions = [p for p in portfolio.get("positions", []) if p.get("symbol") in data]
    if not positions:
        return None
    fig, axes = plt.subplots(len(positions), 1, figsize=(12, 3.8 * len(positions)), dpi=120, squeeze=False)
    for ax, position in zip(axes.flat, positions):
        symbol = position["symbol"]
        chart_daily(ax, symbol, get_rows(symbol), data[symbol], position=position, lookback=180)
    fig.suptitle("Holdings - close, cost, stop, target and moving averages", x=0.01, ha="left", fontsize=11, color=INK)
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    return to_png(fig)


def chart_weekly_dashboard(data, portfolio):
    symbols = ["SPY", "QQQ"]
    for position in portfolio.get("positions", []):
        symbol = position.get("symbol")
        if symbol and symbol in data and symbol not in symbols:
            symbols.append(symbol)
    symbols = symbols[:4]
    if not symbols:
        return None
    rows = 2 if len(symbols) > 2 else 1
    cols = 2
    fig, axes = plt.subplots(rows, cols, figsize=(12, 3.6 * rows), dpi=120, squeeze=False)
    for ax, symbol in zip(axes.flat, symbols):
        chart_weekly(ax, symbol, get_rows(symbol), data[symbol])
    for ax in axes.flat[len(symbols):]:
        ax.axis("off")
    fig.suptitle("Weekly trend - SMA5/10/20 weeks", x=0.01, ha="left", fontsize=11, color=INK)
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    return to_png(fig)


def _th(text, align="right"):
    return (
        f'<th style="padding:8px 6px;font-size:10px;line-height:1.3;color:{MUTED};'
        f'text-align:{align};font-weight:600;letter-spacing:.04em;text-transform:uppercase;'
        f'border-bottom:1px solid {BORDER};background:#f8fafc;">{text}</th>'
    )


def _td(value, align="right", color=INK, size="12px", bold=False):
    weight = "600" if bold else "400"
    return (
        f'<td style="padding:8px 6px;font-size:{size};line-height:1.45;color:{color};'
        f'text-align:{align};font-weight:{weight};border-bottom:1px solid #f1f5f9;">{value}</td>'
    )


def _card(label, value, sub, color=INK):
    return (
        '<td class="card" width="33%" style="padding:0 6px;vertical-align:top;">'
        '<div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:12px;padding:14px 16px;">'
        f'<div style="font-size:10px;letter-spacing:.08em;text-transform:uppercase;color:{MUTED};">{label}</div>'
        f'<div style="font-size:21px;font-weight:700;color:{color};margin-top:6px;">{value}</div>'
        f'<div style="font-size:11px;color:{MUTED};margin-top:4px;line-height:1.5;">{sub}</div>'
        '</div></td>'
    )


def _regime(data):
    spy = data.get("SPY")
    qqq = data.get("QQQ")
    if not spy or not qqq:
        return "数据不足", "等待行情恢复"
    spy_last = latest_price(spy)
    qqq_last = latest_price(qqq)
    above200 = spy_last > (spy.get("sma200") or 0) and qqq_last > (qqq.get("sma200") or 0)
    below20 = spy_last < (spy.get("sma20") or 0) and qqq_last < (qqq.get("sma20") or 0)
    above20 = spy_last > (spy.get("sma20") or 0) and qqq_last > (qqq.get("sma20") or 0)
    if above200 and below20:
        return "长期上升，短期回调", "SPY/QQQ 仍在 SMA200 上方，但跌破 SMA20"
    if above200 and above20:
        return "趋势偏强", "SPY/QQQ 在 SMA20 与 SMA200 上方"
    if not above200:
        return "中期转弱", "SPY/QQQ 跌破 SMA200"
    return "震荡/转换", "方向尚未确认"


def _market_advice(data):
    spy = data.get("SPY")
    qqq = data.get("QQQ")
    vix = data.get("^VIX")
    if not spy or not qqq:
        return "数据不足", "等待行情恢复后再制定计划", "#64748b"
    spy_last = latest_price(spy)
    qqq_last = latest_price(qqq)
    vix_last = latest_price(vix) if vix else None
    spy20 = spy.get("sma20") or 0
    qqq20 = qqq.get("sma20") or 0
    spy200 = spy.get("sma200") or 0
    qqq200 = qqq.get("sma200") or 0
    if vix_last and vix_last >= 22.31:
        return "风险厌恶", "VIX 已到 22.31 上方，暂停新多，优先减仓和保护本金", "#dc2626"
    if spy_last < spy200 and qqq_last < qqq200:
        return "中期转弱", "SPY/QQQ 跌破 SMA200，停止新多，现有仓位只减不加", "#dc2626"
    if spy_last < spy20 and qqq_last < qqq20:
        return "上升趋势中的回调", f"减少新开仓；SPY 站回 {spy20:.2f}、QQQ 站回 {qqq20:.2f} 才视为短线修复；跌破 20 日低点进一步防守", "#d97706"
    if spy_last > spy20 and qqq_last > qqq20:
        return "趋势偏强", "可按回踩计划分批，但不追高；单笔仍按 0.5% 风险预算", "#16a34a"
    return "震荡/转换", "方向未确认，减少新仓，等待指数给出方向", "#64748b"


def _advice_rows(data, portfolio):
    rows = []
    for p in portfolio.get("positions", []):
        symbol = p.get("symbol")
        x = data.get(symbol)
        if not x:
            continue
        last = latest_price(x)
        cost = float(p.get("avg_cost") or 0)
        stop = p.get("stop")
        target = p.get("target")
        support = x.get("support")
        resistance = x.get("resistance")
        sma20 = x.get("sma20")
        sma50 = x.get("sma50")
        rsi = x.get("rsi14")
        sma3 = x.get("sma3")
        pnl_pct = ((last / cost - 1) * 100) if cost else None
        support_action = "先观察" if support and (last / support - 1) < 0.005 else "先减仓"
        if stop and last <= stop * 1.005:
            status, tone = "止损区", "#dc2626"
            advice = "按纪律退出或减仓，不补仓、不摊平。"
            trigger = f"已接近/跌破止损 {stop:.2f}"
        elif sma20 and sma50 and last < sma20 and last < sma50 and rsi is not None and rsi < 35:
            status, tone = "弱势超卖", "#d97706"
            advice = f"不建议加仓或摊平；反抽 {sma3:.2f} 不过则考虑减仓；站回 {sma20:.2f} 才转强。" if sma3 else "不建议加仓或摊平；反抽短期均线不过则考虑减仓。"
            if support and stop:
                trigger = f"跌破 {support:.2f} {support_action}；跌破止损 {stop:.2f} 退出；站回 {sma20:.2f} 才转强"
            elif stop:
                trigger = f"跌破止损 {stop:.2f} 退出；站回 {sma20:.2f} 才转强"
            else:
                trigger = f"站回 {sma20:.2f} 才转强"
        elif sma20 and last < sma20:
            status, tone = "短期弱势", "#d97706"
            advice = "持有观察，不新增；跌破支撑先观察，跌破止损再退出。"
            if support and stop:
                trigger = f"跌破 {support:.2f} {support_action}；跌破止损 {stop:.2f} 退出；站回 {sma20:.2f} 才转强"
            elif stop:
                trigger = f"跌破止损 {stop:.2f} 退出；站回 {sma20:.2f} 才转强"
            else:
                trigger = f"站回 {sma20:.2f} 才转强"
        elif sma20 and sma50 and last > sma20 and last > sma50 and rsi is not None and rsi >= 70:
            status, tone = "短线过热", "#2563eb"
            advice = "不追高；持有者可部分止盈并把止损上移。"
            trigger = f"回踩 {sma20:.2f} 不破可继续持有；跌破则减仓"
        elif sma20 and sma50 and last > sma20 and last > sma50:
            status, tone = "趋势偏强", "#16a34a"
            advice = "持有为主；回踩 SMA20 不破可继续，不追高。"
            trigger = f"回踩 {sma20:.2f} 附近观察；跌破支撑减仓"
        else:
            status, tone = "震荡", "#64748b"
            advice = "方向不明，持有观察，不新增。"
            trigger = f"突破 {resistance:.2f} 或跌破 {support:.2f} 后再行动" if support and resistance else "等待方向确认"
        rows.append({
            "symbol": symbol, "status": status, "tone": tone, "advice": advice,
            "trigger": trigger, "stop": stop, "target": target,
            "last": last, "pnl_pct": pnl_pct, "kind": "持仓",
        })

    candidates = []
    for symbol in portfolio.get("watchlist", []):
        x = data.get(symbol)
        if not x:
            continue
        last = latest_price(x)
        sma20, sma50, rsi = x.get("sma20"), x.get("sma50"), x.get("rsi14")
        if not (last and last >= 5 and sma20 and sma50 and rsi is not None):
            continue
        if last > sma20 > sma50 and 45 <= rsi <= 75:
            chg = ((last / x["prev_close"] - 1) * 100) if x.get("prev_close") else (x.get("chg_1d_pct") or 0)
            candidates.append((chg, symbol, x, last, sma20, sma50, rsi))
    candidates.sort(reverse=True)
    for _, symbol, x, last, sma20, sma50, rsi in candidates[:4]:
        support = x.get("support") or sma20
        resistance = x.get("resistance") or x.get("hi20")
        stop = support * 0.99 if support else sma20 * 0.98
        target = resistance if resistance and resistance > last else last + 2 * (last - stop)
        if resistance and abs(last / resistance - 1) < 0.02:
            advice = f"接近压力 {resistance:.2f}，等突破确认或回踩 {sma20:.2f} 企稳，不追高。"
        else:
            advice = f"趋势偏强，等回踩 {sma20:.2f} 企稳或突破 {resistance:.2f} 再考虑，不追高。"
        rows.append({
            "symbol": symbol, "status": "观察", "tone": "#2563eb", "advice": advice,
            "trigger": f"跌破 {stop:.2f} 失效；目标先看 {target:.2f}",
            "stop": stop, "target": target, "last": last, "pnl_pct": None, "kind": "自选",
        })
    return rows


def build_html(output, images, chart_errors=None):
    data = output.get("data", {})
    portfolio = output.get("portfolio", {})
    alerts = output.get("alerts", [])
    session = output.get("session", "")
    generated = output.get("generated_sgt")
    dt = datetime.fromisoformat(generated) if generated else datetime.now(SGT)
    date_str = dt.strftime("%Y-%m-%d")
    time_str = dt.strftime("%H:%M")
    et_str = dt.astimezone(ET).strftime("%H:%M")

    spy = data.get("SPY")
    qqq = data.get("QQQ")
    vix = data.get("^VIX")
    vix_last = latest_price(vix) if vix else None
    spy_last = latest_price(spy) if spy else None
    qqq_last = latest_price(qqq) if qqq else None
    regime_short, regime_detail = _regime(data)

    positions = portfolio.get("positions", [])
    total_pnl = 0.0
    cost_basis = 0.0
    market_value = 0.0
    position_rows = []
    for p in positions:
        symbol = p.get("symbol")
        x = data.get(symbol)
        if not x:
            continue
        last = latest_price(x)
        shares = float(p.get("shares") or 0)
        cost = float(p.get("avg_cost") or 0)
        stop = p.get("stop")
        target = p.get("target")
        pnl = (last - cost) * shares if cost else None
        pnl_pct = ((last / cost - 1) * 100) if cost else None
        risk = (last - stop) * shares if stop else None
        total_pnl += pnl or 0
        cost_basis += cost * shares
        market_value += last * shares
        position_rows.append({
            "symbol": symbol, "shares": shares, "cost": cost, "last": last,
            "pnl": pnl, "pnl_pct": pnl_pct, "stop": stop, "target": target, "risk": risk,
        })
    pnl_pct_total = (total_pnl / cost_basis * 100) if cost_basis else None
    pnl_color = pct_color(total_pnl)

    watch = []
    for symbol in portfolio.get("watchlist", []):
        x = data.get(symbol)
        if not x:
            continue
        last = latest_price(x)
        chg = ((last / x["prev_close"] - 1) * 100) if x.get("prev_close") else x.get("chg_1d_pct")
        watch.append({"symbol": symbol, "last": last, "chg": chg, "rsi": x.get("rsi14"), "trend": x.get("trend")})
    watch.sort(key=lambda z: (z["chg"] is None, -(z["chg"] or 0)))
    valid_watch = [w for w in watch if w["last"] and w["last"] >= 1 and w["rsi"] is not None and w["chg"] is not None]
    strongest = max(valid_watch, key=lambda z: z["chg"]) if valid_watch else None
    weakest = min(valid_watch, key=lambda z: z["chg"]) if valid_watch else None

    bullets = []
    bullets.append(
        f"大盘：{regime_short}。SPY {fmt(spy_last)}，QQQ {fmt(qqq_last)}，VIX {fmt(vix_last)}。"
    )
    if position_rows:
        parts = []
        for p in position_rows:
            parts.append(f"{p['symbol']} {p['pnl_pct']:+.2f}%" if p["pnl_pct"] is not None else p["symbol"])
        bullets.append("持仓：" + "，".join(parts) + "。")
    else:
        bullets.append("持仓：尚未提供持仓，当前仅监控大盘与自选。")
    if strongest and weakest:
        bullets.append(
            f"自选：相对最强 {strongest['symbol']} {strongest['chg']:+.2f}%，"
            f"相对最弱 {weakest['symbol']} {weakest['chg']:+.2f}%（仅相对强弱，不是买卖建议）。"
        )
    if alerts:
        bullets.append("触发：" + "；".join(alerts[:3]) + "。")

    market_stance, market_plan, market_tone = _market_advice(data)
    advice_rows = _advice_rows(data, portfolio)

    parts = []
    parts.append('<!DOCTYPE html><html><head><meta charset="utf-8">')
    parts.append('<meta name="viewport" content="width=device-width, initial-scale=1">')
    parts.append('<style>')
    parts.append(
        'body{margin:0;padding:0;background:#eef2f7;}'
        'table{border-collapse:collapse;border-spacing:0;}'
        'img{border:0;outline:none;text-decoration:none;}'
        'a{color:#2563eb;text-decoration:none;}'
        '@media only screen and (max-width:640px){'
        '.wrap{width:100%!important;}.px{padding-left:14px!important;padding-right:14px!important;}'
        '.card{display:block!important;width:100%!important;padding:0 0 8px 0!important;}'
        '}'
    )
    parts.append('</style></head>')
    parts.append('<body style="margin:0;padding:0;background:#eef2f7;">')
    parts.append('<table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="background:#eef2f7;">')
    parts.append('<tr><td align="center" style="padding:22px 10px;">')
    parts.append('<table role="presentation" class="wrap" width="900" cellspacing="0" cellpadding="0" border="0" style="width:900px;max-width:900px;background:#ffffff;border-radius:16px;overflow:hidden;border:1px solid #dbe3ee;">')

    parts.append(
        '<tr><td style="background-color:#0f172a;background-image:linear-gradient(135deg,#0f172a,#1e293b);padding:28px 30px;">'
        f'<div style="font-size:10px;letter-spacing:.18em;color:#94a3b8;">US MARKET MONITOR</div>'
        f'<div style="font-size:28px;line-height:1.2;font-weight:700;color:#ffffff;margin-top:6px;">美股监控日报</div>'
        f'<div style="font-size:12px;color:#cbd5e1;margin-top:9px;">{date_str} · {time_str} SGT / {et_str} ET · {session}</div>'
        '</td></tr>'
    )

    parts.append('<tr><td style="padding:18px 24px 0;">')
    parts.append('<table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0"><tr>')
    parts.append(_card("市场状态", regime_short, regime_detail, INK))
    parts.append(_card("持仓盈亏", f"{total_pnl:+,.2f} USD", f"成本 {cost_basis:,.2f} · 相对成本 {pnl_pct_total:+.2f}%" if cost_basis else "未提供持仓", pnl_color))
    parts.append(_card("触发提醒", str(len(alerts)), "有触发" if alerts else "无新触发", AMBER if alerts else MUTED))
    parts.append('</tr></table></td></tr>')

    parts.append('<tr><td style="padding:18px 24px 0;">')
    parts.append('<div style="font-size:15px;font-weight:700;color:#0f172a;margin-bottom:8px;">今日结论</div>')
    parts.append('<ul style="margin:0;padding-left:18px;color:#334155;font-size:13px;line-height:1.8;">')
    for b in bullets:
        parts.append(f'<li style="margin:3px 0;">{html_lib.escape(b)}</li>')
    parts.append('</ul></td></tr>')

    parts.append('<tr><td class="px" style="padding:18px 24px 0;">')
    parts.append('<div style="font-size:15px;font-weight:700;color:#0f172a;margin-bottom:8px;">今日建议</div>')
    parts.append(f'<div style="background:#f8fafc;border:1px solid #e2e8f0;border-left:4px solid {market_tone};border-radius:10px;padding:12px 14px;">')
    parts.append(f'<div style="font-size:13px;font-weight:700;color:{market_tone};margin-bottom:4px;">市场：{market_stance}</div>')
    parts.append(f'<div style="font-size:12px;color:#334155;line-height:1.65;">{market_plan}</div>')
    for row in advice_rows:
        if row["kind"] != "持仓":
            continue
        parts.append(
            f'<div style="font-size:12px;color:#334155;line-height:1.65;margin-top:8px;">'
            f'<b>{row["symbol"]}</b> <span style="color:{row["tone"]};font-weight:600;">{row["status"]}</span>：'
            f'{row["advice"]} <span style="color:#94a3b8;">触发/失效：{row["trigger"]}</span></div>'
        )
    watch_advice = [r for r in advice_rows if r["kind"] == "自选"]
    if watch_advice:
        parts.append(
            '<div style="font-size:12px;color:#334155;line-height:1.65;margin-top:8px;">'
            '<b>自选观察</b>：' + "；".join(f'{r["symbol"]}（{r["status"]}）' for r in watch_advice) + '。'
            '只做条件观察，不追高、不把观察当成买入指令。</div>'
        )
    parts.append('</div></td></tr>')

    if advice_rows:
        parts.append('<tr><td class="px" style="padding:18px 24px 0;">')
        parts.append('<div style="font-size:15px;font-weight:700;color:#0f172a;margin-bottom:10px;">操作计划</div>')
        parts.append('<div style="border:1px solid #e2e8f0;border-radius:12px;overflow:hidden;">')
        parts.append('<table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0">')
        parts.append('<tr>')
        for h, a in [("标的", "left"), ("状态", "left"), ("建议 / 触发", "left"), ("止损", "right"), ("目标", "right")]:
            parts.append(_th(h, a))
        parts.append('</tr>')
        for row in advice_rows:
            parts.append('<tr>')
            parts.append(_td(f'<b>{row["symbol"]}</b><div style="font-size:9px;color:#94a3b8;font-weight:400;">{row["kind"]}</div>', "left", INK, "11px", True))
            parts.append(_td(row["status"], "left", row["tone"], "10px", True))
            parts.append(_td(f'<div>{row["advice"]}</div><div style="font-size:9px;color:#94a3b8;line-height:1.5;margin-top:2px;">触发/失效：{row["trigger"]}</div>', "left", "#334155", "10px"))
            parts.append(_td(fmt(row["stop"]), "right", DOWN, "10px"))
            parts.append(_td(fmt(row["target"]), "right", UP, "10px"))
            parts.append('</tr>')
        parts.append('</table></div>')
        parts.append('<div style="font-size:10px;color:#94a3b8;margin-top:7px;line-height:1.5;">以上为条件化建议，不是保证盈利；触发价、流动性和滑点需在 TWS 中确认。自选建议只代表相对强势观察，不代表买入。</div>')
        parts.append('</td></tr>')

    key_symbols = []
    for s in ["SPY", "QQQ", "IWM", "SOXX"] + [p["symbol"] for p in position_rows]:
        if s in data and s not in key_symbols:
            key_symbols.append(s)
    parts.append('<tr><td class="px" style="padding:22px 24px 0;">')
    parts.append('<div style="font-size:15px;font-weight:700;color:#0f172a;margin-bottom:10px;">均线与关键位</div>')
    parts.append('<div style="border:1px solid #e2e8f0;border-radius:12px;overflow:hidden;">')
    parts.append('<table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0">')
    parts.append('<tr>')
    for h, a in [("标的", "left"), ("最新", "right"), ("3/5/20日", "right"), ("周5/10/20", "right"), ("支撑", "right"), ("压力", "right"), ("周线", "right")]:
        parts.append(_th(h, a))
    parts.append('</tr>')
    for s in key_symbols:
        x = data[s]
        last = latest_price(x)
        support = f"{fmt(x.get('support'))} {x.get('support_label') or ''}".strip()
        resistance = f"{fmt(x.get('resistance'))} {x.get('resistance_label') or ''}".strip()
        parts.append('<tr>')
        parts.append(_td(f'<b>{s}</b>', "left", INK, "12px", True))
        parts.append(_td(fmt(last), "right", INK, "12px", True))
        parts.append(_td(f'{fmt(x.get("sma3"))} / {fmt(x.get("sma5"))} / {fmt(x.get("sma20"))}', "right", MUTED, "10px"))
        parts.append(_td(f'{fmt(x.get("weekly_sma5"))} / {fmt(x.get("weekly_sma10"))} / {fmt(x.get("weekly_sma20"))}', "right", AMBER, "10px"))
        parts.append(_td(support, "right", SUPPORT))
        parts.append(_td(resistance, "right", RESIST))
        parts.append(_td(x.get("weekly_trend") or "-", "right", MUTED, "10px"))
        parts.append('</tr>')
    parts.append('</table></div>')
    parts.append('<div style="font-size:10px;color:#94a3b8;margin-top:7px;line-height:1.5;">3日/5日/20日为日线均线；周5/10/20为周线均线。支撑/压力取最近均线、前高前低、20日高低与 Pivot 的最近位置。</div>')
    parts.append('</td></tr>')

    chart_specs = [
        ("market_chart", "大盘图表", "SPY / QQQ / IWM / SOXX：日线收盘、3/5/20/50 日均线；蓝色虚线=支撑，橙色虚线=压力。"),
        ("holdings_chart", "持仓图表", "成本、止损、止盈与 3/5/20/50 日均线；黑色点线=成本，绿色点线=止损，红色点线=止盈。"),
        ("weekly_chart", "周线趋势", "周线收盘与 5/10/20 周均线。"),
    ]
    for cid, title, caption in chart_specs:
        if cid not in images:
            continue
        parts.append('<tr><td class="px" style="padding:22px 24px 0;">')
        parts.append(f'<div style="font-size:15px;font-weight:700;color:#0f172a;margin-bottom:8px;">{title}</div>')
        parts.append('<div style="border:1px solid #e2e8f0;border-radius:12px;padding:10px;background:#ffffff;">')
        parts.append(f'<img src="cid:{cid}" width="840" style="width:100%;max-width:840px;height:auto;display:block;" alt="{title}">')
        parts.append('</div>')
        parts.append(f'<div style="font-size:10px;color:#94a3b8;margin-top:6px;line-height:1.5;">{caption}</div>')
        parts.append('</td></tr>')

    parts.append('<tr><td class="px" style="padding:22px 24px 0;">')
    parts.append('<div style="font-size:15px;font-weight:700;color:#0f172a;margin-bottom:10px;">持仓</div>')
    if position_rows:
        parts.append('<div style="border:1px solid #e2e8f0;border-radius:12px;overflow:hidden;">')
        parts.append('<table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0">')
        parts.append('<tr>')
        for h, a in [("代码", "left"), ("股数", "right"), ("成本", "right"), ("最新", "right"), ("盈亏", "right"), ("止损", "right"), ("止盈", "right"), ("风险", "right")]:
            parts.append(_th(h, a))
        parts.append('</tr>')
        for p in position_rows:
            parts.append('<tr>')
            parts.append(_td(f'<b>{p["symbol"]}</b>', "left", INK, "12px", True))
            parts.append(_td(f'{p["shares"]:g}', "right", INK))
            parts.append(_td(fmt(p["cost"]), "right", MUTED))
            parts.append(_td(fmt(p["last"]), "right", INK, "12px", True))
            pnl_text = f'{p["pnl"]:+,.2f} ({p["pnl_pct"]:+.2f}%)' if p["pnl"] is not None and p["pnl_pct"] is not None else "-"
            parts.append(_td(pnl_text, "right", pct_color(p["pnl"])))
            parts.append(_td(fmt(p["stop"]), "right", DOWN))
            parts.append(_td(fmt(p["target"]), "right", UP))
            parts.append(_td(f'{p["risk"]:,.2f}' if p["risk"] is not None else "-", "right", MUTED))
            parts.append('</tr>')
        parts.append('</table></div>')
        parts.append('<div style="font-size:10px;color:#94a3b8;margin-top:7px;line-height:1.5;">风险 = (最新价 − 止损) × 股数，未计滑点和手续费。成本为截图推算，若与 IBKR 平均成本不同请告知。</div>')
    else:
        parts.append('<div style="font-size:12px;color:#64748b;background:#f8fafc;border:1px solid #e2e8f0;border-radius:10px;padding:12px;">尚未提供持仓；当前仅监控大盘和自选列表。</div>')
    parts.append('</td></tr>')

    parts.append('<tr><td class="px" style="padding:22px 24px 0;">')
    parts.append('<div style="font-size:15px;font-weight:700;color:#0f172a;margin-bottom:10px;">自选观察</div>')
    if watch:
        parts.append('<div style="border:1px solid #e2e8f0;border-radius:12px;overflow:hidden;">')
        parts.append('<table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0">')
        parts.append('<tr>')
        for h, a in [("代码", "left"), ("最新", "right"), ("1日%", "right"), ("RSI", "right"), ("趋势", "right")]:
            parts.append(_th(h, a))
        parts.append('</tr>')
        for w in watch:
            parts.append('<tr>')
            parts.append(_td(f'<b>{w["symbol"]}</b>', "left", INK, "11px", True))
            parts.append(_td(fmt(w["last"]), "right", INK, "11px"))
            parts.append(_td(f'{w["chg"]:+.2f}' if w["chg"] is not None else "-", "right", pct_color(w["chg"]), "11px"))
            parts.append(_td(f'{w["rsi"]:.1f}' if w["rsi"] is not None else "-", "right", MUTED, "11px"))
            parts.append(_td(w["trend"] or "-", "right", MUTED, "11px"))
            parts.append('</tr>')
        parts.append('</table></div>')
    parts.append('</td></tr>')

    if chart_errors:
        parts.append('<tr><td class="px" style="padding:18px 24px 0;">')
        parts.append('<div style="font-size:10px;color:#b45309;background:#fffbeb;border:1px solid #fde68a;border-radius:8px;padding:8px 10px;">图表生成提示：' + html_lib.escape("; ".join(chart_errors)) + '</div>')
        parts.append('</td></tr>')

    parts.append('<tr><td style="padding:24px 24px 28px;">')
    parts.append('<div style="border-top:1px solid #e2e8f0;padding-top:14px;font-size:10px;color:#94a3b8;line-height:1.7;">')
    parts.append('数据源：Yahoo Finance，可能延迟约 15 分钟；不是 IBKR 实时报价，不能作为精确成交价。<br>')
    parts.append('颜色：红涨绿跌，与 IBKR 中文界面一致。<br>')
    parts.append('本邮件仅用于监控和规则提示，不构成投资建议，不代下单。<br>')
    parts.append('<a href="https://github.com/racking-in/us-market-monitor-public">GitHub: us-market-monitor</a>')
    parts.append('</div></td></tr>')

    parts.append('</table></td></tr></table></body></html>')
    return "".join(parts)


def build_email(output, daily=False):
    data = output.get("data", {})
    portfolio = output.get("portfolio", {})
    alerts = output.get("alerts", [])
    images = {}
    chart_errors = []
    for cid, builder in [
        ("market_chart", lambda: chart_market(data)),
        ("holdings_chart", lambda: chart_holdings(portfolio, data)),
        ("weekly_chart", lambda: chart_weekly_dashboard(data, portfolio)),
    ]:
        try:
            png = builder()
            if png:
                images[cid] = png
        except Exception as exc:
            chart_errors.append(f"{cid}: {exc}")
    html_body = build_html(output, images, chart_errors)
    report_path = Path(__file__).resolve().parent / "monitor_report.md"
    text_body = report_path.read_text(encoding="utf-8") if report_path.exists() else "美股监控报告"
    dt = datetime.fromisoformat(output.get("generated_sgt")) if output.get("generated_sgt") else datetime.now(SGT)
    regime_short, _ = _regime(data)
    if daily:
        subject = f"美股日报 | {dt:%Y-%m-%d} | {regime_short}"
    elif alerts:
        subject = f"美股提醒 | {alerts[0][:70]}"
    else:
        subject = f"美股监控 | {dt:%Y-%m-%d %H:%M} SGT"
    return subject, html_body, text_body, images
