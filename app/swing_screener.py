import csv
import io
import math
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple, Union

try:
    from app.screener import (
        CFG,
        ara_pct_for,
        calc_rr,
        fmt,
        load_json,
        pct,
        pi,
        raw,
        round_down_tick,
        round_up_to,
        step,
        tick_size,
        ticks_between,
        value_area,
    )
except ImportError:
    from screener import (
        CFG,
        ara_pct_for,
        calc_rr,
        fmt,
        load_json,
        pct,
        pi,
        raw,
        round_down_tick,
        round_up_to,
        step,
        tick_size,
        ticks_between,
        value_area,
    )


SWING_CFG: Dict[str, Any] = {
    "fee_buy_pct": 0.15,
    "fee_sell_pct": 0.25,
    "va_pct": 0.70,
    "min_median_val_20d": 2_000_000_000,
    "min_rr_net": 2.0,
    "weights": {
        "layer1_price": 25.0,
        "layer2_orderflow": 25.0,
        "layer3_bandar": 20.0,
        "layer4_trajectory": 20.0,
        "layer5_network": 10.0,
    },
}


def pf(val: Any) -> float:
    if val is None or val == "":
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip().replace(",", "")
    if not s:
        return 0.0
    if s.startswith("(") and s.endswith(")"):
        s = "-" + s[1:-1]
    try:
        return float(s)
    except ValueError:
        return 0.0


def clamp(val: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, val))


def median_val(vals: List[float]) -> float:
    if not vals:
        return 0.0
    s = sorted(vals)
    n = len(s)
    mid = n // 2
    return float(s[mid]) if n % 2 == 1 else (s[mid - 1] + s[mid]) / 2.0


