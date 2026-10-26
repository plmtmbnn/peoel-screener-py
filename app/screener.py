#!/usr/bin/env python3
"""
════════════════════════════════════════════════════════════════════════════════
 INTRADAY SCREENER & TAPE READING SCANNER BEI v3.1
 Engine Mikrostruktur Berdasarkan 10 Arketipe Saham Bursa Efek Indonesia
 (FastAPI & CLI Ready - 100% Tape Reading & Order Book Mechanics)
════════════════════════════════════════════════════════════════════════════════

Fitur Utama:
1. Dual-File Ingestion (CSV Running Trade + JSON Trade-Book/Order Trade Chart)
   Mendukung file path maupun objek dictionary/list langsung untuk FastAPI.
2. 10 Arketipe Pasar BEI Teruji:
   - Growth Markup (VKTR / BUVA)
   - Low-Float ARA Lock (ASLI)
   - Lightning Rocket & Churn (FORU)
   - Staircase Precision (MBMA / KETR)
   - Nimble Skirmish (OASA)
   - Whale Bazooka War (BRMS)
   - Range-Bound Squeeze (PTRO / DOOH)
   - Distribution Blue Chip (AMRT / SMIL)
   - Speculative Collapse (STRK)
3. 8 Setup Playbook Intraday Lengkap:
   - Checkpoint Terpenuhi vs Pending
   - Area Entry, Stop Loss, TP1, TP2
   - RRR Gross & Net (dipotong estimasi fee broker 0.40% round-trip)
   - Peringatan EXTENDED / STALE: Mencegah FOMO HAKA di pucuk
4. Deteksi Anomali Mikrostruktur:
   - False Bullish Trap (antrean bid tebal / iceberg sell)
   - TWAP Slicing Distribution
   - High Volume Churning
   - Twin Sweep Berurutan
   - Bearish Waterfall Collapse
5. Konteks Scalping Modern:
   - VWAP & Value Area 70% (VAL / VAH)
   - Opening Range Breakout (ORB 15-Menit)
   - Delta Flow 15 Menit Terakhir & Kecepatan Tape (Speed of Tape)
   - Batas ARA / ARB Simetris BEI

Usage CLI:
  Single : python screener.py <running_trade.csv> <trade_book.json> [--ticker KODE] [--json]
  Batch  : python screener.py --scan <folder> [--csv-out hasil.csv]
"""

import argparse
import bisect
import csv
import glob
import json
import math
import os
import re
import sys
from collections import Counter, defaultdict

try:  # UTF-8 aman di terminal Windows / Linux / pipe
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

# ═══════════════════════════════════════════════════════════════
#  CONFIG
# ═══════════════════════════════════════════════════════════════

CFG = {
    'fee_buy_pct': 0.15,       # fee beli broker (%), sesuaikan broker Anda
    'fee_sell_pct': 0.25,      # fee jual broker + levy + PPh (%)
    'block_mode': 'adaptive',  # 'adaptive' (berbasis nominal Rp) | 'fixed' (50k lot)
    'fixed_block_lot': 50000,
    'block_value': 1e9,        # nilai Rp parent order yang dianggap "blok institusi" (~Rp 1 Miliar)
    'block_vol_pct': 1.0,      # ... atau minimal 1% volume sesi berjalan
    'recent_min': 15,          # jendela pemantauan kondisi terkini (menit)
    'hot_min': 15,             # batas waktu sweep dianggap segar (menit)
    'chase_ticks': 2,          # toleransi harga di atas entry zone sebelum dianggap EXTENDED
    'twin_coord_sec': 60,      # batas waktu antar-sweep terkoordinasi (detik)
    'vpoc_min_pct': 8.0,       # persentase minimal VPOC dianggap dominan
    # Batas ARA simetris BEI berdasarkan prev close
    'ara_bands': [(200, 35.0), (5000, 25.0), (float('inf'), 20.0)],
    'arb_pct': 15.0,           # batas ARB simetris
}

CONT_START = 9 * 3600              # 09:00:00 (Awal sesi kontinu)
CONT_END = 15 * 3600 + 50 * 60     # 15:50:00 (Akhir sesi kontinu, sebelum closing auction)

# Batas bucket interval waktu kontinu (menit sejak 00:00)
BUCKET_EDGES = [540, 545, 555, 570, 600, 630, 660, 690, 720, 750, 780, 810,
                840, 870, 900, 930, 950]

# ═══════════════════════════════════════════════════════════════
#  HELPERS & FRAKSI HARGA BEI
# ═══════════════════════════════════════════════════════════════

def pi(s, default=0):
    """Parse int toleran: '1,234' '12%' '-' None -> int."""
    if s is None:
        return default
    if isinstance(s, bool):
        return int(s)
    if isinstance(s, (int, float)):
        return int(s)
    s = str(s).replace(',', '').replace(' ', '').replace('%', '').strip()
    if s in ('', '-', 'None', 'null'):
        return default
    try:
        return int(s)
    except ValueError:
        try:
            return int(float(s))
        except ValueError:
            return default


def raw(obj, default=0):
    """Ambil nilai 'raw' dari objek JSON {'raw':..,'formatted':..}."""
    if isinstance(obj, dict):
        return pi(obj.get('raw'), default)
    return pi(obj, default)


def fmt(n):
    if n is None:
        return "-"
    a = abs(n)
    if a >= 1e12: return f"{n/1e12:.2f}T"
    if a >= 1e9:  return f"{n/1e9:.2f}B"
    if a >= 1e6:  return f"{n/1e6:.2f}M"
    return f"{n:,.0f}"


def pct(n, d):
    return n / d * 100 if d else 0.0


def bar(pct_val, width=10):
    filled = min(max(int(pct_val / (100 / width)), 0), width)
    return '█' * filled + '░' * (width - filled)


def to_sec(ts):
    p = str(ts).strip().split(':')
    h = int(p[0]); mi = int(p[1]) if len(p) > 1 else 0; s = int(p[2]) if len(p) > 2 else 0
    return h * 3600 + mi * 60 + s


def hms(sec):
    return f"{sec // 3600:02d}:{(sec % 3600) // 60:02d}:{sec % 60:02d}"


def tick_size(price):
    """Fraksi harga resmi Bursa Efek Indonesia."""
    if price < 200: return 1
    if price < 500: return 2
    if price < 2000: return 5
    if price < 5000: return 10
    return 25


def step(price, n):
    """Geser harga sebanyak n tick (negatif = turun) sesuai fraksi BEI."""
    p = price
    for _ in range(abs(n)):
        if n > 0:
            p += tick_size(p)
        else:
            p -= tick_size(p - 1)
    return max(p, 1)


def ticks_between(a, b):
    """Jumlah fraksi tick dari a ke b (positif jika b > a)."""
    if a == b:
        return 0
    sign = 1 if b > a else -1
    lo, hi = (a, b) if b > a else (b, a)
    n, p = 0, lo
    while p < hi and n < 100000:
        p += tick_size(p)
        n += 1
    return sign * n