def load_historical_csv(source: Union[str, List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    if isinstance(source, list):
        raw_rows = source
    elif isinstance(source, str):
        if "\n" in source or "\r" in source:
            raw_rows = list(csv.DictReader(io.StringIO(source)))
        else:
            with open(source, encoding="utf-8-sig") as f:
                raw_rows = list(csv.DictReader(f))
    else:
        raise ValueError("Format sumber CSV historis tidak didukung.")

    bars: List[Dict[str, Any]] = []
    for r in raw_rows:
        dt = str(r.get("date") or r.get("Date") or "").strip()
        c = pi(r.get("close") or r.get("Close"))
        if not dt or c <= 0:
            continue
        o = pi(r.get("open") or r.get("Open")) or c
        h = pi(r.get("high") or r.get("High")) or max(o, c)
        l = pi(r.get("low") or r.get("Low")) or min(o, c)
        vol = pi(r.get("volume") or r.get("Volume"))
        val = pi(r.get("value") or r.get("Value"))
        freq = pi(r.get("frequency") or r.get("Frequency"))
        avg = pi(r.get("average") or r.get("Average"))
        if avg <= 0:
            avg = int(round(val / (vol * 100.0))) if vol > 0 and val > 0 else int(round((h + l + c) / 3.0))
        chg = pi(r.get("change") or r.get("Change"))
        chg_pct = pf(r.get("change_percentage") or r.get("Change_Percentage"))
        fb = pi(r.get("foreign_buy") or r.get("Foreign_Buy"))
        fs = pi(r.get("foreign_sell") or r.get("Foreign_Sell"))
        nf = pi(r.get("net_foreign") or r.get("Net_Foreign"))
        bars.append({
            "date": dt,
            "open": o,
            "high": h,
            "low": l,
            "close": c,
            "average": avg,
            "volume": vol,
            "value": val,
            "frequency": freq,
            "change": chg,
            "change_pct": chg_pct,
            "foreign_buy": fb,
            "foreign_sell": fs,
            "net_foreign": nf,
        })

    bars.sort(key=lambda x: x["date"])
    if not bars:
        raise ValueError("Data CSV historis kosong atau tidak memiliki baris harga valid.")
    return bars


def round_up_tick(price: int) -> int:
    return round_up_to(price, tick_size(price))


def _is_arb_floor_bar(cur: Dict[str, Any], prev_close: int, post_suspension_or_blowoff: bool = False) -> bool:
    if prev_close <= 0 or cur["close"] != cur["low"]:
        return False
    c = cur["close"]
    t = tick_size(c)
    arb_7 = round_up_tick(int(math.ceil(prev_close * 0.93)))
    arb_10 = round_up_tick(int(math.ceil(prev_close * 0.90)))
    arb_15 = round_up_tick(int(math.ceil(prev_close * 0.85)))
    if c <= arb_15 + t and cur["change_pct"] <= -14.0:
        return True
    if abs(c - arb_10) <= t and -10.2 <= cur["change_pct"] <= -9.3:
        return True
    if post_suspension_or_blowoff and abs(c - arb_7) <= t and -7.2 <= cur["change_pct"] <= -6.2:
        return True
    return False


def _composite_vp(bars: List[Dict[str, Any]], va_pct: float = 0.70) -> Dict[str, Any]:
    vp_lots: Dict[int, int] = defaultdict(int)
    total_lot = 0
    for b in bars:
        lot = b["volume"]
        if lot <= 0:
            continue
        total_lot += lot
        p_avg = round_down_tick(b["average"])
        p_cls = round_down_tick(b["close"])
        p_hi = round_down_tick(b["high"])
        p_lo = round_down_tick(b["low"])
        # shortcut: EOD bars lack intraday tick prints, so weight volume 50/25/12.5/12.5 across VWAP/C/H/L; upgrade when multi-day tick CSV is available.
        vp_lots[p_avg] += int(round(lot * 0.50))
        vp_lots[p_cls] += int(round(lot * 0.25))
        vp_lots[p_hi] += int(round(lot * 0.125))
        vp_lots[p_lo] += max(0, lot - int(round(lot * 0.50)) - int(round(lot * 0.25)) - int(round(lot * 0.125)))

    if not vp_lots or total_lot <= 0:
        last_c = bars[-1]["close"] if bars else 0
        return {"vpoc": last_c, "val": last_c, "vah": last_c, "total_lot": 0}

    vp_formatted = {p: {"lot": l} for p, l in vp_lots.items()}
    vpoc = max(vp_lots, key=lambda p: vp_lots[p])
    val, vah = value_area(vp_formatted, vpoc, va_pct)
    return {"vpoc": vpoc, "val": val, "vah": vah, "total_lot": total_lot}


def compute_layer1_price(bars: List[Dict[str, Any]], cfg: Dict[str, Any]) -> Dict[str, Any]:
    n = len(bars)
    last = bars[-1]
    prev = bars[-2] if n >= 2 else last
    close = last["close"]
    tick = tick_size(close)

    def sma(window: int) -> float:
        sub = bars[-window:] if n >= window else bars
        return sum(b["close"] for b in sub) / len(sub)

    ma10 = round(sma(10), 2)
    ma20 = round(sma(20), 2)
    ma50 = round(sma(50), 2)
    ma200 = round(sma(200), 2)

    tr_list: List[float] = []
    start_idx = max(1, n - 14)
    for i in range(start_idx, n):
        cur = bars[i]
        prv_c = bars[i - 1]["close"]
        tr = max(cur["high"] - cur["low"], abs(cur["high"] - prv_c), abs(cur["low"] - prv_c))
        tr_list.append(float(tr))
    atr14 = round(sum(tr_list) / len(tr_list), 2) if tr_list else float(last["high"] - last["low"])
    atr_pct = round(pct(atr14, close), 2)

    b20 = bars[-20:] if n >= 20 else bars
    b10 = bars[-10:] if n >= 10 else bars
    b5 = bars[-5:] if n >= 5 else bars
    b60 = bars[-60:] if n >= 60 else bars

    active_b20 = [b for b in b20 if b["volume"] > 0]
    median_val_20d = int(median_val([float(b["value"]) for b in active_b20])) if active_b20 else 0
    avg_val_20d = int(sum(b["value"] for b in b20) / len(b20))
    avg_val_5d = int(sum(b["value"] for b in b5) / len(b5))
    avg_lot_20d = int(sum(b["volume"] for b in active_b20) / len(active_b20)) if active_b20 else 0
    avg_lot_5d = int(sum(b["volume"] for b in b5) / len(b5))

    active_b5 = [b for b in b5 if b["volume"] > 0]
    range_5d = sum(pct(b["high"] - b["low"], max(1, b["low"])) for b in active_b5) / len(active_b5) if active_b5 else 0.0
    range_20d = sum(pct(b["high"] - b["low"], max(1, b["low"])) for b in active_b20) / len(active_b20) if active_b20 else 1.0
    vcp_ratio = round(range_5d / range_20d, 2) if range_20d > 0 else 1.0
    is_vcp = vcp_ratio <= 0.85 and range_5d <= 6.8

    red_5d = [b["volume"] for b in active_b5 if b["close"] <= b["open"] or b["change"] < 0]
    red_vol_avg = sum(red_5d) / len(red_5d) if red_5d else float(avg_lot_5d)
    red_vol_ratio = round(red_vol_avg / avg_lot_20d, 2) if avg_lot_20d > 0 else 1.0

    # Quiet pause/pullback bars before a breakout often close slightly green on minimal volume
    quiet_5d = [
        b["volume"]
        for b in active_b5
        if b["change"] <= 0 or pct(b["high"] - b["low"], max(1, b["low"])) <= range_20d * 0.75
    ]
    min_quiet_vol = min(quiet_5d) if quiet_5d else (min(b["volume"] for b in active_b5) if active_b5 else avg_lot_20d)
    quiet_vol_ratio = round(min_quiet_vol / avg_lot_20d, 2) if avg_lot_20d > 0 else 1.0
    vol_dryup_ratio = min(red_vol_ratio, quiet_vol_ratio)
    is_vol_dryup = vol_dryup_ratio <= 0.70

    vp20 = _composite_vp(b20, cfg["va_pct"])
    vp60 = _composite_vp(b60, cfg["va_pct"])
    prev_10 = bars[-20:-10] if n >= 20 else bars[: max(1, n // 2)]
    curr_10 = b10
    vp_prev10 = _composite_vp(prev_10, cfg["va_pct"])
    vp_curr10 = _composite_vp(curr_10, cfg["va_pct"])

    prev_5 = bars[-10:-5] if n >= 10 else prev_10
    vp_prev5 = _composite_vp(prev_5, cfg["va_pct"])
    vp_curr5 = _composite_vp(b5, cfg["va_pct"])

    if (vp_curr10["vpoc"] > vp_prev10["vpoc"] and vp_curr10["val"] >= vp_prev10["val"]) or (
        vp_curr5["vpoc"] > vp_prev5["vpoc"] and vp_curr5["val"] > vp_prev5["val"] and close >= vp_curr10["vpoc"]
    ):
        va_migration = "ASCENDING"
    elif vp_curr10["vpoc"] < vp_prev10["vpoc"] and vp_curr10["vah"] <= vp_prev10["vah"]:
        va_migration = "DESCENDING"
    else:
        va_migration = "CONSOLIDATING"

    b22 = bars[-22:] if n >= 22 else bars
    low_bar = min(b22, key=lambda x: (x["low"], -x["volume"]))
    high_bar = max(b22, key=lambda x: (x["high"], x["volume"]))
    swing_low_22d = low_bar["low"]
    swing_low_date = low_bar["date"]
    swing_low_vol = low_bar["volume"]
    swing_high_22d = high_bar["high"]
    swing_high_date = high_bar["date"]
    swing_high_60d = max((b["high"] for b in b60), default=swing_high_22d)

    high_10d = max(b["high"] for b in b10)
    low_10d = min(b["low"] for b in b10 if b["low"] > 0)
    active_prev_b5 = [b for b in b5[:-1] if b["low"] > 0]
    pullback_low_5d = min((b["low"] for b in active_prev_b5[-3:]), default=last["low"])
    handle_low_3d = min((b["low"] for b in bars[-2:] if b["low"] > 0), default=last["low"])

    dist_to_swing_low_pct = round(pct(close - swing_low_22d, swing_low_22d), 2)
    retest_vol_ratio = round(last["volume"] / swing_low_vol, 2) if swing_low_vol > 0 else 1.0
    is_low_vol_retest = (
        last["date"] > swing_low_date
        and 0.0 <= dist_to_swing_low_pct <= 9.0
        and retest_vol_ratio <= 0.65
    )

    zero_vol_days_10d = sum(1 for b in b10 if b["volume"] == 0)
    zero_vol_days_40d = sum(1 for b in bars[-40:] if b["volume"] == 0)
    recent_suspension_10d = zero_vol_days_10d >= 1

    # Detect high-volume blow-off upper-wick rejection (e.g. unsuspension gap & dump)
    blow_off_bars = [
        b
        for b in b10
        if b["high"] > 0
        and pct(b["high"] - b["close"], b["high"]) >= 12.0
        and b["volume"] >= avg_lot_20d * 1.4
    ]
    blow_off_rejection_10d = len(blow_off_bars) > 0
    drawdown_from_10d_high_pct = round(pct(high_10d - close, high_10d), 2) if high_10d > 0 else 0.0

    ara_lim_pct = ara_pct_for(prev["close"])
    arb_7_px = round_up_tick(int(math.ceil(prev["close"] * 0.93)))
    post_susp_blowoff = recent_suspension_10d or blow_off_rejection_10d
    is_arb_today = _is_arb_floor_bar(last, prev["close"], post_susp_blowoff)
    recent_arb_days = sum(
        1
        for i in range(max(1, n - 5), n)
        if _is_arb_floor_bar(bars[i], bars[i - 1]["close"], post_susp_blowoff)
    )

    vol_breakout_ratio = round(last["volume"] / avg_lot_20d, 2) if avg_lot_20d > 0 else 1.0
    is_breakout_10d = (
        close >= step(high_10d, -1)
        and last["change"] > 0
        and last["close"] >= last["average"]
        and last["volume"] >= avg_lot_20d * 0.95
    )

    illiquid = median_val_20d < cfg["min_median_val_20d"]

    if (close > ma20 >= ma50 and (close >= ma200 * 0.96 or close > ma10 >= ma20)) or (
        close >= ma50 and close >= ma200 * 0.96 and close > ma10 >= ma20
    ):
        trend_regime = "STAGE_2_UPTREND"
    elif close < ma20 < ma50:
        trend_regime = "STAGE_4_MARKDOWN" if close < ma200 else "DEEP_CORRECTION"
    elif blow_off_rejection_10d and drawdown_from_10d_high_pct >= 15.0:
        trend_regime = "BLOW_OFF_DISTRIBUTION"
    elif abs(pct(close - ma20, ma20)) <= 5.0 and is_vcp:
        trend_regime = "STAGE_1_BASE_COIL"
    else:
        trend_regime = "TRANSITION_RANGE"

    score = 50.0
    if trend_regime == "STAGE_2_UPTREND":
        score += 18.0
    elif trend_regime == "STAGE_1_BASE_COIL":
        score += 10.0
    elif trend_regime == "DEEP_CORRECTION":
        score -= 10.0
    elif trend_regime in ("STAGE_4_MARKDOWN", "BLOW_OFF_DISTRIBUTION"):
        score -= 18.0

    if va_migration == "ASCENDING":
        score += 10.0
    elif va_migration == "DESCENDING":
        score -= 8.0

    if is_vcp:
        score += 10.0
    if is_vol_dryup:
        score += 8.0
    if is_low_vol_retest:
        score += 8.0
    if is_breakout_10d:
        score += 10.0
        if vol_breakout_ratio >= 1.8:
            score += 4.0

    if close >= last["average"]:
        score += 5.0
    else:
        score -= 4.0

    if is_arb_today:
        score -= 30.0
    elif recent_arb_days >= 2:
        score -= 12.0
    if recent_suspension_10d:
        score -= 15.0
    if blow_off_rejection_10d:
        score -= 16.0
    if illiquid:
        score -= 20.0
    if zero_vol_days_40d >= 2:
        score -= 10.0

    return {
        "available": True,
        "score": round(clamp(score), 1),
        "date": last["date"],
        "ohlc": {
            "open": last["open"],
            "high": last["high"],
            "low": last["low"],
            "close": close,
            "average_vwap": last["average"],
            "prev_close": prev["close"],
            "change": last["change"],
            "change_pct": last["change_pct"],
            "volume_lot": last["volume"],
            "value_idr": last["value"],
            "frequency": last["frequency"],
            "tick": tick,
            "ara_limit_pct": ara_lim_pct,
            "arb_7_floor": arb_7_px,
        },
        "moving_averages": {
            "ma10": ma10,
            "ma20": ma20,
            "ma50": ma50,
            "ma200": ma200,
            "close_vs_ma20_pct": round(pct(close - ma20, ma20), 2),
            "close_vs_ma50_pct": round(pct(close - ma50, ma50), 2),
            "close_vs_ma200_pct": round(pct(close - ma200, ma200), 2),
        },
        "volatility_liquidity": {
            "trend_regime": trend_regime,
            "atr14": atr14,
            "atr_pct": atr_pct,
            "range_5d_pct": round(range_5d, 2),
            "range_20d_pct": round(range_20d, 2),
            "vcp_ratio": vcp_ratio,
            "is_vcp": is_vcp,
            "vol_dryup_ratio": vol_dryup_ratio,
            "red_vol_ratio": red_vol_ratio,
            "quiet_vol_ratio": quiet_vol_ratio,
            "is_vol_dryup": is_vol_dryup,
            "vol_breakout_ratio": vol_breakout_ratio,
            "is_breakout_10d": is_breakout_10d,
            "median_val_20d": median_val_20d,
            "avg_val_20d": avg_val_20d,
            "avg_val_5d": avg_val_5d,
            "avg_lot_20d": avg_lot_20d,
            "avg_lot_5d": avg_lot_5d,
        },
        "volume_profile": {
            "vp_20d": vp20,
            "vp_60d": vp60,
            "vp_curr_10d": vp_curr10,
            "vp_prev_10d": vp_prev10,
            "vp_curr_5d": vp_curr5,
            "vp_prev_5d": vp_prev5,
            "va_migration": va_migration,
            "swing_low_22d": swing_low_22d,
            "swing_low_date": swing_low_date,
            "swing_low_vol": swing_low_vol,
            "swing_high_22d": swing_high_22d,
            "swing_high_date": swing_high_date,
            "swing_high_60d": swing_high_60d,
            "high_10d": high_10d,
            "low_10d": low_10d,
            "pullback_low_5d": pullback_low_5d,
            "handle_low_3d": handle_low_3d,
            "drawdown_from_10d_high_pct": drawdown_from_10d_high_pct,
            "dist_to_swing_low_pct": dist_to_swing_low_pct,
            "retest_vol_ratio": retest_vol_ratio,
            "is_low_vol_retest": is_low_vol_retest,
        },
        "flags": {
            "is_arb_today": is_arb_today,
            "recent_arb_days_5d": recent_arb_days,
            "recent_suspension_10d": recent_suspension_10d,
            "blow_off_rejection_10d": blow_off_rejection_10d,
            "zero_vol_days_10d": zero_vol_days_10d,
            "zero_vol_days_40d": zero_vol_days_40d,
            "illiquid": illiquid,
        },
    }


def _deaccumulate(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not items:
        return []
    parsed = []
    for it in items:
        dt = str(it.get("date") or "").strip()
        lot = raw(it.get("lot"))
        val = raw(it.get("value"))
        freq = raw(it.get("frequency"))
        parsed.append({"date": dt, "lot": lot, "val": val, "freq": freq})

    is_cum = len(parsed) >= 2 and all(
        parsed[i]["lot"] >= parsed[i - 1]["lot"] and parsed[i]["val"] >= parsed[i - 1]["val"]
        for i in range(1, len(parsed))
    ) and parsed[-1]["lot"] > parsed[0]["lot"]

    if not is_cum:
        return parsed

    out = [parsed[0].copy()]
    for i in range(1, len(parsed)):
        out.append({
            "date": parsed[i]["date"],
            "lot": max(0, parsed[i]["lot"] - parsed[i - 1]["lot"]),
            "val": max(0, parsed[i]["val"] - parsed[i - 1]["val"]),
            "freq": max(0, parsed[i]["freq"] - parsed[i - 1]["freq"]),
        })
    return out


def compute_layer2_orderflow(tb_source: Any, bars: List[Dict[str, Any]]) -> Dict[str, Any]:
    jd = load_json(tb_source)
    d = jd.get("data", jd) if isinstance(jd, dict) else {}

    buy_daily = _deaccumulate(d.get("buy") or [])
    sell_daily = _deaccumulate(d.get("sell") or [])
    bm_buy_daily = _deaccumulate(d.get("big_money_buy") or [])
    bm_sell_daily = _deaccumulate(d.get("big_money_sell") or [])

    bm_rt_node = d.get("big_money_rt") or {}
    bm_rt_buy_daily = _deaccumulate(bm_rt_node.get("buy") or [])
    bm_rt_sell_daily = _deaccumulate(bm_rt_node.get("sell") or [])

    net_vals = {str(x.get("date")): raw(x.get("value")) for x in (d.get("net_values") or [])}
    net_lots = {str(x.get("date")): raw(x.get("lot")) for x in (d.get("net_values_volume") or [])}
    bm_net_vals = {str(x.get("date")): raw(x.get("value")) for x in (d.get("big_money_net_values") or [])}
    bm_net_lots = {str(x.get("date")): raw(x.get("lot")) for x in (d.get("big_money_net_values_volume") or [])}
    bm_rt_net_vals = {str(x.get("date")): raw(x.get("value")) for x in (bm_rt_node.get("net_values") or [])}
    bm_rt_net_lots = {str(x.get("date")): raw(x.get("lot")) for x in (bm_rt_node.get("net_values_volume") or [])}

    dates = sorted({x["date"] for x in buy_daily if x.get("date")} | set(net_vals.keys()))
    if not dates:
        raise ValueError("Data JSON Trade-Book tidak memiliki seri tanggal harian yang valid.")

    by_date_buy = {x["date"]: x for x in buy_daily}
    by_date_sell = {x["date"]: x for x in sell_daily}
    by_date_bmb = {x["date"]: x for x in bm_buy_daily}
    by_date_bms = {x["date"]: x for x in bm_sell_daily}
    by_date_rtb = {x["date"]: x for x in bm_rt_buy_daily}
    by_date_rts = {x["date"]: x for x in bm_rt_sell_daily}
    hist_by_date = {b["date"]: b for b in bars}

    daily_records: List[Dict[str, Any]] = []
    for dt in dates:
        b = by_date_buy.get(dt, {"lot": 0, "val": 0, "freq": 0})
        s = by_date_sell.get(dt, {"lot": 0, "val": 0, "freq": 0})
        bmb = by_date_bmb.get(dt, {"lot": 0, "val": 0, "freq": 0})
        bms = by_date_bms.get(dt, {"lot": 0, "val": 0, "freq": 0})
        rtb = by_date_rtb.get(dt, {"lot": 0, "val": 0, "freq": 0})
        rts = by_date_rts.get(dt, {"lot": 0, "val": 0, "freq": 0})

        ov_net_v = net_vals.get(dt, b["val"] - s["val"])
        ov_net_l = net_lots.get(dt, b["lot"] - s["lot"])
        bm_net_v = bm_net_vals.get(dt, bmb["val"] - bms["val"])
        bm_net_l = bm_net_lots.get(dt, bmb["lot"] - bms["lot"])
        rt_net_v = bm_rt_net_vals.get(dt, rtb["val"] - rts["val"])
        rt_net_l = bm_rt_net_lots.get(dt, rtb["lot"] - rts["lot"])

        hb = hist_by_date.get(dt)
        daily_records.append({
            "date": dt,
            "close": hb["close"] if hb else 0,
            "low": hb["low"] if hb else 0,
            "average": hb["average"] if hb else 0,
            "hist_vol": hb["volume"] if hb else (b["lot"] + s["lot"]),
            "buy_lot": b["lot"],
            "sell_lot": s["lot"],
            "buy_val": b["val"],
            "sell_val": s["val"],
            "buy_freq": b["freq"],
            "sell_freq": s["freq"],
            "ov_net_val": ov_net_v,
            "ov_net_lot": ov_net_l,
            "bm_buy_lot": bmb["lot"],
            "bm_sell_lot": bms["lot"],
            "bm_buy_val": bmb["val"],
            "bm_sell_val": bms["val"],
            "bm_net_val": bm_net_v,
            "bm_net_lot": bm_net_l,
            "rt_buy_lot": rtb["lot"],
            "rt_sell_lot": rts["lot"],
            "rt_net_val": rt_net_v,
            "rt_net_lot": rt_net_l,
            "retail_net_val": ov_net_v - bm_net_v,
            "retail_net_lot": ov_net_l - bm_net_l,
        })

    def summarize_window(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
        tot_b_lot = sum(r["buy_lot"] for r in rows)
        tot_s_lot = sum(r["sell_lot"] for r in rows)
        tot_b_freq = sum(r["buy_freq"] for r in rows)
        tot_s_freq = sum(r["sell_freq"] for r in rows)
        tot_bmb_val = sum(r["bm_buy_val"] for r in rows)
        tot_bms_val = sum(r["bm_sell_val"] for r in rows)

        avg_b_size = (tot_b_lot / tot_b_freq) if tot_b_freq > 0 else 0.0
        avg_s_size = (tot_s_lot / tot_s_freq) if tot_s_freq > 0 else 0.0
        plir = round(avg_b_size / avg_s_size, 2) if avg_s_size > 0 else 1.0

        ov_tot_lot = tot_b_lot + tot_s_lot
        bm_tot_val = tot_bmb_val + tot_bms_val
        pos_bm_days = sum(1 for r in rows if r["bm_net_val"] > 0)

        return {
            "days": len(rows),
            "overall_net_val": sum(r["ov_net_val"] for r in rows),
            "overall_net_lot": sum(r["ov_net_lot"] for r in rows),
            "haka_buy_pct": round(pct(tot_b_lot, ov_tot_lot), 1) if ov_tot_lot > 0 else 50.0,
            "bm_net_val": sum(r["bm_net_val"] for r in rows),
            "bm_net_lot": sum(r["bm_net_lot"] for r in rows),
            "bm_buy_pct": round(pct(tot_bmb_val, bm_tot_val), 1) if bm_tot_val > 0 else 50.0,
            "bm_pos_days": pos_bm_days,
            "bm_rt_net_val": sum(r["rt_net_val"] for r in rows),
            "bm_rt_net_lot": sum(r["rt_net_lot"] for r in rows),
            "retail_net_val": sum(r["retail_net_val"] for r in rows),
            "retail_net_lot": sum(r["retail_net_lot"] for r in rows),
            "plir": plir,
        }

    w1 = summarize_window(daily_records[-1:])
    w5 = summarize_window(daily_records[-5:])
    w10 = summarize_window(daily_records[-10:])
    w22 = summarize_window(daily_records)

    valid_lows = [r for r in daily_records if r["low"] > 0]
    if valid_lows:
        low_rec = min(valid_lows, key=lambda x: x["low"])
        low_idx = daily_records.index(low_rec)
    else:
        low_idx = 0
    since_low_rows = daily_records[low_idx:]
    avwap_num = sum(r["average"] * r["hist_vol"] for r in since_low_rows if r["average"] > 0 and r["hist_vol"] > 0)
    avwap_den = sum(r["hist_vol"] for r in since_low_rows if r["average"] > 0 and r["hist_vol"] > 0)
    avwap_swing_low = int(round(avwap_num / avwap_den)) if avwap_den > 0 else (bars[-1]["close"] if bars else 0)
    bm_net_since_low = sum(r["bm_net_val"] for r in since_low_rows)
    rt_net_since_low = sum(r["rt_net_val"] for r in since_low_rows)

    contrarian_10d = [r for r in daily_records[-10:] if r["ov_net_val"] < 0 and r["bm_net_val"] > 0]
    red_day_bm_absorption_10d = sum(r["bm_net_val"] for r in contrarian_10d)
    red_day_absorption_count = len(contrarian_10d)

    # Detect Paint-the-Tape Bull Trap (BM-RT single prints > 0 while Parent-Order BM < 0)
    paint_the_tape_trap = (
        (w22["bm_net_val"] < 0 and w22["bm_rt_net_val"] > 0)
        or (w10["bm_net_val"] < 0 and w10["bm_rt_net_val"] > 0)
    ) and w5["bm_net_val"] < 0

    if paint_the_tape_trap:
        exec_regime = "PAINT_THE_TAPE_BULL_TRAP"
    elif w5["bm_net_val"] > 0 and w5["bm_rt_net_val"] > 0:
        exec_regime = "AGGRESSIVE_SWEEP_ACCUMULATION"
    elif w5["bm_net_val"] > 0 and w5["bm_rt_net_val"] <= 0:
        exec_regime = "PASSIVE_ICEBERG_ABSORPTION"
    elif w5["bm_net_val"] < 0 and abs(w5["bm_net_val"]) > abs(w5["bm_rt_net_val"]) * 1.25:
        exec_regime = "STEALTH_TWAP_DISTRIBUTION"
    elif w5["bm_net_val"] < 0 and w5["retail_net_val"] > 0:
        exec_regime = "RETAIL_ABSORBING_INST_SUPPLY"
    else:
        exec_regime = "MIXED_CONSOLIDATION"

    score = 50.0
    if w5["bm_net_val"] > 0:
        score += min(18.0, 6.0 + (w5["bm_buy_pct"] - 50.0) * 0.8)
    else:
        score -= min(18.0, 6.0 + (50.0 - w5["bm_buy_pct"]) * 0.8)

    if w10["bm_net_val"] > 0:
        score += 10.0
    elif bm_net_since_low > 0 and red_day_bm_absorption_10d > 0 and w5["bm_net_val"] > 0:
        score += 2.0
    else:
        score -= 8.0

    if w22["bm_net_val"] > 0 and w22["bm_buy_pct"] >= 55.0:
        score += 8.0
    elif w22["bm_net_val"] < 0 and w22["bm_buy_pct"] <= 45.0:
        score -= 8.0

    if w5["bm_net_val"] > 0 and w5["bm_rt_net_val"] > 0:
        score += 6.0
    if red_day_bm_absorption_10d > 0 and red_day_absorption_count >= 2:
        score += 6.0

    if w5["plir"] >= 1.15:
        score += 8.0
    elif w5["plir"] >= 1.0:
        score += 3.0
    elif w5["plir"] < 0.85:
        score -= 8.0

    if bm_net_since_low > 0:
        score += 7.0
    if w1["bm_net_val"] > 0 or (w1["bm_rt_net_val"] > 0 and w5["bm_net_val"] > 0):
        score += 5.0
    if exec_regime == "PAINT_THE_TAPE_BULL_TRAP":
        score -= 12.0
    elif exec_regime == "STEALTH_TWAP_DISTRIBUTION":
        score -= 6.0

    return {
        "available": True,
        "score": round(clamp(score), 1),
        "window_1d": w1,
        "window_5d": w5,
        "window_10d": w10,
        "window_22d": w22,
        "anchored_from_swing_low": {
            "anchor_date": daily_records[low_idx]["date"],
            "days_since_low": len(since_low_rows),
            "avwap_swing_low": avwap_swing_low,
            "bm_net_val_since_low": bm_net_since_low,
            "bm_rt_net_val_since_low": rt_net_since_low,
            "red_day_bm_absorption_10d": red_day_bm_absorption_10d,
            "red_day_absorption_days_10d": red_day_absorption_count,
        },
        "execution_regime": exec_regime,
        "paint_the_tape_trap": paint_the_tape_trap,
    }


def compute_layer3_bandar(md_source: Any, close_px: int) -> Dict[str, Any]:
    if not md_source:
        return {"available": False, "score": None}
    jd = load_json(md_source)
    d = jd.get("data", jd) if isinstance(jd, dict) else {}
    bd = d.get("bandar_detector") or {}
    bs = d.get("broker_summary") or {}
    if not bd and not bs:
        return {"available": False, "score": None}

    def parse_participant(item: Dict[str, Any], is_buyer: bool) -> Dict[str, Any]:
        code = str(item.get("netbs_broker_code") or "").strip()
        inv_type = str(item.get("type") or "").strip()
        freq = max(1, int(pf(item.get("freq"))))
        if is_buyer:
            net_lot = pf(item.get("blot"))
            gross_lot = pf(item.get("blotv")) / 100.0
            net_val = pf(item.get("bval"))
            gross_val = pf(item.get("bvalv"))
            avg_px = pf(item.get("netbs_buy_avg_price"))
            valid_dir = net_lot > 0
        else:
            net_lot = pf(item.get("slot"))
            gross_lot = pf(item.get("slotv")) / 100.0
            net_val = pf(item.get("sval"))
            gross_val = pf(item.get("svalv"))
            avg_px = pf(item.get("netbs_sell_avg_price"))
            valid_dir = net_lot < 0

        if gross_lot < abs(net_lot):
            gross_lot = abs(net_lot)
        if gross_val < abs(net_val):
            gross_val = abs(net_val)

        conv = round(abs(net_lot) / gross_lot, 4) if (gross_lot > 0 and valid_dir) else 0.0
        lot_per_trade = round(gross_lot / freq, 1)
        val_per_trade = int(round(gross_val / freq)) if freq > 0 else 0

        # Price-agnostic institutional sizing: Rp 3.5M+/fill or 180+ lot/fill with >=45% retention
        if conv >= 0.45 and (val_per_trade >= 3_500_000 or lot_per_trade >= 180.0):
            behavior = "HIGH_CONVICTION_INST"
        elif conv >= 0.15:
            behavior = "SWING_POSITIONAL"
        else:
            behavior = "HIGH_CHURN_CROWD"

        dist_pct = round(pct(close_px - avg_px, avg_px), 2) if avg_px > 0 else 0.0
        # If institutional buyer is down >25%, flag as trapped legacy position rather than active accumulator
        is_trapped_legacy = bool(valid_dir and behavior == "HIGH_CONVICTION_INST" and dist_pct < -25.0)

        return {
            "code": code,
            "type": inv_type,
            "net_lot": int(round(net_lot)),
            "gross_lot": int(round(gross_lot)),
            "net_val": int(round(net_val)),
            "gross_val": int(round(gross_val)),
            "freq": freq,
            "lot_per_trade": lot_per_trade,
            "val_per_trade": val_per_trade,
            "conviction_ratio": conv,
            "avg_price": round(avg_px, 2),
            "close_vs_avg_pct": dist_pct,
            "behavior": behavior,
            "is_trapped_legacy": is_trapped_legacy,
        }

    buyers = [parse_participant(x, True) for x in (bs.get("brokers_buy") or [])]
    sellers = [parse_participant(x, False) for x in (bs.get("brokers_sell") or [])]

    hc_buyers = [b for b in buyers if b["behavior"] == "HIGH_CONVICTION_INST"]
    hc_sellers = [s for s in sellers if s["behavior"] == "HIGH_CONVICTION_INST"]
    active_hc_buyers = [b for b in hc_buyers if not b.get("is_trapped_legacy")]
    trapped_legacy_buyers = [b for b in hc_buyers if b.get("is_trapped_legacy")]
    inst_buyers = [b for b in buyers if b["conviction_ratio"] >= 0.15]
    active_inst_buyers = [b for b in inst_buyers if b.get("close_vs_avg_pct", 0) >= -25.0]

    inst_cost_num = sum(b["avg_price"] * abs(b["net_lot"]) for b in inst_buyers if b["avg_price"] > 0)
    inst_cost_den = sum(abs(b["net_lot"]) for b in inst_buyers if b["avg_price"] > 0)
    inst_cost_basis = round(inst_cost_num / inst_cost_den, 2) if inst_cost_den > 0 else float(close_px)

    active_cost_num = sum(b["avg_price"] * abs(b["net_lot"]) for b in active_inst_buyers if b["avg_price"] > 0)
    active_cost_den = sum(abs(b["net_lot"]) for b in active_inst_buyers if b["avg_price"] > 0)
    active_inst_avg_cost = round(active_cost_num / active_cost_den, 2) if active_cost_den > 0 else inst_cost_basis

    top3_b = buyers[:3]
    top3_cost_num = sum(b["avg_price"] * abs(b["net_lot"]) for b in top3_b if b["avg_price"] > 0)
    top3_cost_den = sum(abs(b["net_lot"]) for b in top3_b if b["avg_price"] > 0)
    top3_buyer_cost = round(top3_cost_num / top3_cost_den, 2) if top3_cost_den > 0 else float(close_px)

    top3_all_churn_crowd = bool(
        len(top3_b) >= 3 and all(b["conviction_ratio"] < 0.10 for b in top3_b)
    )
    top1_buyer_churn_trapped = bool(
        buyers
        and buyers[0]["conviction_ratio"] < 0.12
        and (buyers[0]["close_vs_avg_pct"] < -10.0 or top3_all_churn_crowd)
    )
    top1_buyer_legacy_trapped = bool(
        buyers
        and buyers[0].get("is_trapped_legacy")
    )

    top1_pct = pf((bd.get("top1") or {}).get("percent"))
    top3_pct = pf((bd.get("top3") or {}).get("percent"))
    top5_pct = pf((bd.get("top5") or {}).get("percent"))
    avg5_pct = pf((bd.get("avg5") or {}).get("percent"))
    total_buyer = pi(bd.get("total_buyer"))
    total_seller = pi(bd.get("total_seller"))

    score = 50.0
    score += clamp(avg5_pct * 1.2, -18.0, 18.0)
    score += clamp(top5_pct * 0.6, -12.0, 12.0)

    if total_seller > total_buyer and total_buyer > 0:
        score += 8.0
    elif total_buyer > total_seller * 1.15:
        score -= 6.0

    hc_buy_lot = sum(b["net_lot"] for b in hc_buyers)
    hc_sell_lot = sum(abs(s["net_lot"]) for s in hc_sellers)
    active_hc_buy_lot = sum(b["net_lot"] for b in active_hc_buyers)

    if hc_buy_lot > hc_sell_lot and not top1_buyer_legacy_trapped:
        score += 12.0
        if len(active_hc_buyers) >= 2 and hc_buy_lot >= hc_sell_lot * 2.0:
            score += 4.0
    elif hc_sell_lot >= hc_buy_lot * 1.25 or (top1_buyer_legacy_trapped and hc_sell_lot > active_hc_buy_lot):
        score -= 10.0
    elif hc_sell_lot > hc_buy_lot:
        score -= 6.0

    if top1_buyer_churn_trapped:
        score -= 12.0
    elif top1_buyer_legacy_trapped:
        score -= 8.0
    elif buyers and buyers[0]["conviction_ratio"] >= 0.35:
        score += 10.0

    return {
        "available": True,
        "score": round(clamp(score), 1),
        "period_from": str(d.get("from") or ""),
        "period_to": str(d.get("to") or ""),
        "bandar_summary": {
            "broker_accdist": str(bd.get("broker_accdist") or "Neutral"),
            "cycle_vwap": round(pf(bd.get("average")), 2),
            "total_buyer": total_buyer,
            "total_seller": total_seller,
            "top1_pct": round(top1_pct, 2),
            "top3_pct": round(top3_pct, 2),
            "top5_pct": round(top5_pct, 2),
            "avg5_pct": round(avg5_pct, 2),
        },
        "cost_basis_map": {
            "top3_buyer_avg_cost": top3_buyer_cost,
            "inst_accumulator_avg_cost": inst_cost_basis,
            "active_inst_avg_cost": active_inst_avg_cost,
            "close_vs_inst_cost_pct": round(pct(close_px - inst_cost_basis, inst_cost_basis), 2),
            "close_vs_active_cost_pct": round(pct(close_px - active_inst_avg_cost, active_inst_avg_cost), 2),
            "overhead_supply_wall": int(round(top3_buyer_cost)) if top3_buyer_cost > close_px * 1.08 else None,
            "top1_buyer_churn_trapped": top1_buyer_churn_trapped,
            "top1_buyer_legacy_trapped": top1_buyer_legacy_trapped,
            "top3_all_churn_crowd": top3_all_churn_crowd,
            "hc_buyer_count": len(hc_buyers),
            "active_hc_buyer_count": len(active_hc_buyers),
            "trapped_legacy_count": len(trapped_legacy_buyers),
            "hc_buy_vs_sell_ratio": round(hc_buy_lot / max(1, hc_sell_lot), 2),
        },
        "top_buyers": buyers[:6],
        "top_sellers": sellers[:6],
        "high_conviction_buyers": hc_buyers[:5],
        "active_high_conviction_buyers": active_hc_buyers[:5],
        "high_conviction_sellers": hc_sellers[:5],
        "_conviction_lookup": {p["code"]: p for p in (buyers + sellers)},
    }


def compute_layer4_trajectory(rtc_source: Any, l3_data: Dict[str, Any]) -> Dict[str, Any]:
    if not rtc_source:
        return {"available": False, "score": None}
    jd = load_json(rtc_source)
    d = jd.get("data", jd) if isinstance(jd, dict) else {}
    charts = d.get("broker_chart_data") or []
    if not charts:
        return {"available": False, "score": None}

    vol_node = next((c for c in charts if c.get("type") == "TYPE_CHART_VOLUME"), None)
    val_node = next((c for c in charts if c.get("type") == "TYPE_CHART_VALUE"), None)
    if not vol_node:
        return {"available": False, "score": None}

    val_by_broker: Dict[str, Dict[str, float]] = {}
    if val_node:
        for b_entry in (val_node.get("charts") or []):
            bc = str(b_entry.get("broker_code") or "").strip()
            val_by_broker[bc] = {
                str(pt.get("date")): pf((pt.get("value") or {}).get("raw"))
                for pt in (b_entry.get("chart") or [])
            }

    conv_lookup = l3_data.get("_conviction_lookup") or {}
    trajectories: List[Dict[str, Any]] = []

    for b_entry in (vol_node.get("charts") or []):
        bc = str(b_entry.get("broker_code") or "").strip()
        pts = b_entry.get("chart") or []
        if not pts:
            continue
        series = [
            {
                "date": str(pt.get("date") or ""),
                "cum_lot": pf((pt.get("value") or {}).get("raw")),
                "cum_val": val_by_broker.get(bc, {}).get(str(pt.get("date") or ""), 0.0),
            }
            for pt in pts
            if pt.get("date")
        ]
        series.sort(key=lambda x: x["date"])
        if not series:
            continue

        cur_lot = series[-1]["cum_lot"]
        cur_val = series[-1]["cum_val"]

        def delta_at(days_back: int) -> Tuple[float, float]:
            idx = max(0, len(series) - 1 - days_back)
            return cur_lot - series[idx]["cum_lot"], cur_val - series[idx]["cum_val"]

        d1_lot, d1_val = delta_at(1)
        d5_lot, d5_val = delta_at(5)
        d10_lot, d10_val = delta_at(10)
        d20_lot, d20_val = delta_at(20)

        min_pt = min(series, key=lambda x: x["cum_lot"])
        max_pt = max(series, key=lambda x: x["cum_lot"])
        rebound_from_min = cur_lot - min_pt["cum_lot"]
        drawdown_from_max = cur_lot - max_pt["cum_lot"]

        prof = conv_lookup.get(bc, {})
        conv = prof.get("conviction_ratio", 0.25)
        behavior = prof.get("behavior", "UNKNOWN")

        trajectories.append({
            "code": bc,
            "behavior": behavior,
            "conviction_ratio": conv,
            "current_cum_lot": int(round(cur_lot)),
            "current_cum_val": int(round(cur_val)),
            "delta_1d_lot": int(round(d1_lot)),
            "delta_5d_lot": int(round(d5_lot)),
            "delta_10d_lot": int(round(d10_lot)),
            "delta_20d_lot": int(round(d20_lot)),
            "delta_5d_val": int(round(d5_val)),
            "delta_10d_val": int(round(d10_val)),
            "peak_lot": int(round(max_pt["cum_lot"])),
            "peak_date": max_pt["date"],
            "trough_lot": int(round(min_pt["cum_lot"])),
            "trough_date": min_pt["date"],
            "rebound_from_trough_lot": int(round(rebound_from_min)),
            "drawdown_from_peak_lot": int(round(drawdown_from_max)),
        })

    sellers_traj = [t for t in trajectories if t["current_cum_lot"] < 0]
    buyers_traj = [t for t in trajectories if t["current_cum_lot"] > 0]

    exhausted_sellers = [
        t["code"]
        for t in sellers_traj
        if abs(t["trough_lot"]) > 0
        and abs(min(0, t["delta_10d_lot"])) <= 0.05 * abs(t["trough_lot"])
        and abs(min(0, t["delta_5d_lot"])) <= 0.03 * abs(t["trough_lot"])
    ]
    tot_seller_trough = sum(abs(t["trough_lot"]) for t in sellers_traj)
    tot_seller_5d_dump = sum(min(0, t["delta_5d_lot"]) for t in sellers_traj)
    tot_seller_10d_dump = sum(min(0, t["delta_10d_lot"]) for t in sellers_traj)
    active_multi_day_dist = (
        tot_seller_trough > 0
        and (abs(tot_seller_5d_dump) >= 0.12 * tot_seller_trough or abs(tot_seller_10d_dump) >= 0.25 * tot_seller_trough)
    )
    seller_exhaustion = len(exhausted_sellers) > 0 and not active_multi_day_dist

    buyback_sellers = [
        t for t in sellers_traj
        if abs(t["trough_lot"]) > 0 and t["rebound_from_trough_lot"] >= 0.08 * abs(t["trough_lot"])
    ]
    distributor_buyback = len(buyback_sellers) > 0

    capitulating_crowd = [
        t for t in buyers_traj
        if (t["conviction_ratio"] < 0.12 or t == buyers_traj[0])
        and t["peak_lot"] > 0
        and t["drawdown_from_peak_lot"] <= -0.05 * t["peak_lot"]
    ]
    retail_capitulation = len(capitulating_crowd) > 0

    fresh_dip_buyers = [
        t for t in buyers_traj
        if t["conviction_ratio"] >= 0.15 and (t["delta_1d_lot"] > 0 or t["delta_5d_lot"] > 0)
    ]
    fresh_dip_accum = len(fresh_dip_buyers) > 0

    sustained_inst_buyers = [
        t for t in buyers_traj
        if t["conviction_ratio"] >= 0.20
        and t["peak_lot"] > 0
        and t["current_cum_lot"] >= 0.90 * t["peak_lot"]
        and t["delta_10d_lot"] > 0
    ]
    sustained_inst_accum = len(sustained_inst_buyers) > 0

    score = 50.0
    if seller_exhaustion:
        score += 12.0
    if distributor_buyback:
        score += 14.0
    if retail_capitulation and (seller_exhaustion or fresh_dip_accum):
        score += 8.0
    if fresh_dip_accum:
        score += 12.0
    if sustained_inst_accum:
        score += 14.0
    if active_multi_day_dist and not sustained_inst_accum:
        score -= 16.0

    net_top_5d = sum(t["delta_5d_lot"] for t in trajectories if t["conviction_ratio"] >= 0.15)
    if net_top_5d > 0:
        score += 8.0
    elif net_top_5d < 0:
        score -= 10.0

    return {
        "available": True,
        "score": round(clamp(score), 1),
        "signals": {
            "seller_exhaustion": seller_exhaustion,
            "exhausted_seller_codes": exhausted_sellers,
            "active_multi_day_distribution": active_multi_day_dist,
            "distributor_buyback": distributor_buyback,
            "buyback_details": [
                {"code": t["code"], "rebound_lot": t["rebound_from_trough_lot"], "trough_date": t["trough_date"]}
                for t in buyback_sellers
            ],
            "retail_capitulation": retail_capitulation,
            "capitulation_details": [
                {"code": t["code"], "cut_lot_from_peak": t["drawdown_from_peak_lot"], "peak_date": t["peak_date"]}
                for t in capitulating_crowd
            ],
            "fresh_dip_accumulation": fresh_dip_accum,
            "fresh_dip_buyers": [
                {"code": t["code"], "delta_1d_lot": t["delta_1d_lot"], "delta_5d_lot": t["delta_5d_lot"]}
                for t in fresh_dip_buyers
            ],
            "sustained_inst_accumulation": sustained_inst_accum,
            "sustained_inst_buyers": [
                {"code": t["code"], "current_cum_lot": t["current_cum_lot"], "delta_10d_lot": t["delta_10d_lot"]}
                for t in sustained_inst_buyers
            ],
        },
        "trajectories": trajectories,
    }


def compute_layer5_network(bd_source: Any, l3_data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if not bd_source:
        return {"available": False, "score": None}
    jd = load_json(bd_source)
    d = jd.get("data", jd) if isinstance(jd, dict) else {}
    by_vol = d.get("by_volume") or {}
    top_buy = by_vol.get("top_broker_buy") or []
    top_sell = by_vol.get("top_broker_sell") or []
    if not top_buy and not top_sell:
        return {"available": False, "score": None}

    conv_lookup = (l3_data or {}).get("_conviction_lookup") or {}
    self_match_records: List[Dict[str, Any]] = []
    tot_gross = 0
    tot_self = 0
    for node in top_buy[:15]:
        det = node.get("detail") or {}
        code = str(det.get("code") or "").strip()
        gross = pi(det.get("amount"))
        dist_list = node.get("distribute_to") or []
        self_amt = sum(pi(x.get("amount")) for x in dist_list if str(x.get("code") or "").strip() == code)
        tot_gross += gross
        tot_self += self_amt
        prof = conv_lookup.get(code, {})
        signed_net_lot = int(prof.get("net_lot", 0))
        net_lot = abs(signed_net_lot)
        churn_mult = round(self_amt / net_lot, 2) if net_lot > 0 else round(pct(self_amt, max(1, gross)) / 10.0, 2)
        if gross > 0:
            self_match_records.append({
                "code": code,
                "net_lot": signed_net_lot,
                "gross_lot": gross,
                "self_match_lot": self_amt,
                "self_match_pct": round(pct(self_amt, gross), 2),
                "self_match_vs_net_multiple": churn_mult,
                "counterparty_count": len(dist_list),
            })

    # Rank true net buyers first (by net_lot descending)
    self_match_records.sort(key=lambda r: (r["net_lot"] > 0, r["net_lot"], r["gross_lot"]), reverse=True)
    weighted_self_match_pct = round(pct(tot_self, tot_gross), 2) if tot_gross > 0 else 0.0

    dominant_vol_record = max(self_match_records, key=lambda r: r["gross_lot"]) if self_match_records else {}
    dominant_is_high_churn = bool(
        dominant_vol_record
        and (dominant_vol_record.get("self_match_pct", 0) >= 20.0 or dominant_vol_record.get("self_match_vs_net_multiple", 0) >= 3.5)
    )

    bandar_is_dist = bool(
        l3_data
        and (
            l3_data.get("bandar_summary", {}).get("broker_accdist") in ("Dist", "Big Dist")
            or l3_data.get("cost_basis_map", {}).get("top1_buyer_legacy_trapped")
        )
    )

    active_accumulators = [
        r for r in self_match_records
        if r["net_lot"] > 0 and not (conv_lookup.get(r["code"], {}).get("is_trapped_legacy"))
    ]
    top1_churn_mult = active_accumulators[0]["self_match_vs_net_multiple"] if active_accumulators else (
        self_match_records[0]["self_match_vs_net_multiple"] if self_match_records else 0.0
    )

    direct_flows: List[Dict[str, Any]] = []
    seller_dispersion_counts: List[int] = []
    for s_node in top_sell[:5]:
        det = s_node.get("detail") or {}
        s_code = str(det.get("code") or "").strip()
        s_gross = pi(det.get("amount"))
        dist_list = s_node.get("distribute_to") or []
        seller_dispersion_counts.append(len(dist_list))
        ext_targets = [
            x for x in dist_list if str(x.get("code") or "").strip() != s_code
        ]
        for tgt in ext_targets[:3]:
            amt = pi(tgt.get("amount"))
            direct_flows.append({
                "from_seller": s_code,
                "to_buyer": str(tgt.get("code") or "").strip(),
                "lot": amt,
                "share_of_seller_pct": round(pct(amt, s_gross), 2) if s_gross > 0 else 0.0,
            })

    buyer_source_counts = [len(b.get("distribute_to") or []) for b in top_buy[:5]]
    avg_seller_reach = sum(seller_dispersion_counts) / len(seller_dispersion_counts) if seller_dispersion_counts else 1.0
    avg_buyer_reach = sum(buyer_source_counts) / len(buyer_source_counts) if buyer_source_counts else 1.0

    if (
        (avg_buyer_reach > avg_seller_reach * 1.05 or (top1_churn_mult <= 0.50 and weighted_self_match_pct <= 15.0))
        and not (bandar_is_dist or dominant_is_high_churn)
    ):
        network_topology = "MANY_TO_FEW_ABSORPTION"
    elif dominant_is_high_churn and weighted_self_match_pct >= 12.0:
        network_topology = "CIRCULAR_WASH_ROTATION"
    elif avg_seller_reach > avg_buyer_reach * 1.08 or top1_churn_mult >= 3.0 or bandar_is_dist:
        network_topology = "FEW_TO_MANY_DISPERSION"
    else:
        network_topology = "BALANCED_ROTATION"

    score = 50.0
    if network_topology == "MANY_TO_FEW_ABSORPTION":
        score += 14.0
    elif network_topology == "CIRCULAR_WASH_ROTATION":
        score -= 10.0
    elif network_topology == "FEW_TO_MANY_DISPERSION":
        score -= 12.0

    if top1_churn_mult <= 0.50 and not (bandar_is_dist or dominant_is_high_churn):
        score += 10.0
    elif top1_churn_mult >= 3.5 or dominant_is_high_churn:
        score -= 12.0
    elif weighted_self_match_pct > 20.0:
        score -= 8.0

    return {
        "available": True,
        "score": round(clamp(score), 1),
        "network_topology": network_topology,
        "weighted_self_match_pct": weighted_self_match_pct,
        "top1_self_match_vs_net_multiple": top1_churn_mult,
        "self_match_breakdown": self_match_records[:5],
        "top_external_transfers": direct_flows[:8],
    }


def combine_swing_score(
    l1: Dict[str, Any],
    l2: Dict[str, Any],
    l3: Dict[str, Any],
    l4: Dict[str, Any],
    l5: Dict[str, Any],
    cfg: Dict[str, Any],
) -> Dict[str, Any]:
    w_cfg = cfg["weights"]
    layers = [
        ("layer1_price", l1.get("score"), w_cfg["layer1_price"]),
        ("layer2_orderflow", l2.get("score"), w_cfg["layer2_orderflow"]),
        ("layer3_bandar", l3.get("score"), w_cfg["layer3_bandar"]),
        ("layer4_trajectory", l4.get("score"), w_cfg["layer4_trajectory"]),
        ("layer5_network", l5.get("score"), w_cfg["layer5_network"]),
    ]
    active = [(k, float(sc), w) for k, sc, w in layers if sc is not None]
    total_w = sum(w for _, _, w in active) or 100.0

    composite = sum(sc * (w / total_w) for _, sc, w in active)
    breakdown = {
        k: {
            "score": sc,
            "base_weight": w,
            "effective_weight_pct": round((w / total_w) * 100.0, 1) if sc is not None else 0.0,
        }
        for k, sc, w in layers
    }
    return {
        "composite_score": round(clamp(composite), 1),
        "active_layers": len(active),
        "breakdown": breakdown,
    }


def _build_plan(
    entry_lo: int,
    entry_hi: int,
    sl_px: int,
    tp1_px: int,
    tp2_px: int,
    status: str,
    strategy: str,
    horizon: str,
    trigger: str,
    fee_cost_pct: float = 0.40,
) -> Dict[str, Any]:
    e_lo = round_down_tick(max(50, entry_lo))
    e_hi = round_up_tick(max(e_lo, entry_hi))
    ref_entry = e_hi
    sl = round_down_tick(min(e_lo - tick_size(e_lo), sl_px))
    tp1 = round_up_tick(max(ref_entry + tick_size(ref_entry) * 2, tp1_px))
    tp2 = round_up_tick(max(tp1 + tick_size(tp1) * 2, tp2_px))

    r1 = calc_rr(ref_entry, sl, tp1)
    r2 = calc_rr(ref_entry, sl, tp2)
    net_risk_pct = r1["risk_pct"] + fee_cost_pct
    net_tp1_pct = max(0.0, r1["gain_pct"] - fee_cost_pct)
    net_tp2_pct = max(0.0, r2["gain_pct"] - fee_cost_pct)
    rr1_net = net_tp1_pct / net_risk_pct if net_risk_pct > 0 else 0.0
    rr2_net = net_tp2_pct / net_risk_pct if net_risk_pct > 0 else 0.0

    return {
        "status": status,
        "strategy": strategy,
        "entry_zone": f"Rp {e_lo} - Rp {e_hi}",
        "entry_low": e_lo,
        "entry_high": e_hi,
        "entry_ref": ref_entry,
        "sl": sl,
        "sl_pct_net": round(-net_risk_pct, 2),
        "tp1": tp1,
        "tp1_pct_net": round(net_tp1_pct, 2),
        "tp2": tp2,
        "tp2_pct_net": round(net_tp2_pct, 2),
        "rr_tp1_net": round(rr1_net, 2),
        "rr_tp2_net": round(rr2_net, 2),
        "rr_net": round(max(rr1_net, rr2_net), 2),
        "holding_horizon": horizon,
        "trigger_rule": trigger,
    }


def eval_swing_setups(
    l1: Dict[str, Any],
    l2: Dict[str, Any],
    l3: Dict[str, Any],
    l4: Dict[str, Any],
    l5: Dict[str, Any],
    cfg: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    fee_cost = (cfg["fee_buy_pct"] + cfg["fee_sell_pct"]) if cfg else 0.40
    c = l1["ohlc"]["close"]
    vwap_d = l1["ohlc"]["average_vwap"]
    ma20 = l1["moving_averages"]["ma20"]
    ma50 = l1["moving_averages"]["ma50"]
    vl = l1["volatility_liquidity"]
    vp = l1["volume_profile"]
    vp20 = vp["vp_20d"]
    vp60 = vp["vp_60d"]
    vp10 = vp["vp_curr_10d"]
    w5 = l2["window_5d"]
    w10 = l2["window_10d"]
    avwap_low = l2["anchored_from_swing_low"]["avwap_swing_low"]

    sig4 = l4.get("signals") or {}
    cb3 = l3.get("cost_basis_map") or {}
    supply_wall = cb3.get("overhead_supply_wall")

    setups: List[Dict[str, Any]] = []

    m1, p1 = [], []
    if vl["is_vcp"]:
        m1.append(("Kontraksi volatilitas 5D/20D aktif (VCP)", f"rasio {vl['vcp_ratio']}x, range 5D {vl['range_5d_pct']}%"))
    else:
        p1.append(("Kontraksi volatilitas 5D/20D (VCP <= 0.85x)", f"saat ini {vl['vcp_ratio']}x"))
    if vl["is_vol_dryup"]:
        m1.append(("Volume koreksi/jeda mengering (Volume Dry-Up)", f"rasio {vl['vol_dryup_ratio']}x rata-rata 20D"))
    else:
        p1.append(("Volume koreksi <= 0.70x rata-rata 20D", f"saat ini {vl['vol_dryup_ratio']}x"))
    if w5["bm_net_val"] > 0 and (w10["bm_net_val"] > 0 or w5["bm_net_val"] >= -w10["bm_net_val"] * 0.5):
        m1.append(("Akumulasi Big Money positif di fase base", f"BM 5D Rp {fmt(w5['bm_net_val'])}, 10D Rp {fmt(w10['bm_net_val'])}"))
    else:
        p1.append(("Big Money 5D harus Net Buy (> 0)", f"saat ini 5D Rp {fmt(w5['bm_net_val'])}, 10D Rp {fmt(w10['bm_net_val'])}"))
    if w5["plir"] >= 1.0:
        m1.append(("Ukuran lot per order beli mengungguli jual (PLIR >= 1.0)", f"PLIR 5D {w5['plir']}x"))
    else:
        p1.append(("PLIR 5D >= 1.0x", f"saat ini {w5['plir']}x"))

    s1_lo = max(vp20["val"], vp["swing_low_22d"], step(c, -4))
    s1_hi = max(c, min(step(c, 2), vp20["vpoc"]))
    if s1_lo >= s1_hi:
        s1_lo = step(c, -2)
        s1_hi = max(c, step(c, 1))
    s1_sl = step(min(s1_lo, vp["swing_low_22d"]), -2)
    s1_tp1 = min(max(vp20["vah"], int(round(ma20)), int(round(s1_hi * 1.08))), int(round(s1_hi * 1.25)))
    s1_tp2 = min(max(vp["swing_high_22d"], vp60["vpoc"], int(round(s1_hi * 1.15))), int(round(s1_hi * 1.45)))
    if supply_wall and s1_tp2 > supply_wall:
        s1_tp2 = max(s1_tp1, step(supply_wall, -2))
    s1_valid_base = (
        vl["trend_regime"] != "STAGE_4_MARKDOWN"
        or (
            vl["is_vcp"]
            and w5["bm_net_val"] > 0
            and l2["execution_regime"] not in ("RETAIL_ABSORBING_INST_SUPPLY", "PAINT_THE_TAPE_BULL_TRAP", "STEALTH_TWAP_DISTRIBUTION")
        )
    )
    is_at_base = bool(c <= max(vp20["vah"], vp10["vah"]) * 1.04)
    setups.append({
        "id": 1,
        "name": "Multi-Day Silent Absorption & VCP Base",
        "category": "BASE ACCUMULATION SWING",
        "checks_met": m1,
        "checks_pending": p1,
        "params": _build_plan(
            s1_lo, s1_hi, s1_sl, s1_tp1, s1_tp2,
            status="READY" if (len(m1) >= 3 and s1_valid_base and is_at_base) else "DEVELOPING",
            strategy="Buy on Weakness di Base Demand / VAL",
            horizon="5 - 10 Hari Bursa (1 - 2 Minggu)",
            trigger=f"Antre di Rp {round_down_tick(s1_lo)}-{round_up_tick(s1_hi)} saat HAKI mengering & Close bertahan >= Rp {vwap_d}.",
            fee_cost_pct=fee_cost,
        ),
    })

    m2, p2 = [], []
    if vp["va_migration"] == "ASCENDING":
        m2.append(("Migrasi Value Area naik (Ascending Value Area)", f"VPOC 5D/10D naik ke Rp {vp['vp_curr_5d']['vpoc']} / Rp {vp10['vpoc']}"))
    else:
        p2.append(("Migrasi Value Area harus ASCENDING", f"saat ini {vp['va_migration']}"))
    if c >= ma20 and c >= vp10["vpoc"]:
        m2.append(("Harga bertahan di atas MA20 dan VPOC 10D", f"Close Rp {c} vs MA20 Rp {ma20:.0f}"))
    else:
        p2.append(("Close harus di atas MA20 & VPOC 10D", f"Close Rp {c} vs MA20 Rp {ma20:.0f}"))
    if w5["bm_net_val"] > 0 and w5["bm_rt_net_val"] >= 0:
        m2.append(("Breakout didukung Big Money Order & Running Trade", f"BM 5D Rp {fmt(w5['bm_net_val'])}, BM-RT 5D Rp {fmt(w5['bm_rt_net_val'])}"))
    else:
        p2.append(("Konfirmasi Big Money Net Buy positif", f"BM 5D Rp {fmt(w5['bm_net_val'])}"))
    if c >= step(vp["high_10d"], -2):
        m2.append(("Harga menembus/menguji High 10D", f"Close Rp {c} vs High 10D Rp {vp['high_10d']}"))
    else:
        p2.append(("Penembusan High 10D", f"High 10D Rp {vp['high_10d']}"))

    bo_px = vp["high_10d"]
    bo_lo = min(c, max(vwap_d, int(round(bo_px * 0.985))))
    s2_sl_base = max(vp["handle_low_3d"], vp["pullback_low_5d"], int(round(ma20)), int(round(bo_px * 0.94)))
    if s2_sl_base >= bo_lo:
        s2_sl_base = int(round(bo_lo - max(vl["atr14"] * 1.5, tick_size(bo_lo) * 4)))
    s2_sl = step(round_down_tick(s2_sl_base), -1)
    base_depth = max(0, vp["high_10d"] - vp["low_10d"])
    s2_tp1 = max(int(round(bo_px * 1.08)), min(int(round(bo_px + base_depth * 0.50)), int(round(bo_px * 1.15))))
    s2_tp2 = min(
        max(
            int(round(bo_px * 1.16)),
            min(max(vp["swing_high_22d"], vp["swing_high_60d"], bo_px + base_depth), int(round(bo_px * 1.35))),
        ),
        int(round(bo_px * 1.45)),
    )
    setups.append({
        "id": 2,
        "name": "Ascending Value Area & Breakout Valid",
        "category": "MOMENTUM BREAKOUT SWING",
        "checks_met": m2,
        "checks_pending": p2,
        "params": _build_plan(
            bo_lo, bo_px, s2_sl, s2_tp1, s2_tp2,
            status="READY" if len(m2) >= 3 else "INACTIVE",
            strategy="Buy on Breakout / Retest VAH & Daily VWAP",
            horizon="5 - 10 Hari Bursa",
            trigger=f"Eksekusi di Rp {round_down_tick(bo_lo)}-{round_up_tick(bo_px)} saat bertahan di atas VWAP Rp {vwap_d} dengan volume >= rata-rata 20D ({fmt(vl['avg_lot_20d'])} lot).",
            fee_cost_pct=fee_cost,
        ),
    })

    m3, p3 = [], []
    has_trend_structure = (c >= ma50 or vl["trend_regime"] == "STAGE_2_UPTREND")
    if has_trend_structure:
        m3.append(("Struktur tren menengah masih terjaga di atas MA50", f"Close Rp {c} vs MA50 Rp {ma50:.0f}"))
    else:
        p3.append(("Harga harus berada di atas MA50", f"Close Rp {c} vs MA50 Rp {ma50:.0f}"))
    if abs(pct(c - avwap_low, avwap_low)) <= 4.0 or abs(pct(c - vp20["vpoc"], vp20["vpoc"])) <= 4.0:
        m3.append(("Harga menguji area Anchored VWAP / Composite VPOC", f"AVWAP Low Rp {avwap_low}, VPOC 20D Rp {vp20['vpoc']}"))
    else:
        p3.append(("Pullback ke area AVWAP / VPOC (+-4%)", f"AVWAP Rp {avwap_low}, VPOC Rp {vp20['vpoc']}"))
    if l2["anchored_from_swing_low"]["bm_net_val_since_low"] > 0:
        m3.append(("Akumulasi Big Money sejak Swing Low masih positif", f"Net BM Rp {fmt(l2['anchored_from_swing_low']['bm_net_val_since_low'])}"))
    else:
        p3.append(("Net Big Money sejak Swing Low harus positif", f"saat ini Rp {fmt(l2['anchored_from_swing_low']['bm_net_val_since_low'])}"))
    if vl["vol_dryup_ratio"] <= 0.85:
        m3.append(("Volume pullback menyusut sehat", f"rasio {vl['vol_dryup_ratio']}x"))
    else:
        p3.append(("Volume pullback <= 0.85x rata-rata 20D", f"saat ini {vl['vol_dryup_ratio']}x"))

    is_at_pullback = bool(abs(pct(c - avwap_low, avwap_low)) <= 4.0 or abs(pct(c - vp20["vpoc"], vp20["vpoc"])) <= 4.0)
    s3_lo = min(c, avwap_low)
    s3_hi = max(c, avwap_low)
    if s3_lo < step(c, -4):
        s3_lo = step(c, -3)
    if s3_lo >= s3_hi:
        s3_lo = step(c, -2)
        s3_hi = step(c, 1)
    s3_sl = step(min(vp20["val"], vp["swing_low_22d"]), -2)
    s3_tp1 = min(max(vp20["vah"], vp["high_10d"], int(round(s3_hi * 1.08))), int(round(s3_hi * 1.25)))
    s3_tp2 = min(max(vp["swing_high_22d"], int(round(s3_hi * 1.15))), int(round(s3_hi * 1.45)))
    if supply_wall and s3_tp2 > supply_wall:
        s3_tp2 = max(s3_tp1, step(supply_wall, -2))
    setups.append({
        "id": 3,
        "name": "Pullback to Demand & Anchored VWAP Re-test",
        "category": "TREND PULLBACK SWING",
        "checks_met": m3,
        "checks_pending": p3,
        "params": _build_plan(
            s3_lo, s3_hi, s3_sl, s3_tp1, s3_tp2,
            status="READY" if (len(m3) >= 3 and has_trend_structure and is_at_pullback) else "DEVELOPING",
            strategy="Buy on Pullback di Anchored VWAP",
            horizon="5 - 8 Hari Bursa",
            trigger=f"Masuk bertahap di Rp {round_down_tick(s3_lo)}-{round_up_tick(s3_hi)} saat muncul candle pantulan di atas Rp {avwap_low}.",
            fee_cost_pct=fee_cost,
        ),
    })

    m4, p4 = [], []
    if vp["is_low_vol_retest"]:
        m4.append(("Retest sekunder di atas Capitulation Low dengan volume menyusut", f"Low Rp {vp['swing_low_22d']} ({vp['swing_low_date']}), vol retest {vp['retest_vol_ratio']}x"))
    else:
        p4.append(("Retest sekunder dekat Swing Low (0-9%) dengan volume <= 0.65x", f"jarak {vp['dist_to_swing_low_pct']}%, rasio vol {vp['retest_vol_ratio']}x"))
    if sig4.get("seller_exhaustion") or sig4.get("distributor_buyback"):
        ev_str = f"Exhausted: {sig4.get('exhausted_seller_codes')}, Buyback: {len(sig4.get('buyback_details') or [])} broker"
        m4.append(("Top Seller berhenti jualan (Seller Exhaustion) / mulai Buyback", ev_str))
    else:
        p4.append(("Konfirmasi Seller Exhaustion / Buyback di Running-Trade Chart", "belum terdeteksi"))
    if sig4.get("retail_capitulation") or sig4.get("fresh_dip_accumulation"):
        m4.append(("Kapitulasi ritel di dasar disertai serokan dip buyer aktif", f"Cut loss crowd: {sig4.get('retail_capitulation')}, Dip buyer: {sig4.get('fresh_dip_accumulation')}"))
    else:
        p4.append(("Kapitulasi crowd atau masuknya Fresh Dip Buyer", "belum terkonfirmasi"))
    if c >= vwap_d and l2["window_1d"]["bm_net_val"] > 0:
        m4.append(("Konfirmasi Reversal Bar: Close >= Daily VWAP & Big Money 1D Net Buy", f"Close Rp {c} vs VWAP Rp {vwap_d}"))
    else:
        p4.append(("Menunggu Trigger Reversal Harian: Close >= Daily VWAP & Big Money 1D > 0", f"Close Rp {c} vs VWAP Rp {vwap_d}, BM 1D Rp {fmt(l2['window_1d']['bm_net_val'])}"))

    inst_cost = cb3.get("inst_accumulator_avg_cost") or c
    s4_lo = max(vp["swing_low_22d"], step(c, -3))
    s4_hi = c
    if s4_lo >= s4_hi:
        s4_lo = step(c, -2)
        s4_hi = step(c, 1)
    s4_sl = max(step(vp["swing_low_22d"], -2), int(round(c * 0.93)))
    s4_tp1 = min(max(vp10["vpoc"], int(round(c * 1.08))), int(round(c * 1.15)))
    s4_tp2 = min(max(int(round(ma20)), int(round(inst_cost)), int(round(c * 1.16))), int(round(c * 1.30)))
    if supply_wall and s4_tp2 >= supply_wall:
        s4_tp2 = max(s4_tp1, min(step(round_down_tick(supply_wall), -2), int(round(c * 1.25))))
    setups.append({
        "id": 4,
        "name": "Capitulation Double-Bottom & Seller Exhaustion",
        "category": "MEAN-REVERSION REBOUND SWING",
        "checks_met": m4,
        "checks_pending": p4,
        "params": _build_plan(
            s4_lo, s4_hi, s4_sl, s4_tp1, s4_tp2,
            status="READY" if len(m4) == 4 else ("WAIT_TRIGGER" if len(m4) == 3 else "INACTIVE"),
            strategy="Speculative Buy on Support / Reversal Confirmation",
            horizon="5 - 10 Hari Bursa (Mean-Reversion)",
            trigger=f"Pertahankan support Rp {vp['swing_low_22d']}-{c} & tunggu 1 bar penutupan >= Rp {max(vwap_d, step(c, 2))} dengan Big Money Net Buy positif.",
            fee_cost_pct=fee_cost,
        ),
    })

    m5, p5 = [], []
    hc_b = l3.get("active_high_conviction_buyers") or l3.get("high_conviction_buyers") or []
    inst_cost = cb3.get("active_inst_avg_cost") or cb3.get("inst_accumulator_avg_cost") or c
    close_vs_cost_pct = cb3.get("close_vs_active_cost_pct", cb3.get("close_vs_inst_cost_pct", 0.0))
    if len(hc_b) >= 1:
        codes_str = ", ".join(f"{x['code']} ({x['conviction_ratio']*100:.0f}%)" for x in hc_b[:3])
        m5.append(("Terdeteksi High-Conviction Institutional Accumulator (rasio simpan >= 45%)", codes_str))
    else:
        p5.append(("Minimal 1 High-Conviction Accumulator di Market Detector", "tidak ditemukan"))
    if -15.0 <= close_vs_cost_pct <= 9.0:
        m5.append(("Harga berada di zona modal / markup awal institusi (-15% s/d +9%)", f"Close Rp {c} vs Modal Institusi Aktif Rp {inst_cost:.0f} ({close_vs_cost_pct:+.2f}%)"))
    else:
        p5.append(("Harga harus dekat modal institusi (-15% s/d +9%)", f"selisih {close_vs_cost_pct}%"))
    if not cb3.get("top1_buyer_churn_trapped", False) and not cb3.get("top1_buyer_legacy_trapped", False):
        m5.append(("Top 1 Buyer bukan ritel nyangkut atau institusi legacy terjebak", "struktur pemegang sehat"))
    else:
        p5.append(("Top 1 Buyer terjebak posisi nyangkut >25% atau didominasi ritel churn", f"modal Top 3 Buyer Rp {cb3.get('top3_buyer_avg_cost', 0):.0f}"))
    if w10["bm_net_val"] > 0 or l2["window_22d"]["bm_net_val"] > 0:
        m5.append(("Aliran Big Money 10D/22D searah dengan akumulasi broker", f"BM 10D Rp {fmt(w10['bm_net_val'])}, 22D Rp {fmt(l2['window_22d']['bm_net_val'])}"))
    else:
        p5.append(("Aliran Big Money 10D/22D harus positif", f"BM 10D Rp {fmt(w10['bm_net_val'])}"))

    s5_lo = min(c, vwap_d)
    s5_hi = max(c, vwap_d)
    if s5_lo >= s5_hi:
        s5_lo = step(c, -2)
        s5_hi = step(c, 1)
    else:
        s5_lo = min(s5_lo, step(c, -2))

    s5_sl_base = max(vp["swing_low_22d"], vp["handle_low_3d"], int(round(s5_lo * 0.94)))
    if s5_sl_base >= s5_lo:
        s5_sl_base = int(round(s5_lo - max(vl["atr14"] * 1.5, tick_size(s5_lo) * 4)))
    s5_sl = step(round_down_tick(s5_sl_base), -1)
    s5_tp1 = max(int(round(s5_hi * 1.07)), min(int(round(inst_cost)), int(round(s5_hi * 1.12))))
    s5_tp2 = min(max(int(round(inst_cost * 1.10)), int(round(s5_hi * 1.20))), int(round(s5_hi * 1.35)))
    if supply_wall and supply_wall > s5_hi * 1.05:
        if s5_tp1 >= supply_wall:
            s5_tp1 = step(supply_wall, -2)
        elif s5_tp2 > supply_wall:
            s5_tp2 = max(s5_tp2, step(supply_wall, 2))
    setups.append({
        "id": 5,
        "name": "Institutional Cost-Basis Discount Accumulation",
        "category": "SMART MONEY VALUE SWING",
        "checks_met": m5,
        "checks_pending": p5,
        "params": _build_plan(
            s5_lo, s5_hi, s5_sl, s5_tp1, s5_tp2,
            status="READY" if len(m5) >= 3 else "DEVELOPING",
            strategy="Buy Near Institutional Cost Basis",
            horizon="5 - 10 Hari Bursa",
            trigger=f"Akumulasi di rentang Rp {round_down_tick(s5_lo)}-{round_up_tick(s5_hi)} selama tidak jebol Rp {s5_sl}.",
            fee_cost_pct=fee_cost,
        ),
    })

    m6, p6 = [], []
    if l1["flags"]["is_arb_today"] or l1["flags"]["recent_arb_days_5d"] >= 1 or l1["flags"]["recent_suspension_10d"]:
        m6.append(("Terdeteksi ARB Floor Lock / Suspensi BEI aktif dalam 10 hari terakhir", f"ARB 5D: {l1['flags']['recent_arb_days_5d']}, Suspensi 10D: {l1['flags']['zero_vol_days_10d']} hari"))
    else:
        p6.append(("Tidak ada ARB Lock atau Suspensi aktif", "aman"))
    if l2["execution_regime"] in ("PAINT_THE_TAPE_BULL_TRAP", "STEALTH_TWAP_DISTRIBUTION", "RETAIL_ABSORBING_INST_SUPPLY") or w5["bm_net_val"] < -1_000_000_000:
        m6.append(("Distribusi Big Money aktif (Paint-the-Tape / TWAP Slicing / net dump > 1M)", f"Regime: {l2['execution_regime']}, BM 5D Rp {fmt(w5['bm_net_val'])}"))
    else:
        p6.append(("Tidak ada distribusi Big Money aktif", "aman"))
    if (
        cb3.get("top1_buyer_churn_trapped")
        or (l3.get("bandar_summary") or {}).get("broker_accdist") == "Dist"
        or (cb3.get("trapped_legacy_count", 0) >= 3 and w5["bm_net_val"] < -1_000_000_000)
    ):
        m6.append(("Struktur broker Distribusi / Top Buyer didominasi High-Churn Crowd / Likuidasi Legacy", f"Bandar: {(l3.get('bandar_summary') or {}).get('broker_accdist')}, Trapped Legacy: {cb3.get('trapped_legacy_count', 0)} broker"))
    else:
        p6.append(("Tidak ada distribusi bandar / jebakan ritel", "aman"))
    if (
        (vl["trend_regime"] in ("STAGE_4_MARKDOWN", "DEEP_CORRECTION") and (vp["va_migration"] == "DESCENDING" or vp["drawdown_from_10d_high_pct"] >= 15.0))
        or l1["flags"]["blow_off_rejection_10d"]
    ):
        m6.append(("Struktur harga Markdown atau Blow-Off Rejection ekstrem (>12% upper-wick dump)", f"Regime: {vl['trend_regime']}, Drop dari High 10D: -{vp['drawdown_from_10d_high_pct']}%"))
    else:
        p6.append(("Bukan fase Markdown atau Blow-Off Top", "aman"))

    setups.append({
        "id": 6,
        "name": "Multi-Day Distribution / Markdown Waterfall Trap",
        "category": "AVOID / CAPITAL PROTECTION",
        "checks_met": m6,
        "checks_pending": p6,
        "params": {
            "status": "DANGER_ACTIVE" if len(m6) >= 3 else "INACTIVE",
            "strategy": "HINDARI KEJAR HARGA / TUNGGU KONFIRMASI DASAR",
            "entry_zone": "JANGAN ENTRY SEBELUM KONFIRMASI REVERSAL",
            "sl": step(vp["swing_low_22d"], -2),
            "tp1": vp10["vah"],
            "tp2": vp20["vpoc"],
            "rr_net": 0.0,
            "holding_horizon": "N/A (Cash Protection)",
            "trigger_rule": f"Wajib keluar jika support struktural Rp {vp['swing_low_22d']} jebol.",
        },
    })

    for s in setups:
        tot = len(s["checks_met"]) + len(s["checks_pending"])
        s["score"] = round((len(s["checks_met"]) / tot) * 100.0, 1) if tot > 0 else 0.0

    return setups


def decide_swing_action(
    score_data: Dict[str, Any],
    l1: Dict[str, Any],
    l2: Dict[str, Any],
    setups: List[Dict[str, Any]],
    cfg: Dict[str, Any],
) -> Dict[str, Any]:
    comp = score_data["composite_score"]
    flags = l1["flags"]
    bull_setups = [s for s in setups if s["id"] != 6]
    trap_setup = next(s for s in setups if s["id"] == 6)
    best_bull = max(
        bull_setups,
        key=lambda x: (
            x["params"].get("status") == "READY" and float(x["params"].get("rr_net") or 0.0) >= cfg["min_rr_net"],
            x["score"],
            float(x["params"].get("rr_net") or 0.0),
        ),
    )
    best_rr = float(best_bull["params"].get("rr_net") or 0.0)

    if flags["is_arb_today"] or flags["illiquid"] or (flags["recent_suspension_10d"] and flags["blow_off_rejection_10d"]):
        if flags["is_arb_today"]:
            reason = "Terkunci ARB / Penutupan di Lantai Bawah Hari Ini"
        elif flags["illiquid"]:
            reason = "Likuiditas Harian di Bawah Rp 2 Miliar"
        else:
            reason = "Pasca-Suspensi BEI disertai Guyuran Blow-Off Top"
        return {
            "key": "AVOID",
            "label": f"HINDARI / TIDAK LAYAK SWING ({reason})",
            "conviction": "LOW",
            "best_setup": trap_setup["name"],
            "trade_plan": trap_setup["params"],
        }

    if trap_setup["score"] >= 75.0 and best_bull["params"].get("status") != "READY":
        return {
            "key": "AVOID_DISTRIBUTION",
            "label": "HINDARI: DISTRIBUSI SIKLUS / MARKDOWN BELUM SELESAI",
            "conviction": "LOW",
            "best_setup": trap_setup["name"],
            "trade_plan": trap_setup["params"],
        }

    is_ready = best_bull["params"].get("status") == "READY"

    if is_ready and comp >= 70.0 and best_bull["score"] >= 75.0 and best_rr >= cfg["min_rr_net"]:
        return {
            "key": "STRONG_BUY",
            "label": "STRONG BUY SWING (HIGH CONVICTION ACCUMULATION & BREAKOUT)",
            "conviction": "HIGH",
            "best_setup": best_bull["name"],
            "trade_plan": best_bull["params"],
        }

    if is_ready and comp >= 56.0 and best_bull["score"] >= 75.0 and best_rr >= cfg["min_rr_net"]:
        return {
            "key": "BUY_ON_WEAKNESS",
            "label": "BUY ON WEAKNESS / ACCUMULATE IN DEMAND ZONE",
            "conviction": "MEDIUM_HIGH",
            "best_setup": best_bull["name"],
            "trade_plan": best_bull["params"],
        }

    if comp >= 40.0 and best_bull["score"] >= 70.0 and best_rr >= cfg["min_rr_net"] and best_bull["params"].get("status") in ("READY", "WAIT_TRIGGER"):
        return {
            "key": "WAIT_FOR_TRIGGER",
            "label": "WATCHLIST KETAT: TUNGGU KONFIRMASI REVERSAL / SPECULATIVE SUPPORT",
            "conviction": "TACTICAL_MEAN_REVERSION",
            "best_setup": best_bull["name"],
            "trade_plan": best_bull["params"],
        }

    if trap_setup["score"] >= 75.0:
        return {
            "key": "AVOID_DISTRIBUTION",
            "label": "HINDARI: DISTRIBUSI SIKLUS / MARKDOWN BELUM SELESAI",
            "conviction": "LOW",
            "best_setup": trap_setup["name"],
            "trade_plan": trap_setup["params"],
        }

    return {
        "key": "WAIT",
        "label": "WAIT & SEE (BELUM ADA EDGE SWING 1-2 MINGGU)",
        "conviction": "NEUTRAL",
        "best_setup": best_bull["name"],
        "trade_plan": best_bull["params"],
    }


def analyze_swing_stock(
    historical_source: Any,
    trade_book_source: Any,
    market_detector_source: Any = None,
    running_trade_chart_source: Any = None,
    broker_distribution_source: Any = None,
    ticker: str = "TICKER",
    cfg_override: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    cfg = {**SWING_CFG, "weights": dict(SWING_CFG["weights"])}
    if cfg_override:
        cfg.update(cfg_override)

    bars = load_historical_csv(historical_source)
    l1 = compute_layer1_price(bars, cfg)
    l2 = compute_layer2_orderflow(trade_book_source, bars)
    l3 = compute_layer3_bandar(market_detector_source, l1["ohlc"]["close"])
    l4 = compute_layer4_trajectory(running_trade_chart_source, l3)
    l5 = compute_layer5_network(broker_distribution_source, l3)

    l3_public = {k: v for k, v in l3.items() if not k.startswith("_")}

    score_data = combine_swing_score(l1, l2, l3_public, l4, l5, cfg)
    setups = eval_swing_setups(l1, l2, l3_public, l4, l5, cfg)
    action = decide_swing_action(score_data, l1, l2, setups, cfg)

    return {
        "ticker": ticker.strip().upper(),
        "date": l1["date"],
        "horizon": "1 - 2 Weeks (5 - 10 Trading Days)",
        "swing_score": score_data["composite_score"],
        "active_layers": score_data["active_layers"],
        "layer_scores": score_data["breakdown"],
        "action": {
            "key": action["key"],
            "label": action["label"],
            "conviction": action["conviction"],
            "best_setup": action["best_setup"],
        },
        "trade_plan": action["trade_plan"],
        "ohlc": l1["ohlc"],
        "moving_averages": l1["moving_averages"],
        "trend_vcp": l1["volatility_liquidity"],
        "levels": {
            "daily_vwap": l1["ohlc"]["average_vwap"],
            "avwap_swing_low": l2["anchored_from_swing_low"]["avwap_swing_low"],
            "vpoc_10d": l1["volume_profile"]["vp_curr_10d"]["vpoc"],
            "val_10d": l1["volume_profile"]["vp_curr_10d"]["val"],
            "vah_10d": l1["volume_profile"]["vp_curr_10d"]["vah"],
            "vpoc_20d": l1["volume_profile"]["vp_20d"]["vpoc"],
            "val_20d": l1["volume_profile"]["vp_20d"]["val"],
            "vah_20d": l1["volume_profile"]["vp_20d"]["vah"],
            "vpoc_60d": l1["volume_profile"]["vp_60d"]["vpoc"],
            "va_migration": l1["volume_profile"]["va_migration"],
            "swing_low_22d": l1["volume_profile"]["swing_low_22d"],
            "swing_low_date": l1["volume_profile"]["swing_low_date"],
            "swing_high_22d": l1["volume_profile"]["swing_high_22d"],
            "swing_high_date": l1["volume_profile"]["swing_high_date"],
            "high_10d": l1["volume_profile"]["high_10d"],
            "low_10d": l1["volume_profile"]["low_10d"],
        },
        "order_flow": l2,
        "bandar_structure": l3_public,
        "broker_trajectory": l4,
        "broker_network": l5,
        "setups": setups,
        "flags": l1["flags"],
    }