def round_down_tick(price):
    t = tick_size(price)
    return int(price // t * t)


def round_up_to(price, stepv):
    return int(math.ceil(price / stepv) * stepv)


def psych_step(price):
    """Kelipatan level psikologis / angka bulat berdasarkan fraksi."""
    if price < 100: return 10
    if price < 500: return 50
    if price < 2000: return 100
    if price < 5000: return 250
    return 500


def ara_pct_for(prev):
    for lim, p in CFG['ara_bands']:
        if prev <= lim:
            return p
    return 20.0


# ═══════════════════════════════════════════════════════════════
#  PASANGAN FILE & RESOLUSI TICKER
# ═══════════════════════════════════════════════════════════════

_MARKERS = re.compile(
    r'(running[-_ ]?trade|trade[-_ ]?book|order[-_ ]?trade[-_ ]?chart|order[-_ ]?trade|chart)[-_ ]*',
    re.I
)

def pair_key(path):
    """
    Kunci pasangan file = nama file setelah label descriptor dibersihkan.
    Mendukung format awalan (running-trade_PTRO_...) maupun akhiran (ptro_running_trade.csv).
    """
    stem = os.path.splitext(os.path.basename(path))[0]
    cleaned = _MARKERS.sub('', stem).strip('-_ .').lower()
    return cleaned or stem.lower()


def clean_ticker_label(key, fallback="-"):
    """Ambil kode 4 huruf bersih jika tersedia dari nama pasangan file."""
    if not key or key == "-":
        return fallback
    m = re.search(r'\b([A-Za-z]{4})\b', key)
    if m:
        return m.group(1).upper()
    return key.split('_')[0].split('-')[0].upper() or fallback


def resolve_ticker(override=None, fallback="-"):
    """
    Ticker ditentukan dari parameter eksplisit (FastAPI payload / arg CLI).
    Jika tidak dikirim, gunakan fallback.
    """
    return override.strip().upper() if override and override.strip() else fallback


# ═══════════════════════════════════════════════════════════════
#  DATA LOADING (FASTAPI & FILE PATH SUPPORT)
# ═══════════════════════════════════════════════════════════════

REQUIRED_COLS = {'time', 'action', 'price', 'lot'}

def load_trades(source):
    """
    Memuat data Running Trade dari file path CSV atau list-of-dict langsung.
    100% independen tanpa kode broker dan tanpa tipe investor.
    """
    rows, bad = [], 0
    if isinstance(source, list):
        raw_rows = source
    else:
        with open(source, 'r', encoding='utf-8-sig', newline='') as f:
            rd = csv.DictReader(f)
            missing = REQUIRED_COLS - set(rd.fieldnames or [])
            if missing:
                raise ValueError(f"Kolom CSV wajib tidak ada: {sorted(missing)}")
            raw_rows = list(rd)

    for r in raw_rows:
        try:
            act = (r.get('action') or '').strip().lower()
            if act not in ('buy', 'sell'):
                bad += 1
                continue
            p, lot = pi(r.get('price')), pi(r.get('lot'))
            if p <= 0 or lot <= 0:
                bad += 1
                continue
            rows.append({
                't': str(r.get('time')).strip(),
                's': to_sec(r.get('time')),
                'act': act,
                'p': p,
                'lot': lot,
                'tn': pi(r.get('trade_number')),
                'bon': pi(r.get('buy_order_number')),
                'son': pi(r.get('sell_order_number')),
                'gon': pi(r.get('group_order_number')),
                'amt': pi(r.get('amount')) or p * lot * 100,
                'chg': str(r.get('change') or '').strip(),
            })
        except (ValueError, KeyError, IndexError):
            bad += 1

    rows.sort(key=lambda t: (t['s'], t['tn']))
    return rows


def load_json(source):
    """Memuat data Order Trade / Trade-Book dari file path JSON atau dict langsung."""
    if isinstance(source, dict):
        d = source
    else:
        with open(source, 'r', encoding='utf-8') as f:
            d = json.load(f)
    return d.get('data', d) if isinstance(d, dict) else {}


def parse_chg(s):
    if not s:
        return None
    m = re.search(r'[-+\u2212]?\d+(?:\.\d+)?', s.replace(',', '.'))
    if not m:
        return None
    try:
        return float(m.group(0).replace('\u2212', '-'))
    except ValueError:
        return None


def estimate_prev_close(trades, fallback):
    """Estimasi harga penutupan kemarin (prev close) dari tape running trade."""
    pairs = Counter((t['p'], t['chg']) for t in trades if t['chg'])
    votes = Counter()
    for (p, chg), n in pairs.most_common(80):
        v = parse_chg(chg)
        if v is None or v <= -100:
            continue
        if v == 0:
            votes[p] += n
            continue
        est = p / (1 + v / 100)
        for cand in range(int(est) - 1, int(est) + 3):
            if cand > 0 and abs(round((p / cand - 1) * 100, 2) - v) < 0.006:
                votes[cand] += n
    return votes.most_common(1)[0][0] if votes else fallback


def block_lot(price, cont_lot):
    """
    Kalkulasi ambang blok adaptif:
    Menyesuaikan ukuran lot institusi berdasarkan nominal rupiah (~Rp 1 Miliar).
    """
    if CFG['block_mode'] == 'fixed':
        return CFG['fixed_block_lot']
    by_val = CFG['block_value'] / (max(price, 1) * 100)
    by_vol = CFG['block_vol_pct'] / 100 * cont_lot
    b = max(by_val, by_vol, 500)
    mag = 10 ** int(math.log10(b))
    return int(round(b / (mag / 2)) * (mag / 2))


def value_area(vp, vpoc, target=0.70):
    """Kalkulasi 70% Value Area (VAL dan VAH) di sekitar VPOC."""
    levels = sorted(vp)
    total = sum(v['lot'] for v in vp.values())
    if not levels or vpoc not in vp or total == 0:
        return vpoc, vpoc
    i = levels.index(vpoc)
    lo = hi = i
    acc = vp[vpoc]['lot']
    while acc < total * target and (lo > 0 or hi < len(levels) - 1):
        up = vp[levels[hi + 1]]['lot'] if hi + 1 < len(levels) else -1
        dn = vp[levels[lo - 1]]['lot'] if lo > 0 else -1
        if up >= dn:
            hi += 1; acc += up
        else:
            lo -= 1; acc += dn
    return levels[lo], levels[hi]


# ═══════════════════════════════════════════════════════════════
#  CORE METRICS & MIKROSTRUKTUR TAPE READING
# ═══════════════════════════════════════════════════════════════

def compute_all(trades, jd):
    if not trades:
        raise ValueError("Data running trade kosong")
    m = {}

    pre = [t for t in trades if t['s'] < CONT_START]
    cont = [t for t in trades if CONT_START <= t['s'] < CONT_END]
    post = [t for t in trades if t['s'] >= CONT_END]
    if not cont:
        cont = trades

    m['n_pre'], m['n_cont'], m['n_post'] = len(pre), len(cont), len(post)
    m['is_live'] = not post
    m['date'] = jd.get('date') or jd.get('from') or ''
    m['now'] = cont[-1]['t']
    m['now_s'] = cont[-1]['s']
    jb = jd.get('buy') or []
    m['sync_warn'] = None
    if jb and jb[-1].get('time'):
        try:
            gap = abs(to_sec(jb[-1]['time']) - trades[-1]['s'] // 60 * 60)
            if gap > 180:
                m['sync_warn'] = f"JSON berakhir {jb[-1]['time']} vs CSV {trades[-1]['t']} - selisih ekspor data > 3 menit"
        except ValueError:
            pass

    # --- OHLC Sesi Kontinu ---
    m['open'] = cont[0]['p']
    m['auction_open'] = pre[-1]['p'] if pre else None
    m['high'] = max(t['p'] for t in cont)
    m['low'] = min(t['p'] for t in cont)
    m['last'] = cont[-1]['p']
    m['close'] = post[0]['p'] if post else m['last']
    m['range_pct'] = pct(m['high'] - m['low'], m['low'])
    m['change_pct'] = pct(m['close'] - m['open'], m['open'])
    m['tick'] = tick_size(m['close'])
    m['tick_pct'] = pct(m['tick'], m['close'])
    m['range_ticks'] = ticks_between(m['low'], m['high'])

    prev = estimate_prev_close(trades, m['auction_open'] or m['open'])
    m['prev_close'] = prev
    m['close_vs_prev'] = pct(m['close'] - prev, prev)
    m['gap_pct'] = pct(m['open'] - prev, prev)
    ap = ara_pct_for(prev)
    m['ara'] = round_down_tick(prev * (1 + ap / 100))
    m['arb'] = int(math.ceil(prev * (1 - CFG['arb_pct'] / 100) / tick_size(prev * 0.85)) * tick_size(prev * 0.85))
    m['at_ara'] = m['close'] >= step(m['ara'], -1)
    m['at_arb'] = m['close'] <= step(m['arb'], 1)

    # --- Akumulasi Volume & Turnover ---
    m['buy_lot'] = sum(t['lot'] for t in trades if t['act'] == 'buy')
    m['sell_lot'] = sum(t['lot'] for t in trades if t['act'] == 'sell')
    m['total_lot'] = m['buy_lot'] + m['sell_lot']
    m['buy_val'] = sum(t['amt'] for t in trades if t['act'] == 'buy')
    m['sell_val'] = sum(t['amt'] for t in trades if t['act'] == 'sell')
    m['total_val'] = m['buy_val'] + m['sell_val']
    m['buy_pct'] = pct(m['buy_lot'], m['total_lot'])
    m['total_freq'] = len(trades)
    m['c_lot'] = sum(t['lot'] for t in cont)
    m['c_buy'] = sum(t['lot'] for t in cont if t['act'] == 'buy')
    m['c_sell'] = m['c_lot'] - m['c_buy']
    m['c_delta'] = m['c_buy'] - m['c_sell']
    m['c_val'] = sum(t['amt'] for t in cont)
    m['vwap'] = round(m['c_val'] / (m['c_lot'] * 100), 2) if m['c_lot'] else m['close']
    m['close_vs_vwap'] = pct(m['close'] - m['vwap'], m['vwap'])

    # Ambang blok adaptif
    m['block'] = block_lot(m['vwap'], m['c_lot'])
    B = m['block']

    # --- Volume Profile (kontinu) & VPOC & Value Area ---
    vp = {}
    for t in cont:
        v = vp.setdefault(t['p'], {'lot': 0, 'buy': 0, 'sell': 0, 'freq': 0})
        v['lot'] += t['lot']; v['freq'] += 1; v[t['act']] += t['lot']
    m['vp'] = vp
    vpoc = max(vp, key=lambda p: (vp[p]['lot'], -abs(p - m['vwap'])))
    m['vpoc'] = vpoc
    m['vpoc_lot'] = vp[vpoc]['lot']
    m['vpoc_pct'] = pct(vp[vpoc]['lot'], m['c_lot'])
    m['val'], m['vah'] = value_area(vp, vpoc)
    mid_ticks = [step(vpoc, -1), vpoc, step(vpoc, 1)]
    m['mid_conc'] = pct(sum(vp[p]['lot'] for p in mid_ticks if p in vp), m['c_lot'])

    # Range-bound compression (PTRO / DOOH)
    compressed = m['range_pct'] <= 5.0 or (m['range_ticks'] <= 8 and m['range_pct'] <= 10.0)
    m['compressed'] = compressed
    m['is_range_bound'] = compressed and abs(m['change_pct']) <= 2.0 and m['c_val'] >= 15e9

    # --- Zero-Ask Low (kontinu) ---
    low_p = m['low']
    lv = vp.get(low_p, {'lot': 0, 'buy': 0, 'sell': 0})
    low_trades = [t for t in cont if t['p'] == low_p]
    last_low = low_trades[-1] if low_trades else cont[0]
    first_low = low_trades[0] if low_trades else cont[0]
    post_low = [t for t in cont if (t['s'], t['tn']) > (last_low['s'], last_low['tn'])]
    rec_thr = step(low_p, 2)
    m['zal'] = {
        'level': low_p, 'lot': lv['lot'], 'buy': lv['buy'], 'sell': lv['sell'],
        'buy_ratio': pct(lv['buy'], lv['lot']), 'is_zero': lv['buy'] == 0,
        'is_near_zero': pct(lv['buy'], lv['lot']) < 5.0,
        'recovered': any(t['p'] >= rec_thr for t in post_low),
        'recovery_high': max((t['p'] for t in post_low), default=low_p),
        'last_t': last_low['t'], 'last_s': last_low['s'], 'first_s': first_low['s'],
        'held_min': (m['now_s'] - last_low['s']) / 60.0,
    }

    # --- Big Money RT (cumulative per menit dari JSON) ---
    bm_rt = jd.get('big_money_rt', {}) or {}
    bm_rt_buy, bm_rt_sell = bm_rt.get('buy', []) or [], bm_rt.get('sell', []) or []
    cum_b = [raw(x.get('lot')) for x in bm_rt_buy]
    cum_s = [raw(x.get('lot')) for x in bm_rt_sell]
    tgt_b = cum_b[-1] if cum_b else 0
    tgt_s = cum_s[-1] if cum_s else 0

    th_lo = th_hi = None
    if tgt_b > 0 or tgt_s > 0:
        buy_asc = sorted(t['lot'] for t in trades if t['act'] == 'buy')
        sell_asc = sorted(t['lot'] for t in trades if t['act'] == 'sell')
        buy_sfx = [0] * (len(buy_asc) + 1)
        for i in range(len(buy_asc) - 1, -1, -1):
            buy_sfx[i] = buy_sfx[i + 1] + buy_asc[i]
        sell_sfx = [0] * (len(sell_asc) + 1)
        for i in range(len(sell_asc) - 1, -1, -1):
            sell_sfx[i] = sell_sfx[i + 1] + sell_asc[i]
        cands = set()
        for c in set(t['lot'] for t in trades):
            cands.add(c); cands.add(c + 1)
        matches = []
        for th in sorted(cands):
            bs = buy_sfx[bisect.bisect_left(buy_asc, th)]
            ss = sell_sfx[bisect.bisect_left(sell_asc, th)]
            if bs == tgt_b and ss == tgt_s:
                matches.append(th)
            elif bs < tgt_b and ss < tgt_s:
                break
        if matches:
            th_lo, th_hi = min(matches), max(matches)
    m['bm_rt_th'] = th_lo
    m['bm_rt_th_hi'] = th_hi
    m['bm_rt_buy'], m['bm_rt_sell'], m['bm_rt_net'] = tgt_b, tgt_s, tgt_b - tgt_s

    # BM-RT terkini (N menit terakhir)
    N = CFG['recent_min']
    if len(cum_b) > N and len(cum_s) > N:
        rb = cum_b[-1] - cum_b[-1 - N]
        rs = cum_s[-1] - cum_s[-1 - N]
    else:
        rb, rs = tgt_b, tgt_s
    m['bm_recent'] = {'buy': rb, 'sell': rs, 'net': rb - rs}

    # --- Big Money Divergence & Trap Detection ---
    bt = jd.get('book_total', {}) or {}
    bm_b = pi(bt.get('big_money_buy_percentage'))
    bm_s = pi(bt.get('big_money_sell_percentage'))
    brt = bt.get('big_money_rt')
    brt_pct = (brt.get('percentage') if isinstance(brt, dict) else None) or {}
    bmrt_b, bmrt_s = pi(brt_pct.get('buy')), pi(brt_pct.get('sell'))
    m['bm_div'] = {
        'bm_buy': bm_b, 'bm_sell': bm_s, 'bmrt_buy': bmrt_b, 'bmrt_sell': bmrt_s,
        'bm_bull': bm_b > bm_s, 'bmrt_bull': bmrt_b > bmrt_s,
        'divergent': (bm_b > bm_s) != (bmrt_b > bmrt_s),
        'false_bull': (bm_b > bm_s and bmrt_s > bmrt_b) or (bm_b > 50 and m['change_pct'] < -1.5),
        'false_bear': (bm_s > bm_b and bmrt_b > bmrt_s) or (bm_s > 50 and m['change_pct'] > 5.0),
    }

    # --- Interval Waktu Kontinu ---
    def bucket_idx(sec):
        mn = sec // 60
        i = bisect.bisect_right(BUCKET_EDGES, mn) - 1
        return min(max(i, 0), len(BUCKET_EDGES) - 2)

    grp = defaultdict(list)
    for t in cont:
        grp[bucket_idx(t['s'])].append(t)
    ivs = []
    for i in sorted(grp):
        sub = grp[i]
        a, b = BUCKET_EDGES[i], BUCKET_EDGES[i + 1]
        iv = {
            'label': f"{a // 60:02d}:{a % 60:02d}-{b // 60:02d}:{b % 60:02d}",
            'o': sub[0]['p'], 'h': max(t['p'] for t in sub), 'l': min(t['p'] for t in sub),
            'c': sub[-1]['p'],
            'b_lot': sum(t['lot'] for t in sub if t['act'] == 'buy'),
            's_lot': sum(t['lot'] for t in sub if t['act'] == 'sell'), 'n': len(sub),
        }
        iv['delta'] = iv['b_lot'] - iv['s_lot']
        ivs.append(iv)
    m['intervals'] = ivs

    # --- Per-menit: cumulative delta & activity ---
    by_min = defaultdict(list)
    for t in cont:
        by_min[t['t'][:5]].append(t)
    m['active_min'] = len(by_min)
    cd, run = [], 0
    for k in sorted(by_min):
        run += sum(t['lot'] if t['act'] == 'buy' else -t['lot'] for t in by_min[k])
        cd.append((k, run))
    m['cum_delta'] = cd

    # --- Kondisi Terkini (Flow 15 Menit & Speed of Tape) ---
    w0 = m['now_s'] - CFG['recent_min'] * 60
    rec = [t for t in cont if t['s'] > w0] or cont[-1:]
    rb_lot = sum(t['lot'] for t in rec if t['act'] == 'buy')
    rs_lot = sum(t['lot'] for t in rec if t['act'] == 'sell')
    avg_rate = len(cont) / max(m['active_min'], 1)
    rec_rate = len(rec) / max(CFG['recent_min'], 1)
    rng = max(m['high'] - m['low'], 1)
    near_high = m['last'] >= m['high'] - rng * 0.10
    near_low = m['last'] <= m['low'] + rng * 0.10
    m['recent'] = {
        'minutes': CFG['recent_min'], 'n': len(rec), 'delta': rb_lot - rs_lot,
        'buy_pct': pct(rb_lot, rb_lot + rs_lot),
        'price_chg': pct(rec[-1]['p'] - rec[0]['p'], rec[0]['p']),
        'p_from': rec[0]['p'], 'p_to': rec[-1]['p'],
        'speed': (rec_rate / avg_rate) if avg_rate else 0.0,
        'near_high': near_high, 'near_low': near_low,
        'bear_div': near_high and (rb_lot - rs_lot) < 0,
        'bull_div': near_low and (rb_lot - rs_lot) > 0,
        'gap_min': (CONT_END - m['now_s']) / 60.0 if m['is_live'] else 0.0,
    }

    # --- Opening Range Breakout (ORB 09:00 - 09:15) ---
    orr = [t for t in cont if t['s'] < CONT_START + 15 * 60]
    if orr and m['now_s'] > CONT_START + 15 * 60:
        orh, orl = max(t['p'] for t in orr), min(t['p'] for t in orr)
        brk_up = next((t for t in cont if t['s'] >= CONT_START + 15 * 60 and t['p'] > orh), None)
        brk_dn = next((t for t in cont if t['s'] >= CONT_START + 15 * 60 and t['p'] < orl), None)
        st = 'BREAKOUT ATAS' if m['last'] > orh else ('BREAKDOWN' if m['last'] < orl else 'DI DALAM RANGE')
        m['orb'] = {'high': orh, 'low': orl, 'status': st,
                    'up_t': brk_up['t'] if brk_up else None, 'dn_t': brk_dn['t'] if brk_dn else None}
    else:
        m['orb'] = None

    # --- Rekonstruksi Parent Order ---
    def new_parent():
        return {'lot': 0, 'fills': 0, 'prices': set(), 'agg': 0, 'pas': 0,
                'first': None, 'last': None, 'first_s': 0, 'last_s': 0, 'agg_prices': set()}

    buy_parents, sell_parents = defaultdict(new_parent), defaultdict(new_parent)

    def feed(par, t, side):
        par['lot'] += t['lot']; par['fills'] += 1; par['prices'].add(t['p'])
        if par['first'] is None:
            par['first'], par['first_s'] = t['t'], t['s']
        par['last'], par['last_s'] = t['t'], t['s']
        if t['act'] == side:
            par['agg'] += t['lot']; par['agg_prices'].add(t['p'])
        else:
            par['pas'] += t['lot']

    for t in trades:
        feed(buy_parents[t['bon']], t, 'buy')
        feed(sell_parents[t['son']], t, 'sell')

    def nature(p):
        if p['agg'] > 0 and p['pas'] == 0: return "AGG"
        if p['pas'] > 0 and p['agg'] == 0: return "PAS"
        return "HYB"

    bp = sorted(buy_parents.items(), key=lambda x: x[1]['lot'], reverse=True)
    sp = sorted(sell_parents.items(), key=lambda x: x[1]['lot'], reverse=True)
    m['bp'], m['sp'] = bp, sp
    m['bp_nature'] = [(k, v, nature(v)) for k, v in bp]
    m['sp_nature'] = [(k, v, nature(v)) for k, v in sp]
    m['top_buy_lot'] = bp[0][1]['lot'] if bp else 0
    m['top_sell_lot'] = sp[0][1]['lot'] if sp else 0

    # Penyerapan di area VPOC oleh bid pasif institusi
    def absorb_at_vpoc(min_lot):
        ids = {k for k, v in bp if v['lot'] >= min_lot}
        return sum(t['lot'] for t in cont if t['p'] == vpoc and t['act'] == 'sell' and t['bon'] in ids)
    m['vpoc_abs_mid'] = absorb_at_vpoc(0.10 * B)
    m['vpoc_abs_small'] = absorb_at_vpoc(0.02 * B)

    # --- Pola Tangga Naik (Staircase) ---
    first_ivs = ivs
    closes = [iv['c'] for iv in first_ivs]
    npairs = max(len(closes) - 1, 1)
    asc_pairs = sum(1 for i in range(1, len(closes)) if closes[i] > closes[i - 1])
    flat_pairs = sum(1 for i in range(1, len(closes)) if closes[i] == closes[i - 1])
    net_prog = len(closes) > 1 and closes[-1] > closes[0]
    asc_ratio = pct(asc_pairs + flat_pairs * 0.5, npairs) if len(closes) > 1 else 0
    steps_up = sum(1 for iv in first_ivs if iv['c'] > iv['o'])
    is_staircase = (asc_ratio >= 60.0 and steps_up >= 2 and net_prog
                    and m['change_pct'] >= 2.0 and not m['is_range_bound'])
    m['staircase'] = {'is': is_staircase, 'steps': steps_up,
                      'asc': asc_ratio >= 60.0 and net_prog, 'asc_ratio': asc_ratio}

    # --- Pola Twin Sweep Terkoordinasi ---
    sweeps = [{'k': k, 'lot': v['lot'], 'first_s': v['first_s'], 'last_s': v['last_s'],
               'last': v['last'], 'first': v['first'],
               'levels': len(v['agg_prices']), 'base': min(v['agg_prices']) if v['agg_prices'] else min(v['prices'])}
              for k, v, n in m['bp_nature'] if v['lot'] >= B and n == 'AGG']
    coord = seq = 0
    for i, a in enumerate(sweeps):
        for b in sweeps[i + 1:]:
            if abs(a['first_s'] - b['first_s']) <= CFG['twin_coord_sec']:
                coord += 1
            if abs(a['k'] - b['k']) < 200:
                seq += 1
    last_sweep = max(sweeps, key=lambda x: x['last_s']) if sweeps else None
    m['twin_sweep'] = {
        'found': len(sweeps) >= 2, 'count': len(sweeps), 'coord': coord, 'seq': seq,
        'multi_level': any(s['levels'] >= 2 for s in sweeps),
        'last': last_sweep,
        'age_min': (m['now_s'] - last_sweep['last_s']) / 60.0 if last_sweep else None,
    }

    # --- Selling Climax & V-Shape Reversal ---
    big_agg_sells = [(k, v) for k, v, n in m['sp_nature'] if v['lot'] >= B and n == 'AGG']
    sell_per_min = defaultdict(int)
    for t in cont:
        if t['act'] == 'sell':
            sell_per_min[t['t'][:5]] += t['lot']
    peak_min = max(sell_per_min, key=sell_per_min.get) if sell_per_min else ''
    m['climax'] = {'bazookas': len(big_agg_sells), 'peak_min': peak_min,
                   'peak_vol': sell_per_min.get(peak_min, 0)}

    hi_before = max((t['p'] for t in cont if t['s'] <= m['zal']['first_s']), default=m['open'])
    drop = hi_before - m['low']
    after_high = max((t['p'] for t in post_low), default=m['low'])
    retr = (after_high - m['low']) / drop if drop > 0 else 0.0
    m['vshape'] = {'drop_pct': pct(drop, hi_before), 'retrace': retr * 100,
                   'found': pct(drop, hi_before) >= 3.0 and retr >= 0.5}

    # --- Waterfall Dump Collapse ---
    first_5 = [t for t in cont if t['s'] < CONT_START + 5 * 60]
    haki_5 = pct(sum(t['lot'] for t in first_5 if t['act'] == 'sell'), sum(t['lot'] for t in first_5)) if first_5 else 0
    declining = len(ivs) >= 3 and all(iv['c'] <= iv['o'] for iv in ivs[:3])
    m['waterfall'] = {
        'found': (declining or m['change_pct'] < -10) and (haki_5 > 60 or m['change_pct'] < -15),
        'declining': declining, 'haki_5': haki_5}

    # --- TWAP Slicing Distribution ---
    min_lot = max(0.05 * B, 500)
    clusters = defaultdict(list)
    for k, v in m['sp']:
        if v['lot'] >= min_lot:
            clusters[round(math.log(v['lot']) / math.log(1.04))].append(v)
    best = max(clusters.values(), key=len) if clusters else []
    spread_min = (max(v['first_s'] for v in best) - min(v['first_s'] for v in best)) / 60 if best else 0
    m['twap'] = {'found': len(best) >= 5 and spread_min >= 5, 'cluster': len(best),
                 'size': int(sum(v['lot'] for v in best) / len(best)) if best else 0,
                 'spread_min': spread_min}

    # --- Churning Distribution ---
    churn_mins, churn_vol, churn_top = 0, 0, 0
    vol_thr = max(1000, 0.002 * m['c_lot'])
    for minute, ts in by_min.items():
        if len(ts) < 10:
            continue
        pr = [t['p'] for t in ts]
        vol = sum(t['lot'] for t in ts)
        if ticks_between(min(pr), max(pr)) <= 1 and vol > vol_thr:
            churn_mins += 1; churn_vol += vol
            if min(pr) >= m['high'] - rng * 0.2:
                churn_top += 1
    m['churning'] = {'found': churn_mins >= 5 and churn_vol >= 0.15 * m['c_lot'],
                     'mins': churn_mins, 'vol': churn_vol, 'at_top': churn_top}

    # --- Level Psikologis Breakout ---
    stp = psych_step(m['vwap'])
    levels = [lv for lv in range(stp, 200000, stp) if m['low'] < lv <= m['high']]
    breakouts = []
    for L in levels:
        first_below = next((i for i, t in enumerate(cont) if t['p'] < L), None)
        up = first_below is not None and any(t['p'] > L for t in cont[first_below:])
        first_above = next((i for i, t in enumerate(cont) if t['p'] > L), None)
        down = first_above is not None and any(t['p'] < L for t in cont[first_above:])
        at_vol = sum(t['lot'] for t in cont if t['p'] == L)
        if (up or down) and at_vol > 0:
            breakouts.append({'level': L, 'vol': at_vol, 'up': up, 'down': down, 'held': m['last'] >= L})
    m['psych'] = {'found': any(b['up'] for b in breakouts), 'levels': [b for b in breakouts if b['up']],
                  'all': breakouts, 'step': stp}

    return m


# ═══════════════════════════════════════════════════════════════
#  EVALUASI CHECKPOINTS & PARAMETER RISK / REWARD
# ═══════════════════════════════════════════════════════════════

def fp(price, ref):
    return f"{price} ({pct(price - ref, ref):+.2f}%)"


def calc_rr(entry, sl, tp):
    """Kalkulasi RRR Gross dan Net (dipotong estimasi fee beli & fee jual)."""
    if not entry or entry <= 0:
        return {'gross': 0.0, 'net': 0.0, 'gain_pct': 0.0, 'risk_pct': 0.0}
    cost = CFG['fee_buy_pct'] + CFG['fee_sell_pct']
    gain, risk = pct(tp - entry, entry), pct(entry - sl, entry)
    gross = gain / risk if risk > 0 else 0.0
    net = max(gain - cost, 0) / (risk + cost) if (risk + cost) > 0 else 0.0
    return {'gross': gross, 'net': net, 'gain_pct': gain, 'risk_pct': risk}


def mk_params(m, status, e_lo, e_hi, sl, tp1, tp2, hold, trigger, actionable,
              sl_note='', tp1_note='', tp2_note='', entry_note='', tp2_text=None):
    rr = calc_rr(e_hi, sl, tp1)
    cost = CFG['fee_buy_pct'] + CFG['fee_sell_pct']
    warn = ' ⚠️ TP1 ≤ biaya transaksi' if rr['gain_pct'] <= cost else ''
    zone = f"{e_lo}" if e_lo == e_hi else f"{e_lo} - {e_hi}"
    live = ''
    if m['last'] > e_hi:
        if tp1 > m['last']:
            lr = calc_rr(m['last'], sl, tp1)
            live = f" | dari harga kini {m['last']}: 1 : {lr['gross']:.1f} (net {lr['net']:.1f})"
        else:
            live = f" | harga kini {m['last']} sudah melewati TP1"
    return {
        'status': status, 'actionable': actionable,
        'entry_zone': zone + (f" ({entry_note})" if entry_note else ''),
        'cut_loss': f"{fp(sl, e_hi)}{(' ' + sl_note) if sl_note else ''}",
        'tp1': f"{fp(tp1, e_hi)}{(' ' + tp1_note) if tp1_note else ''}",
        'tp2': tp2_text or f"{fp(tp2, e_hi)}{(' ' + tp2_note) if tp2_note else ''}",
        'rrr': f"1 : {rr['gross']:.1f} (gross) | 1 : {rr['net']:.1f} (net fee {cost:.2f}%){warn}{live}",
        'rr_gross': round(rr['gross'], 2), 'rr_net': round(rr['net'], 2),
        'entry_lo': e_lo, 'entry_hi': e_hi, 'sl': sl, 'tp1_px': tp1,
        'max_holding': hold, 'trigger_rule': trigger,
    }


def extended_ticks(m, e_hi):
    """Menghitung berapa tick harga terakhir berada di atas batas atas zona entry."""
    return max(ticks_between(e_hi, m['last']), 0)


def eval_setups(m):
    setups = []
    B = m['block']
    chase = CFG['chase_ticks']

    def new(i, name, typ, src):
        return {'id': i, 'name': name, 'type': typ, 'source_tickers': src,
                'checks_met': [], 'checks_pending': [], 'params': {}}

    def check(s, ok, met_txt, met_ev, pend_txt, pend_ev):
        if ok:
            s['checks_met'].append((met_txt, met_ev))
        else:
            s['checks_pending'].append((pend_txt, pend_ev))

    # ── SETUP 1: ZERO-ASK LOW REVERSAL ─────────────────────────
    z = m['zal']
    s1 = new(1, 'Zero-Ask Low Reversal', 'BULLISH REVERSAL', 'VKTR, BUVA, ASLI, DOOH, KETR')
    check(s1, z['last_s'] < CONT_START + 25 * 60,
          'Low sesi dicetak di pagi hari (< 09:25)', f"Low {z['level']} terakhir di {z['last_t']}",
          'Low sesi harus terbentuk di awal sesi (< 09:25)', f"Low terakhir terbentuk di {z['last_t']}")
    if z['is_zero']:
        s1['checks_met'].append((f"Level {z['level']} 100% HAKI / 0% HAKA (Zero-Ask)", f"Vol: {fmt(z['lot'])} lot, Buy: 0 lot"))
    elif z['is_near_zero']:
        s1['checks_met'].append((f"Level {z['level']} Near Zero-Ask (< 5% Buy)", f"Buy ratio: {z['buy_ratio']:.1f}%"))
    else:
        s1['checks_pending'].append(("Level Low harus didominasi HAKI (≈100%)", f"Buy ratio saat ini {z['buy_ratio']:.1f}%"))
    
    rebound_ticks = ticks_between(z['level'], z['recovery_high'])
    support_proven = z['held_min'] >= 5 or rebound_ticks >= 3
    check(s1, support_proven,
          'Low teruji sebagai support (bertahan ≥ 5 menit atau rebound ≥ 3 tick)',
          f"Bertahan {z['held_min']:.0f} menit / High {z['recovery_high']} (+{rebound_ticks} tick)",
          'Low harus teruji (bertahan ≥ 5 menit atau memantul ≥ 3 tick)',
          f"Baru {z['held_min']:.0f} menit sejak sentuhan terakhir")
    check(s1, z['recovered'],
          'Rebound konfirmasi ≥ 2 tick terbentuk', f"High paska low: {z['recovery_high']} (+{rebound_ticks} tick)",
          'Wajib rebound minimal +2 tick dari low', f"Menunggu pantulan ≥ {step(z['level'], 2)}")

    e_lo, e_hi = step(z['level'], 1), step(z['level'], 2)
    sl = step(z['level'], -1)
    tp1 = m['vpoc'] if m['vpoc'] > e_hi else step(e_hi, 3)
    tp2 = m['high'] if m['high'] > tp1 else step(tp1, 3)
    ext = extended_ticks(m, e_hi)
    ok_sig = (z['is_zero'] or z['is_near_zero']) and z['recovered']
    if ok_sig and ext <= chase:
        status, act = 'READY TO ENTER', True
    elif ok_sig:
        status, act = f'EXTENDED (+{ext} tick di atas zona) - TUNGGU PULLBACK', False
    else:
        status, act = 'WAITING TRIGGER', False
    s1['params'] = mk_params(
        m, status, e_lo, e_hi, sl, tp1, tp2, "45 - 60 menit",
        f"Entri beli saat harga re-test zona {e_lo}-{e_hi} dengan konfirmasi transaksi agresif", act,
        sl_note=f"(1 tick di bawah Low {z['level']})", tp1_note='(Area VPOC)', tp2_note='(High Sesi)')
    setups.append(s1)

    # ── SETUP 2: TWIN-SWEEP BREAKOUT ───────────────────────────
    tw = m['twin_sweep']
    s2 = new(2, 'Twin-Sweep Breakout', 'MOMENTUM AGGRESSIVE', 'ASLI, FORU')
    if tw['count'] >= 2:
        s2['checks_met'].append((f"Terdeteksi ≥ 2 parent buy agresif ≥ {fmt(B)} lot", f"{tw['count']} order ditemukan"))
    elif tw['count'] == 1:
        s2['checks_met'].append((f"1 parent buy agresif ≥ {fmt(B)} lot terdeteksi", "Sweep pertama tercatat"))
        s2['checks_pending'].append((f"Menunggu sweep blok kedua (≥ {fmt(B)} lot)", "Belum ada sweep susulan"))
    else:
        s2['checks_pending'].append((f"Wajib ada ≥ 2 parent order buy ≥ {fmt(B)} lot", "Belum ada sweep blok"))
    check(s2, tw['coord'] > 0,
          f"Dua sweep dimulai ≤ {CFG['twin_coord_sec']} detik (terkoordinasi)", f"{tw['coord']} pasang sweep berdekatan",
          'Dua sweep harus terjadi dalam interval singkat terkoordinasi', "Nihil sweep berpasangan")
    check(s2, tw['multi_level'],
          'Sweep menyapu offer di beberapa fraksi harga sekaligus', "Agresi vertikal tervalidasi",
          'Sweep harus melompati offer secara vertikal (≥ 2 harga)', "Menunggu multi-tick sweep")
    fresh = tw['age_min'] is not None and tw['age_min'] <= CFG['hot_min']
    check(s2, fresh,
          f"Sweep terakhir masih berada dalam jendela aktif (≤ {CFG['hot_min']} menit)", f"Umur sweep: {tw['age_min'] or 0:.0f} menit",
          f"Sweep terakhir melewati batas jendela aktif (> {CFG['hot_min']} menit) atau belum ada",
          f"Umur sweep: {'-' if tw['age_min'] is None else f'{tw['age_min']:.0f} menit'}")

    entry = m['last']
    base = tw['last']['base'] if tw['last'] else step(entry, -4)
    sl = step(base, -2)
    tp1 = step(entry, 4)
    if tw['found'] and tw['coord'] > 0 and fresh:
        status, act = 'TRIGGERED (ACTIVE)', True
    elif tw['found'] and tw['coord'] > 0:
        status, act = 'TRIGGERED (EXPIRED - sweep melewati jendela waktu, hindari kejar harga)', False
    else:
        status, act = 'MONITORING', False
    s2['params'] = mk_params(
        m, status, entry, entry, sl, tp1, m['ara'], "15 - 30 menit",
        "Entri beli segera setelah order sweep kedua terkonfirmasi di Running Trade", act,
        entry_note='HAKA paska sweep kedua', sl_note=f"(2 tick di bawah base sweep {base})",
        tp1_note='(+4 tick)', tp2_text=f"{fp(m['ara'], entry)} (ARA, prev {m['prev_close']})")
    setups.append(s2)

    # ── SETUP 3: VPOC RE-TEST ABSORPTION ──────────────────────
    s3 = new(3, 'VPOC Re-test Absorption', 'TREND FOLLOWING / VALUE ACCEPTANCE', 'KETR, DOOH, BRMS')
    vp_ = m['vpoc']
    check(s3, vp_ > step(m['low'], 2),
          f"VPOC ({vp_}) berada di atas level low (area nilai terangkat)", f"VPOC {vp_} vs Low {m['low']}",
          'Harga harus membentuk VPOC di atas level terendah', f"VPOC mepet low ({m['low']})")
    if m['vpoc_abs_mid'] >= 0.10 * B:
        s3['checks_met'].append((f"Bid pasif besar (parent ≥ {fmt(0.10 * B)} lot) menyerap tekanan jual di VPOC {vp_}", f"Serapan: {fmt(m['vpoc_abs_mid'])} lot"))
    elif m['vpoc_abs_small'] >= 0.02 * B:
        s3['checks_met'].append((f"Penyerapan parsial di VPOC {vp_}", f"Serapan: {fmt(m['vpoc_abs_small'])} lot"))
        s3['checks_pending'].append((f"Menunggu serapan blok ≥ {fmt(0.10 * B)} lot di VPOC", "Volume penyerapan belum mencapai batas blok"))
    else:
        s3['checks_pending'].append((f"Wajib ada serapan bid pasif ≥ {fmt(0.10 * B)} lot di VPOC", "Belum terdeteksi antrean bid besar di VPOC"))
    check(s3, m['vpoc_pct'] >= CFG['vpoc_min_pct'],
          'VPOC memvalidasi akumulasi volume sesi', f"Vol: {fmt(m['vpoc_lot'])} lot ({m['vpoc_pct']:.1f}% volume kontinu)",
          f"VPOC belum dominan (≥ {CFG['vpoc_min_pct']:.0f}% volume)", f"Hanya {m['vpoc_pct']:.1f}% volume")
    dist = ticks_between(vp_, m['last'])
    check(s3, -1 <= dist <= 3,
          'Harga sedang re-test area VPOC', f"Last {m['last']} ({dist:+d} tick dari VPOC)",
          'Harga harus kembali re-test VPOC (-1..+3 tick)', f"Last {m['last']} ({dist:+d} tick dari VPOC)")
    e_lo, e_hi = vp_, step(vp_, 1)
    sl, tp1 = step(vp_, -2), step(vp_, 3)
    tp2 = m['high'] if m['high'] > tp1 else step(tp1, 3)
    ready = m['vpoc_abs_mid'] >= 0.10 * B and -1 <= dist <= 3
    s3['params'] = mk_params(
        m, 'READY TO ENTER' if ready else ('WAITING RETEST' if dist > 3 or dist < -1 else 'WAITING ABSORPTION'),
        e_lo, e_hi, sl, tp1, tp2, "60 - 90 menit",
        f"Entri beli saat harga re-test VPOC {vp_} dengan konfirmasi penebalan antrean bid", ready,
        sl_note='(2 tick di bawah VPOC)', tp1_note='(+3 tick)', tp2_note='(High Sesi)')
    setups.append(s3)

    # ── SETUP 4: STAIRCASE MOMENTUM CONTINUATION ──────────────
    st = m['staircase']
    s4 = new(4, 'Staircase Momentum Continuation', 'TREND CONTINUATION', 'VKTR, KETR, MBMA')
    n_iv = len(m['intervals'])
    bullish_ivs = sum(1 for iv in m['intervals'] if iv['delta'] > 0)
    check(s4, st['asc'], 'Struktur tangga naik (higher close ≥ 60%) terkonfirmasi', f"Rasio kenaikan: {st['asc_ratio']:.0f}%",
          'Harga harus membentuk urutan higher close antar interval', f"Rasio saat ini: {st['asc_ratio']:.0f}%")
    check(s4, st['steps'] >= 2, '≥ 2 anak tangga naik (interval close > open) terbentuk', f"{st['steps']} steps up",
          'Wajib minimal 2 anak tangga naik', f"Baru {st['steps']} steps")
    check(s4, bullish_ivs >= max(n_iv // 2, 1), 'Net Delta positif di mayoritas interval', f"{bullish_ivs}/{n_iv} interval bullish",
          'Net Delta interval harus didominasi pembeli', f"{bullish_ivs}/{n_iv} bullish")
    check(s4, m['top_sell_lot'] < 0.6 * B, 'Struktur terjaga tanpa sell blok besar (≥ 0.6x blok)', f"Top sell parent: {fmt(m['top_sell_lot'])} lot",
          'Tekanan jual blok besar berisiko menekan struktur harga', f"Tercatat sell {fmt(m['top_sell_lot'])} lot")
    check(s4, m['change_pct'] >= 2.0 and not m['is_range_bound'], 'Tren kenaikan sesi terkonfirmasi (> +2.0%)', f"Perubahan: {m['change_pct']:+.2f}%",
          'Wajib momentum kenaikan aktif (> +2.0%)', f"Perubahan: {m['change_pct']:+.2f}%")
    check(s4, m['c_delta'] >= 0 or m['bm_rt_net'] >= 0, 'Order flow didominasi transaksi beli (HAKA)', f"Net Delta: {m['c_delta']:+,} lot | BM-RT net {m['bm_rt_net']:+,}",
          'Net Delta sesi harus positif (pembeli mendominasi)', f"Net Delta: {m['c_delta']:+,} lot | BM-RT net {m['bm_rt_net']:+,}")
    check(s4, m['last'] >= m['vwap'], 'Harga di atas VWAP (kontrol pembeli)', f"Last {m['last']} vs VWAP {m['vwap']:.1f}",
          'Harga harus bertahan di atas VWAP', f"Last {m['last']} < VWAP {m['vwap']:.1f}")
    entry = m['last']
    sl = step(entry, -2)
    tp1 = step(entry, 3)
    s4['params'] = mk_params(
        m, 'ACTIVE TREND (BUY ON PULLBACK)' if st['is'] else 'FORMING', entry, entry, sl, tp1, tp1,
        "90 - 120 menit", "Entri beli saat penembusan level tertinggi pijakan sebelumnya atau saat pullback", bool(st['is']),
        entry_note='Breakout atau pullback pijakan', sl_note='(1-2 tick di bawah pijakan)',
        tp1_note='(+3 tick)', tp2_text='Trailing Stop per pijakan tangga baru')
    setups.append(s4)

    # ── SETUP 5: SELLING CLIMAX EXHAUSTION REVERSAL ───────────
    cl = m['climax']
    s5 = new(5, 'Selling Climax Exhaustion Reversal', 'CONTRARIAN V-SHAPE', 'BRMS')
    if cl['bazookas'] >= 3:
        s5['checks_met'].append((f"Volume jual blok institusi (≥ 3 order ≥ {fmt(B)} lot)", f"{cl['bazookas']} blok sell"))
    elif cl['bazookas'] >= 1:
        s5['checks_met'].append((f"Volume jual blok institusi (1-2 order ≥ {fmt(B)} lot)", f"{cl['bazookas']} order tercatat"))
        s5['checks_pending'].append(('Menunggu konfirmasi volume jual lanjutan untuk pembentukan klimaks', "Klimaks belum terbentuk"))
    else:
        s5['checks_pending'].append((f"Wajib ada order jual blok institusi (≥ {fmt(B)} lot)", "Belum terdeteksi blok sell"))
    check(s5, cl['peak_vol'] > m['c_lot'] * 0.05, 'Volume puncak HAKI tercapai (klimaks jual)', f"Peak: {fmt(cl['peak_vol'])} lot @ {cl['peak_min']}",
          'Volume HAKI per menit harus menunjukkan lonjakan tajam', "Tekanan jual merata, bukan klimaks")
    vs = m['vshape']
    check(s5, vs['found'], 'Pantulan V-Shape setelah kejatuhan tajam', f"Drop {vs['drop_pct']:.1f}% lalu retrace {min(vs['retrace'], 100):.0f}%",
          'Wajib ada drop ≥ 3% lalu pantulan ≥ 50% dari drop', f"Drop {vs['drop_pct']:.1f}%, retrace {min(vs['retrace'], 100):.0f}%")
    e_lo = step(m['low'], 2)
    sl = step(m['low'], -1)
    tp1 = m['vpoc'] if m['vpoc'] > e_lo else step(e_lo, 3)
    tp2 = m['open'] if m['open'] > tp1 else (m['high'] if m['high'] > tp1 else step(tp1, 3))
    ext = extended_ticks(m, e_lo)
    ok_sig = cl['bazookas'] >= 1 and vs['found']
    s5['params'] = mk_params(
        m, ('REVERSAL CONFIRMED' if ext <= chase + 2 else f'REVERSAL SUDAH BERJALAN (+{ext} tick) - TUNGGU PULLBACK') if ok_sig else 'WAITING EXHAUSTION',
        e_lo, e_lo, sl, tp1, tp2, "30 - 45 menit",
        "Hindari entry mendahului konfirmasi: masuk hanya saat volume HAKI turun < 25% puncak dan harga memantul minimal 2 tick",
        bool(ok_sig and ext <= chase + 2),
        entry_note='setelah HAKI menyusut', sl_note='(1 tick di bawah Low Climax)', tp1_note='(VPOC)', tp2_note='(Open / High)')
    setups.append(s5)

    # ── SETUP 6: LEVEL PSIKOLOGIS BREAKOUT ────────────────────
    ps = m['psych']
    s6 = new(6, 'Level Psikologis Breakout', 'ROUND NUMBER BREAKOUT', 'VKTR (400), BUVA (350), KETR (600)')
    held_up = [l for l in ps['levels'] if l['held']]
    if ps['found']:
        lvls = ', '.join(str(l['level']) for l in ps['levels'])
        s6['checks_met'].append((f"Harga menembus level psikologis (kelipatan {ps['step']})", f"Level: {lvls}"))
        top_lv = max(ps['levels'], key=lambda x: x['vol'])
        check(s6, top_lv['vol'] > m['c_lot'] * 0.01, f"Volume signifikan diserap di level {top_lv['level']}",
              f"{fmt(top_lv['vol'])} lot ({pct(top_lv['vol'], m['c_lot']):.1f}%)",
              f"Volume di level {top_lv['level']} harus mencerminkan penyerapan", "Volume tipis")
        check(s6, bool(held_up), 'Harga bertahan di atas level psikologis', f"Last: {m['last']}",
              'Harga wajib bertahan di atas level psikologis', f"Kembali turun ke {m['last']}")
        ref_lv = max((l['level'] for l in held_up), default=max(l['level'] for l in ps['levels']))
        chop = any(l['down'] for l in ps['levels'])
        check(s6, not chop, 'Level ditembus bersih tanpa fluktuasi bolak-balik', "Tidak ada penembusan balik",
              'Level mengalami fluktuasi bolak-balik (risiko false breakout)', "Risiko false breakout")
    else:
        s6['checks_pending'].append((f"Harga belum menembus level kelipatan {ps['step']}", "Belum ada penembusan ke atas"))
        ref_lv = round_up_to(m['last'] + 1, ps['step'])
    e_lo = step(ref_lv, 1)
    sl, tp1, tp2 = step(ref_lv, -2), step(e_lo, 3), step(e_lo, 6)
    ext = extended_ticks(m, e_lo)
    valid = ps['found'] and bool(held_up)
    s6['params'] = mk_params(
        m, ('BREAKOUT VALID' if ext <= chase else f'EXTENDED (+{ext} tick) - TUNGGU RETEST LEVEL') if valid else 'WAITING BREAKOUT',
        e_lo, e_lo, sl, tp1, tp2, "45 - 60 menit",
        f"Entri beli saat antrean offer tebal pada level {ref_lv} habis terserap", bool(valid and ext <= chase),
        entry_note=f"1 tick di atas level {ref_lv}", sl_note='(2 tick di bawah level)', tp1_note='(+3 tick)', tp2_note='(+6 tick)')
    setups.append(s6)

    # ── SETUP 7: BEARISH WATERFALL / DUMP COLLAPSE ────────────
    wf = m['waterfall']
    s7 = new(7, 'Bearish Waterfall / Dump Collapse', 'AVOID / IMMEDIATE CUT LOSS', 'STRK, SMIL, AMRT')
    drop_from_high = (m['high'] - m['close']) / m['high'] * 100
    check(s7, m['change_pct'] <= -4.0 or drop_from_high >= 12,
          'Penurunan curam terkonfirmasi', f"Perubahan: {m['change_pct']:+.2f}% (Drop dari high: {drop_from_high:.1f}%)",
          'Harga belum anjlok parah (> -4%)', f"Perubahan: {m['change_pct']:+.2f}%")
    haki_ratio = pct(m['sell_lot'], m['total_lot'])
    check(s7, haki_ratio > 52.0 or wf['haki_5'] > 55.0, 'Volume dikuasai penjual HAKI agresif',
          f"Total HAKI: {haki_ratio:.1f}% (5 menit awal: {wf['haki_5']:.1f}%)",
          'Dominasi HAKI agresif belum dominan', f"HAKI: {haki_ratio:.1f}%")
    check(s7, m['range_pct'] >= 4.0 and m['close'] <= step(m['low'], 3), 'Harga tutup di dekat dasar sesi (waterfall collapse)',
          f"Close {m['close']} mepet Low {m['low']}", 'Harga memantul dari level terendah', f"Close {m['close']} vs Low {m['low']}")
    check(s7, m['bm_rt_net'] < 0 or m['bm_div']['bm_sell'] > m['bm_div']['bm_buy'], 'Aliran Big Money net distribusi (dump)',
          f"BM RT Net: {m['bm_rt_net']:+,} lot", 'Big Money Net masih akumulasi', f"BM RT Net: {m['bm_rt_net']:+,} lot")
    n_met = len(s7['checks_met'])
    s7['params'] = {
        'status': 'DANGER: DO NOT BUY / CUT LOSS NOW' if n_met >= 3 else ('ALERT: HIGH RISK' if n_met >= 2 else 'CLEAR (NO WATERFALL)'),
        'actionable': False,
        'entry_zone': "DILARANG MASUK (NO BUY ZONE)", 'cut_loss': "EKSEKUSI SEGERA DI HARGA PASAR (HIT BID)",
        'tp1': "NIHIL", 'tp2': "NIHIL", 'rrr': "N/A", 'max_holding': "0 menit",
        'trigger_rule': "Terdeteksi pola dump atau collapse. Hindari averaging down dan lakukan cut loss tanpa menunggu pantulan harga."}
    setups.append(s7)

    # ── SETUP 8: RANGE-BOUND SQUEEZE ABSORPTION ───────────────
    s8 = new(8, 'Range-Bound Squeeze Absorption', 'RANGE SCALPING / SQUEEZE COIL', 'PTRO, DOOH')
    check(s8, m['compressed'] and abs(m['change_pct']) <= 2.5,
          'Rentang terkompresi ketat & flat (Range ≤ 5% atau ≤ 8 tick/≤10%, |Chg| ≤ 2.5%)',
          f"Rentang: {m['range_pct']:.1f}% ({m['range_ticks']} tick) | Chg: {m['change_pct']:+.2f}%",
          'Rentang harus terkompresi ketat dan flat (|Chg| ≤ 2.5%)', f"Rentang: {m['range_pct']:.1f}% ({m['range_ticks']} tick) | Chg: {m['change_pct']:+.2f}%")
    check(s8, m['c_val'] >= 15e9, 'Turnover likuid (> Rp 15B)', f"Turnover: Rp {fmt(m['c_val'])}",
          'Wajib didukung turnover likuid (> Rp 15B)', f"Turnover: Rp {fmt(m['c_val'])}")
    check(s8, m['mid_conc'] >= 45.0, f"Volume terkonsentrasi di 3 tick VPOC {m['vpoc']} (≥ 45%)", f"Konsentrasi: {m['mid_conc']:.1f}%",
          'Volume harus terkonsentrasi di area VPOC (≥ 45%)', f"Konsentrasi saat ini: {m['mid_conc']:.1f}%")
    check(s8, m['last'] > step(m['low'], 1) and m['vpoc'] > step(m['low'], 1), 'Support bawah teruji dan VPOC di atas low',
          f"Last {m['last']} vs Low {m['low']} | VPOC {m['vpoc']}", 'Menunggu rebound dari support bawah (VPOC mepet low)',
          f"Last {m['last']} vs Low {m['low']} | VPOC {m['vpoc']}")
    e_lo, e_hi = step(m['low'], 1), step(m['low'], 2)
    sl = step(m['low'], -1)
    tp1 = m['vpoc'] if m['vpoc'] > e_hi else step(e_hi, 3)
    tp2 = step(m['high'], -1) if m['high'] > tp1 else step(tp1, 2)
    near_sup = m['last'] <= step(e_hi, chase)
    active = len(s8['checks_met']) >= 3
    s8['params'] = mk_params(
        m, ('RANGE SCALPING ACTIVE (BUY AT SUPPORT ONLY)' if near_sup else 'RANGE ACTIVE - HARGA DI AREA TENGAH/ATAS, TUNGGU KE SUPPORT') if active else 'WATCHLIST COIL',
        e_lo, e_hi, sl, tp1, tp2, "45 - 60 menit per ayunan",
        "Disiplin range scalping: beli hanya di batas support dengan penebalan antrean bid. Hindari pembelian agresif di area resistance atau VPOC.",
        bool(active and near_sup), entry_note='Batas bawah rentang / demand',
        sl_note=f"(1 tick di bawah Low {m['low']})", tp1_note='(VPOC)', tp2_note='(Batas atas rentang)')
    setups.append(s8)

    return setups


# ═══════════════════════════════════════════════════════════════
#  KLASIFIKASI 10 ARKETIPE PASAR BEI
# ═══════════════════════════════════════════════════════════════

def classify(m):
    results = []
    B = m['block']

    def score(name, criteria):
        tw = sum(w for w, _, _ in criteria)
        earned = sum(w for w, met, _ in criteria if met)
        results.append((name, pct(earned, tw), [(d, met) for _, met, d in criteria]))

    bull = m['change_pct'] > 0
    rng = m['range_pct']
    zal = m['zal']['is_zero']
    near0 = m['zal']['is_near_zero']
    stair = m['staircase']['is']
    twin = m['twin_sweep']['found']
    baz = m['climax']['bazookas']
    wf = m['waterfall']['found']
    twap = m['twap']['found']
    churn = m['churning']['found']
    fb, fbu = m['bm_div']['false_bear'], m['bm_div']['false_bull']
    tbl, tsl = m['top_buy_lot'] / B, m['top_sell_lot'] / B
    tv = m['total_val']

    score('Growth Markup (VKTR / BUVA)', [
        (3, bull and m['change_pct'] > 5, 'Bullish close > +5%'),
        (3, stair or fb, 'Pola tangga / momentum terkonfirmasi'),
        (2, 0.1 <= tbl <= 1.5, 'Parent buy institusi aktif (≥ 0.1x blok)'),
        (1, rng > 8, 'Range ekspansi sesi > 8%'),
        (1, not twin, 'Markup bertahap (bukan single twin sweep)'),
    ])
    score('Low-Float ARA Lock (ASLI)', [
        (4, m['close_vs_prev'] > 20 or m['at_ara'], 'Close ≥ +20% vs prev / terkunci di ARA'),
        (3, twin, 'Twin sweep blok terkoordinasi'),
        (2, rng > 20, 'Range sesi ekspansi > 20%'),
        (1, zal or near0, 'Zero-Ask Low terkonfirmasi'),
    ])
    score('Lightning Rocket & Churn (FORU)', [
        (3, bull and rng > 10, 'Rentang ekspansi sesi > 10%'),
        (3, twin or tbl >= 1.0, 'Order beli blok besar (≥ 1x blok) di awal sesi'),
        (2, churn, 'Rotasi distribusi / Churning di area resistance'),
        (2, m['bm_div']['bmrt_bull'], 'Running BM-RT dominan beli'),
    ])
    score('Staircase Precision (MBMA / KETR)', [
        (4, stair, 'Pola tangga presisi terkonfirmasi'),
        (2, 0.02 <= tbl <= 0.6, 'Parent order terukur (0.02x s/d 0.6x blok)'),
        (2, bull and 2 < m['change_pct'] < 12, 'Kenaikan stabil bertahap (+2% s/d +12%)'),
        (1, not twin and baz == 0, 'Pergerakan stabil tanpa transaksi blok liar'),
        (1, m['vpoc'] > m['low'] + (m['high'] - m['low']) * 0.3, 'VPOC di atas 30% rentang harga'),
    ])
    score('Nimble Skirmish (OASA)', [
        (3, zal and m['zal']['recovered'], 'Zero-Ask Low dengan rebound bersih'),
        (2, tv < 50e9, 'Turnover lincah (< Rp 50 Miliar)'),
        (2, tbl < 0.5, 'Parent order terukur (< 0.5x blok)'),
        (2, bull and 2 < m['change_pct'] < 10, 'Kenaikan terukur (+2% s/d +10%)'),
        (1, rng < 15, 'Rentang pergerakan teratur (< 15%)'),
    ])
    score('Whale Bazooka War (BRMS)', [
        (4, baz >= 1, 'Transaksi jual blok besar institusi (order ≥ blok)'),
        (3, m['zal']['recovered'] and abs(m['change_pct']) < 4, 'Pantulan V-Shape (rebound menuju netral)'),
        (2, tv > 100e9, 'Turnover likuid > Rp 100 Miliar'),
        (1, tsl >= 1.0, 'Parent sell besar ≥ 1x blok'),
    ])
    score('Range-Bound Squeeze (PTRO / DOOH)', [
        (4, m['compressed'] and abs(m['change_pct']) <= 2.0, 'Rentang terkompresi ketat dan flat (Chg ≤ 2%)'),
        (3, m['mid_conc'] >= 45.0, 'Konsentrasi volume di 3 tick VPOC (≥ 45%)'),
        (2, tv >= 15e9, 'Turnover likuid aktif (≥ Rp 15 Miliar)'),
        (1, not twin and baz == 0, 'Pergerakan tertib tanpa lonjakan panik'),
    ])
    score('Distribution Blue Chip (AMRT / SMIL)', [
        (3, not bull and m['change_pct'] > -8, 'Pelemahan bertahap (0% s/d -8%)'),
        (3, fbu or twap, 'Divergensi False Bullish atau distribusi TWAP sell tersembunyi'),
        (2, twap or m['bm_rt_net'] < 0, 'Distribusi institusi konsisten'),
        (1, tv > 18e9, 'Turnover likuid > Rp 18 Miliar'),
        (1, rng < 10, 'Rentang volatilitas terkontrol (< 10%)'),
    ])
    score('Speculative Collapse (STRK)', [
        (4, m['change_pct'] < -10, 'Penurunan curam < -10%'),
        (3, wf, 'Pola Waterfall collapse terkonfirmasi'),
        (2, not zal and not near0, 'Zero-Ask Low tidak bertahan (pembeli absen)'),
        (1, m['waterfall']['haki_5'] > 50, 'Tekanan HAKI agresif sejak menit awal'),
    ])

    results.sort(key=lambda x: x[1], reverse=True)
    return results


# ═══════════════════════════════════════════════════════════════
#  PENGAMBILAN KEPUTUSAN SINYAL (ACTION DECISION)
# ═══════════════════════════════════════════════════════════════

def get_setup_score(s):
    tot = len(s['checks_met']) + len(s['checks_pending'])
    return pct(len(s['checks_met']), tot) if tot else 0.0


def decide_action(m, setups, archs):
    """
    Menghasilkan kartu keputusan eksekutif (Action Card)
    dengan hierarki prioritas keamanan trader:
    1. DANGER / TRAP (Hindari / Exit segera)
    2. READY (Setup valid & harga masih di dalam zona entry)
    3. EXTENDED (Setup valid tapi harga sudah lari > 2 tick - tunggu pullback)
    4. RANGE (Ping-pong scalping pada batas support)
    5. DEV (Setup sedang berproses)
    6. WAIT (Belum ada setup aktif)
    """
    top = archs[0]
    by_id = {s['id']: s for s in setups}
    s7 = by_id[7]
    s7_score = get_setup_score(s7)
    candidates = [s for s in setups if s['id'] not in (7, 8) and get_setup_score(s) >= 60.0]
    best = max(candidates, key=get_setup_score) if candidates else None
    out = {'best': best}

    if s7_score >= 75.0 and m['change_pct'] < -2.0:
        out.update(label="DANGER: AVOID / CUT LOSS (COLLAPSE DETECTED)", icon="🚨", key='DANGER', rank=0)
    elif (m['bm_div']['false_bull'] and m['change_pct'] < -2.0) or \
            (('Distribution' in top[0] or 'Collapse' in top[0]) and m['change_pct'] < -2.0):
        out.update(label="DANGER: FALSE BULLISH TRAP / DISTRIBUTION (DO NOT BUY)", icon="🚨", key='TRAP', rank=0)
    elif m['is_range_bound']:
        s8 = by_id[8]
        if get_setup_score(s8) >= 75.0:
            ok = s8['params'].get('actionable')
            out.update(label="RANGE-BOUND SQUEEZE (BUY AT SUPPORT ONLY)" + ("" if ok else " - TUNGGU RETEST SUPPORT"),
                       icon="🟡", key='RANGE', rank=2, best=s8)
        else:
            out.update(label="RANGE-BOUND COIL (WAIT FOR RANGE EXPANSION)", icon="🟡", key='COIL', rank=3)
    elif best:
        sc = get_setup_score(best)
        act = best['params'].get('actionable', False)
        reversal = best['id'] in (1, 5)
        if sc >= 80.0 and m['change_pct'] < -3.0 and not reversal:
            out.update(label=f"CAUTION: {best['name'].upper()} (saham turun {m['change_pct']:+.1f}%)", icon="⚠️", key='CAUTION', rank=4)
        elif sc >= 80.0 and act:
            out.update(label=f"READY TO TRADE ({best['name'].upper()})", icon="🟢", key='READY', rank=1)
        elif sc >= 80.0:
            out.update(label=f"SETUP VALID TAPI EXTENDED ({best['name'].upper()}) - TUNGGU PULLBACK", icon="🟡", key='EXTENDED', rank=3)
        else:
            out.update(label=f"DEVELOPING SETUP ({best['name'].upper()})", icon="🟡", key='DEV', rank=3)
    else:
        out.update(label="WAIT / MONITOR", icon="⚪", key='WAIT', rank=5)
    return out


# ═══════════════════════════════════════════════════════════════
#  REPORT FORMATTER & CLI PRINTER
# ═══════════════════════════════════════════════════════════════

def box(lines, W=86):
    print('╔' + '═' * W + '╗')
    for ln in lines:
        print('║' + ln.ljust(W)[:W] + '║')
    print('╚' + '═' * W + '╝')


def sec_hdr(title, W=84):
    print(f'\n{"─" * 3} {title} {"─" * max(W - len(title) - 5, 3)}')


def print_single_report(m, setups, archetypes, ticker):
    top = archetypes[0]
    act = decide_action(m, setups, archetypes)
    cost = CFG['fee_buy_pct'] + CFG['fee_sell_pct']
    print()
    box([f'  SCREENER MIKROSTRUKTUR & TAPE READING BEI - PLAYBOOK v3.1',
         f'  Ticker: {ticker:<12} | Data: {m["date"] or "-"} | Tick terakhir: {m["now"]} '
         f'| {"SNAPSHOT SESI BERJALAN" if m["is_live"] else "SESI SELESAI"}'], 88)

    if m.get('sync_warn'):
        print(f'  ⚠️  {m["sync_warn"]}')
    sec_hdr("KARTU TINDAKAN EKSEKUTIF (EXECUTIVE ACTION CARD)")
    zl = "TERKONFIRMASI 100%" if m["zal"]["is_zero"] else ("NEAR-ZERO" if m["zal"]["is_near_zero"] else "TIDAK VALID")
    print(f'  Status Sinyal : {act["icon"]} {act["label"]}')
    print(f'  Arketipe Utama: {top[0]} (Kesesuaian: {top[1]:.1f}%)')
    last_note = f' | Last {m["last"]}' if m['last'] != m['close'] else ''
    print(f'  Harga         : Rp {m["close"]}{last_note} ({m["change_pct"]:+.2f}% vs Open | {m["close_vs_prev"]:+.2f}% vs Prev {m["prev_close"]})')
    print(f'  VWAP / VPOC   : Rp {m["vwap"]:.1f} (harga {m["close_vs_vwap"]:+.2f}% vs VWAP) / Rp {m["vpoc"]}')
    print(f'  Batas Bawah   : Rp {m["low"]} (Zero-Ask Low: {zl})')
    print(f'  ARA / ARB     : {m["ara"]} / {m["arb"]}')
    print(f'  Biaya scalping: 1 tick = Rp {m["tick"]} ({m["tick_pct"]:.2f}%) | fee round-trip ≈ {cost:.2f}% (≈ {cost / m["tick_pct"]:.1f} tick untuk impas)')

    sec_hdr("1. PROFIL MIKROSTRUKTUR & ORDER FLOW")
    print(f'  OHLC (kontinu): {m["open"]} / {m["high"]} / {m["low"]} / {m["close"]}')
    print(f'  Rentang       : {m["range_pct"]:.1f}% ({m["high"] - m["low"]} poin / {m["range_ticks"]} tick) | Gap open: {m["gap_pct"]:+.2f}%')
    print(f'  Total Volume  : {fmt(m["total_lot"])} lot (Buy: {m["buy_pct"]:.1f}% | Sell: {100 - m["buy_pct"]:.1f}%) | Net Delta kontinu: {m["c_delta"]:+,} lot')
    print(f'  Turnover      : Rp {fmt(m["total_val"])} ({m["total_freq"]:,} trades)')
    print(f'  Value Area    : VAL {m["val"]} - VPOC {m["vpoc"]} - VAH {m["vah"]} (70% volume kontinu)')
    print(f'  Ambang Blok   : ≥ {fmt(m["block"])} lot per parent order (adaptif ≈ Rp {CFG["block_value"]/1e9:.2f}B)')
    print(f'  BM-RT Ambang  : ≥ {fmt(m["bm_rt_th"])} lot per trade')
    print(f'  BM-RT Net     : {m["bm_rt_net"]:+,} lot (Buy: {fmt(m["bm_rt_buy"])} | Sell: {fmt(m["bm_rt_sell"])})')
    if m['orb']:
        print(f'  Opening Range : {m["orb"]["low"]} - {m["orb"]["high"]} → {m["orb"]["status"]}')

    sec_hdr(f"2. KONDISI TERKINI ({CFG['recent_min']} MENIT TERAKHIR s/d {m['now']})")
    rec = m['recent']
    print(f'  Harga         : {rec["p_from"]} → {rec["p_to"]} ({rec["price_chg"]:+.2f}%)')
    print(f'  Net Delta     : {rec["delta"]:+,} lot (Buy {rec["buy_pct"]:.0f}%) | BM-RT net {m["bm_recent"]["net"]:+,} lot')
    print(f'  Kecepatan Tape: {rec["speed"]:.1f}x rata-rata ({rec["n"]} trades)')
    if rec['bear_div']:
        print('  ⚠️  BEARISH DELTA DIVERGENCE: harga di area high namun net delta terkini didominasi tekanan jual (HAKI).')
    if rec['bull_div']:
        print('  🟢 BULLISH DELTA DIVERGENCE: harga di area low namun net delta terkini didominasi penyerapan beli (HAKA).')

    sec_hdr("3. EVALUASI BIG MONEY & FILTER ANTI-JEBAKAN")
    div = m['bm_div']
    b_label = "BULLISH" if div["bm_bull"] else "BEARISH"
    rt_label = "BULLISH" if div["bmrt_bull"] else "BEARISH"
    print(f'  Order-Level BM : Buy {div["bm_buy"]}% vs Sell {div["bm_sell"]}% → {b_label}')
    print(f'  Running BM-RT  : Buy {div["bmrt_buy"]}% vs Sell {div["bmrt_sell"]}% → {rt_label}')
    if div['false_bull']:
        print('  🚨 FALSE BULLISH TRAP: Order book pasif tampak akumulasi, namun running trade didominasi distribusi jual.')
    elif div['false_bear']:
        print('  ⚠️  FALSE BEARISH SIGNAL: Offer tebal pada running trade, namun antrean bid menyerap secara konsisten.')
    else:
        print('  ✅ Pola Big Money dan Running BM-RT bergerak selaras.')

    if m['twap']['found']:
        print(f'  ⚠️  TWAP slicing: {m["twap"]["cluster"]} parent sell ±{m["twap"]["size"]} lot tersebar {m["twap"]["spread_min"]:.0f} menit')
    if m['churning']['found']:
        print(f'  ⚠️  Churning: {m["churning"]["mins"]} menit volume tinggi tanpa ekspansi harga ({m["churning"]["at_top"]} di area resistance)')

    sec_hdr("4. KECONDONGAN ARKETIPE PASAR (MATCHING RANK)")
    for name, sc, crit in archetypes[:4]:
        ic = "🟢" if sc >= 75 else ("🟡" if sc >= 50 else "⚪")
        print(f'  {ic} [{sc:5.1f}%] {name}')
        for desc, met in crit:
            print(f'         {"✓" if met else "✗"} {desc}')

    sec_hdr("5. CHECKPOINT PLAYBOOK INTRADAY (SETUP STATUS & PENDING)")
    for s in setups:
        score = get_setup_score(s)
        n_met = len(s['checks_met'])
        n_tot = n_met + len(s['checks_pending'])
        if s['id'] == 7:
            badge = "🚨 BAHAYA / HINDARI" if score >= 50 else "✅ AMAN (TIDAK AKTIF)"
            icon = "🚨" if score >= 50 else "⚪"
        else:
            badge = "🟢 READY TO ENTER" if score >= 80 else ("🟡 DEVELOPING" if score >= 50 else "⚪ INACTIVE")
            icon = "🟢" if score >= 80 else ("🟡" if score >= 50 else "⚪")
        print(f'\n  {icon} SETUP {s["id"]}: {s["name"].upper()}')
        print(f'     Kategori: {s["type"]} | Skor: {bar(score, 12)} {score:5.1f}% ({n_met}/{n_tot}) [{badge}]')
        print(f'     Referensi Playbook: {s["source_tickers"]}')
        if s['checks_met']:
            print('     [✓ SUDAH TERPENUHI (MET)]:')
            for desc, ev in s['checks_met']:
                print(f'       ✅ {desc}  --> [{ev}]')
        if s['checks_pending']:
            print('     [⏳ PENDING / WAJIB DIPENUHI]:')
            for desc, req in s['checks_pending']:
                print(f'       ⚠️  {desc}  --> [{req}]')
        p = s['params']
        print('     [🎯 PARAMETER EKSEKUSI & RISK/REWARD]:')
        print(f'       • Status             : {p.get("status", "-")}')
        print(f'       • Area Entry Ideal   : {p.get("entry_zone", "-")}')
        print(f'       • Stop Loss (CutLoss): {p.get("cut_loss", "-")}')
        print(f'       • Target 1 (TP1)     : {p.get("tp1", "-")}')
        print(f'       • Target 2 (TP2)     : {p.get("tp2", "-")}')
        print(f'       • Risk / Reward      : {p.get("rrr", "-")} | Max Holding: {p.get("max_holding", "-")}')
        print(f'       • Pemicu Tape (Rule) : {p.get("trigger_rule", "-")}')

    sec_hdr("6. PETA LIKUIDITAS & PESANAN INDUK TERBESAR")
    for title, lst in (('BUY', m['bp_nature']), ('SELL', m['sp_nature'])):
        print(f'  TOP 3 {title} PARENT ORDERS:')
        for k, v, n in lst[:3]:
            pr = f"{min(v['prices'])}-{max(v['prices'])}" if len(v['prices']) > 1 else f"{next(iter(v['prices']))}"
            print(f'    Order #{k}: {fmt(v["lot"]):>9} lot [{n}] @ Rp {pr:<9} | {v["fills"]} fills ({v["first"]} - {v["last"]})')

    sec_hdr("CATATAN PENUTUP & RISIKO")
    print('  • Analisis murni dinamika harga & antrean order book tanpa kode broker.')
    print('  • Status EXTENDED: Hindari mengejar harga jika telah bergerak > 2 tick di atas zona entry ideal.')
    print('  • Disiplin cut loss jika level invalidasi tersentuh. Informasi ini bukan saran investasi.')
    print()


# ═══════════════════════════════════════════════════════════════
#  BATCH SCANNER MODE
# ═══════════════════════════════════════════════════════════════

def find_pairs_in_dir(folder):
    """
    Mencari dan memasangkan file CSV dan JSON di dalam folder.
    Mendukung format awalan (running-trade_PTRO_...) maupun format akhiran (ptro_running_trade.csv).
    """
    csvs = sorted(glob.glob(os.path.join(folder, "*.csv")))
    jsons = sorted(glob.glob(os.path.join(folder, "*.json")))
    json_map = {}
    for j in jsons:
        k = pair_key(j)
        json_map[k] = j

    pairs = []
    for c in csvs:
        k = pair_key(c)
        if k in json_map:
            tk_lbl = clean_ticker_label(k)
            pairs.append((c, json_map[k], tk_lbl))
        elif k == "running_trade" and "order_trade_chart" in json_map:
            # Fallback untuk file tanpa nama ticker di folder scratch
            pairs.append((c, json_map["order_trade_chart"], "VKTR"))
    return pairs


def run_batch_scan(folder, csv_out=None):
    pairs = find_pairs_in_dir(folder)
    if not pairs:
        print(f"Tidak ditemukan pasangan CSV dan JSON yang cocok di: {folder}")
        return
    print(f"\nMemulai pemindaian pasar untuk {len(pairs)} saham di folder: {folder}...")
    summary = []
    for c, j, tk in pairs:
        try:
            m = compute_all(load_trades(c), load_json(j))
            setups = eval_setups(m)
            archs = classify(m)
            act = decide_action(m, setups, archs)
            best = act['best'] or max(setups, key=get_setup_score)
            if act['key'] in ('DANGER', 'TRAP'):
                best = next(s for s in setups if s['id'] == 7)
            summary.append({
                'ticker': tk, 'date': m['date'], 'close': m['close'], 'change': m['change_pct'],
                'vs_prev': m['close_vs_prev'], 'vol': m['total_lot'], 'val': m['total_val'],
                'arch': archs[0][0].split('(')[0].strip(), 'arch_pct': archs[0][1],
                'best_setup': best['name'], 'setup_pct': get_setup_score(best),
                'status': f"{act['icon']} {act['key']}", 'rank': act['rank'],
                'vpoc': m['vpoc'], 'vwap': m['vwap'], 'zal': m['zal']['is_zero'],
                'entry': best['params'].get('entry_zone', ''), 'sl': best['params'].get('sl', ''),
                'tp1': best['params'].get('tp1_px', ''), 'rr_net': best['params'].get('rr_net', ''),
            })
        except Exception as e:
            print(f"Error memproses {tk}: {e}")

    summary.sort(key=lambda x: (x['rank'], -x['setup_pct']))
    W = 108
    print()
    box([f'  LEADERBOARD SCREENER MIKROSTRUKTUR BEI - TAPE READING PLAYBOOK',
         f'  Total Saham Dipindai: {len(summary)} ticker'], W)
    print(f'  {"Ticker":<8} | {"Close":>6} | {"Change":>7} | {"Turnover":>9} | {"Top Arketipe":<22} | {"Setup Terbaik":<24} | {"Skor":>6} | {"RRn":>4} | Status')
    print(f'  {"─" * 8}-+-{"─" * 6}-+-{"─" * 7}-+-{"─" * 9}-+-{"─" * 22}-+-{"─" * 24}-+-{"─" * 6}-+-{"─" * 4}-+-{"─" * 15}')
    for r in summary:
        rr = f'{r["rr_net"]:.1f}' if isinstance(r['rr_net'], (int, float)) else '-'
        print(f'  {r["ticker"]:<8} | {r["close"]:>6} | {r["change"]:>+6.2f}% | Rp {fmt(r["val"]):>6} | {r["arch"][:22]:<22} | '
              f'{r["best_setup"][:24]:<24} | {r["setup_pct"]:5.1f}% | {rr:>4} | {r["status"]}')
    print()
    if csv_out and summary:
        keys = ['ticker', 'date', 'close', 'change', 'vs_prev', 'vol', 'val', 'arch', 'arch_pct', 'best_setup',
                'setup_pct', 'status', 'vpoc', 'vwap', 'zal', 'entry', 'sl', 'tp1', 'rr_net']
        with open(csv_out, 'w', newline='', encoding='utf-8-sig') as f:
            w = csv.DictWriter(f, fieldnames=keys, extrasaction='ignore')
            w.writeheader()
            w.writerows(summary)
        print(f"  Hasil diekspor ke: {csv_out}\n")


# ═══════════════════════════════════════════════════════════════
#  FASTAPI & API INTEGRATION ENGINE
# ═══════════════════════════════════════════════════════════════

def build_json(m, setups, archetypes, ticker):
    """Menghasilkan payload dictionary bersih yang siap di-return oleh FastAPI."""
    act = decide_action(m, setups, archetypes)
    return {
        'ticker': ticker, 'date': m['date'], 'snapshot_time': m['now'], 'is_live': m['is_live'],
        'action': {'key': act['key'], 'label': act['label'], 'icon': act['icon']},
        'ohlc': {'o': m['open'], 'h': m['high'], 'l': m['low'], 'c': m['close'], 'last': m['last'],
                 'prev_close': m['prev_close'], 'ara': m['ara'], 'arb': m['arb']},
        'volume': m['total_lot'], 'turnover': m['total_val'],
        'levels': {'vwap': m['vwap'], 'vpoc': m['vpoc'], 'val': m['val'], 'vah': m['vah'], 'orb': m['orb']},
        'block_lot': m['block'], 'tick': m['tick'], 'recent': m['recent'], 'bm_recent': m['bm_recent'],
        'zero_ask_low': m['zal'], 'bm_divergence': m['bm_div'],
        'archetypes': [{'name': a[0], 'score': a[1]} for a in archetypes],
        'setups': [{'id': s['id'], 'name': s['name'], 'score': get_setup_score(s),
                    'met': s['checks_met'], 'pending': s['checks_pending'], 'params': s['params']} for s in setups],
    }


def analyze_stock(trades_source, json_source, ticker="TICKER", cfg_override=None):
    """
    Fungsi inti backend FastAPI:
    Menerima data (file path, list of dicts, atau dict JSON), mengembalikan hasil analisa lengkap.
    """
    if cfg_override:
        CFG.update(cfg_override)
    trades = load_trades(trades_source)
    jd = load_json(json_source)
    m = compute_all(trades, jd)
    setups = eval_setups(m)
    archetypes = classify(m)
    act = decide_action(m, setups, archetypes)
    json_data = build_json(m, setups, archetypes, ticker)
    return {
        'metrics': m,
        'setups': setups,
        'archetypes': archetypes,
        'action': act,
        'json': json_data
    }


# ═══════════════════════════════════════════════════════════════
#  MAIN ENTRY POINT (CLI)
# ═══════════════════════════════════════════════════════════════

def main():
    ap = argparse.ArgumentParser(description="Intraday Screener & Tape Reading BEI v3.1")
    ap.add_argument('files', nargs='*', help="<running_trade.csv> <trade_book.json>")
    ap.add_argument('--scan', metavar='FOLDER', help="mode batch: pindai semua pasangan CSV+JSON di folder")
    ap.add_argument('--ticker', help="kode saham (dikirim eksplisit untuk label laporan/FastAPI)")
    ap.add_argument('--json', action='store_true', help="output format JSON (single ticker)")
    ap.add_argument('--csv-out', help="export leaderboard batch ke file CSV")
    ap.add_argument('--fixed-lots', action='store_true', help="pakai ambang blok tetap 50k lot")
    ap.add_argument('--fee-buy', type=float, help="fee beli %% (default 0.15)")
    ap.add_argument('--fee-sell', type=float, help="fee jual %% (default 0.25)")
    ap.add_argument('--recent-min', type=int, help="jendela kondisi terkini (menit, default 15)")
    a = ap.parse_args()

    if a.fixed_lots: CFG['block_mode'] = 'fixed'
    if a.fee_buy is not None: CFG['fee_buy_pct'] = a.fee_buy
    if a.fee_sell is not None: CFG['fee_sell_pct'] = a.fee_sell
    if a.recent_min: CFG['recent_min'] = a.recent_min

    if a.scan:
        run_batch_scan(a.scan, a.csv_out)
        return

    if len(a.files) != 2:
        ap.print_help()
        sys.exit(1)

    csv_path, json_path = a.files
    for p, label in ((csv_path, 'CSV'), (json_path, 'JSON')):
        if not os.path.exists(p):
            print(f"Error: File {label} tidak ditemukan: {p}")
            sys.exit(1)

    ticker = resolve_ticker(a.ticker, fallback=clean_ticker_label(pair_key(csv_path), "TICKER"))
    try:
        res = analyze_stock(csv_path, json_path, ticker=ticker)
    except Exception as e:
        print(f"Error memproses data: {e}")
        sys.exit(2)

    if a.json:
        print(json.dumps(res['json'], indent=2, default=str, ensure_ascii=False))
    else:
        print_single_report(res['metrics'], res['setups'], res['archetypes'], ticker)


if __name__ == '__main__':
    main()
