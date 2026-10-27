import csv
import io
import json
import logging
import os
import shutil
import tempfile
import uuid
import zipfile
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional, List, Dict, Any
import urllib.parse

import httpx
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, BackgroundTasks, Query
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

try:
    from app.screener import analyze_stock, CFG, find_pairs_in_dir, compute_all, eval_setups, classify, decide_action, get_setup_score
    from app.swing_screener import analyze_swing_stock
    from app.cleanup import safe_close_upload, remove_path, clean_stale_files
except ImportError:
    from screener import analyze_stock, CFG, find_pairs_in_dir, compute_all, eval_setups, classify, decide_action, get_setup_score
    from swing_screener import analyze_swing_stock
    from cleanup import safe_close_upload, remove_path, clean_stale_files

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("peoel.screener.api")

TEMP_BASE_DIR = Path(os.environ.get("TEMP_RESIDUALS_DIR") or Path(tempfile.gettempdir()) / "peoel_residuals")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifecycle manager:
    - Menyiapkan direktori temp untuk residual file
    - Membersihkan file residual basi (> 1 jam) saat startup dan shutdown
    """
    try:
        TEMP_BASE_DIR.mkdir(parents=True, exist_ok=True)
        cleaned = clean_stale_files(TEMP_BASE_DIR, max_age_seconds=3600)
        if cleaned:
            logger.info(f"Startup: {cleaned} file residual lama dibersihkan.")
    except Exception as e:
        logger.warning(f"Startup: gagal inisialisasi temp dir {TEMP_BASE_DIR}: {e}")
    yield
    # Shutdown cleanup
    try:
        if TEMP_BASE_DIR.exists():
            clean_stale_files(TEMP_BASE_DIR, max_age_seconds=0)
            logger.info("Shutdown: pembersihan residual selesai.")
    except Exception as e:
        logger.warning(f"Shutdown: gagal pembersihan residual: {e}")



app = FastAPI(
    title="Peoel Intraday Screener & Tape Reading API",
    description="Engine Mikrostruktur & Tape Reading Saham Bursa Efek Indonesia (BEI) v3.1",
    version="3.1.0",
    lifespan=lifespan,
)

# CORS Middleware agar Next.js (localhost:3000 / Vercel) dapat mengakses API tanpa hambatan
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/", tags=["Info"])
async def root():
    return {
        "service": "Peoel Intraday Screener & Tape Reading BEI API",
        "version": "3.1.0",
        "status": "online",
        "supported_archetypes": 10,
        "supported_setups": 8,
        "docs_url": "/docs",
        "health_check": "/health"
    }


@app.get("/health", tags=["Info"])
async def health_check():
    return {"status": "ok", "service": "screener-api", "version": "3.1.0"}


@app.post("/api/v1/analyze", tags=["Screener"])
async def analyze_single_ticker(
    background_tasks: BackgroundTasks,
    trades_file: UploadFile = File(..., description="File CSV Running Trade BEI"),
    book_file: UploadFile = File(..., description="File JSON Trade-Book / Order Trade Chart"),
    ticker: str = Form("TICKER", description="Kode ticker saham 4 huruf (misal: PTRO, VKTR, BRMS)"),
    fee_buy: Optional[float] = Form(None, description="Fee beli broker dalam persen (default: 0.15)"),
    fee_sell: Optional[float] = Form(None, description="Fee jual broker + tax dalam persen (default: 0.25)"),
    block_mode: Optional[str] = Form("adaptive", description="'adaptive' (~Rp 1B) atau 'fixed' (50k lot)"),
):
    """
    Menganalisis mikrostruktur satu saham secara mendalam:
    - Running trade dan trade book dibaca langsung dari stream memori (tanpa residual disk jika memungkinkan).
    - Menjadwalkan penutupan dan pembersihan UploadFile temporary via BackgroundTasks setelah response dikirim.
    """
    # 1. Daftarkan pembersihan file upload ke BackgroundTasks (pasti dieksekusi setelah response kembali)
    background_tasks.add_task(safe_close_upload, trades_file)
    background_tasks.add_task(safe_close_upload, book_file)

    ticker_clean = (ticker or "TICKER").strip().upper()

    try:
        # 2. Baca isi file ke memory stream
        trades_raw_bytes = await trades_file.read()
        book_raw_bytes = await book_file.read()

        if not trades_raw_bytes:
            raise HTTPException(status_code=400, detail="File CSV Running Trade kosong.")
        if not book_raw_bytes:
            raise HTTPException(status_code=400, detail="File JSON Trade-Book kosong.")

        # Decode CSV toleran UTF-8-sig
        trades_text = trades_raw_bytes.decode("utf-8-sig", errors="replace")
        csv_reader = csv.DictReader(io.StringIO(trades_text))
        trades_list = list(csv_reader)

        if not trades_list:
            raise HTTPException(status_code=400, detail="Baris data pada CSV Running Trade tidak ditemukan.")

        # Parse JSON
        try:
            book_dict = json.loads(book_raw_bytes.decode("utf-8", errors="replace"))
        except json.JSONDecodeError as je:
            raise HTTPException(status_code=400, detail=f"Format file JSON tidak valid: {str(je)}")

        # 3. Konfigurasi override jika dikirimkan oleh FE
        cfg_override = {}
        if fee_buy is not None: cfg_override['fee_buy_pct'] = fee_buy
        if fee_sell is not None: cfg_override['fee_sell_pct'] = fee_sell
        if block_mode: cfg_override['block_mode'] = block_mode

        # 4. Eksekusi engine mikrostruktur dalam threadpool agar tidak memblokir event loop async FastAPI
        analysis_result = await run_in_threadpool(
            analyze_stock,
            trades_source=trades_list,
            json_source=book_dict,
            ticker=ticker_clean,
            cfg_override=cfg_override
        )

        return JSONResponse(content=analysis_result["json"])

    except HTTPException:
        raise
    except ValueError as ve:
        logger.error(f"Validation error saat memproses {ticker_clean}: {ve}")
        raise HTTPException(status_code=422, detail=str(ve))
    except Exception as e:
        logger.exception(f"Unexpected error saat memproses {ticker_clean}: {e}")
        raise HTTPException(status_code=500, detail=f"Gagal memproses data saham {ticker_clean}: {str(e)}")


async def _read_optional_json(file: Optional[UploadFile], label: str) -> Optional[Dict[str, Any]]:
    if not file:
        return None
    raw_bytes = await file.read()
    if not raw_bytes:
        return None
    try:
        return json.loads(raw_bytes.decode("utf-8", errors="replace"))
    except json.JSONDecodeError as je:
        raise HTTPException(status_code=400, detail=f"Format JSON {label} tidak valid: {str(je)}")


@app.post("/api/v1/analyze-swing", tags=["Screener"])
async def analyze_swing_ticker(
    background_tasks: BackgroundTasks,
    historical_file: UploadFile = File(..., description="File CSV Historical Trade (historical-trade_*.csv)"),
    trade_book_file: UploadFile = File(..., description="File JSON Trade-Book 5m (trade-book-5m_*.json)"),
    market_detector_file: Optional[UploadFile] = File(None, description="File JSON Market Detector (market-detector_*.json)"),
    running_trade_chart_file: Optional[UploadFile] = File(None, description="File JSON Running Trade Chart (running-trade-chart_*.json)"),
    broker_distribution_file: Optional[UploadFile] = File(None, description="File JSON Broker Distribution (broker-distribution_*.json)"),
    ticker: str = Form("TICKER", description="Kode ticker saham 4 huruf (misal: DOOH, PTRO, BRMS)"),
    fee_buy: Optional[float] = Form(None, description="Fee beli broker dalam persen (default: 0.15)"),
    fee_sell: Optional[float] = Form(None, description="Fee jual broker + tax dalam persen (default: 0.25)"),
):
    for f in (historical_file, trade_book_file, market_detector_file, running_trade_chart_file, broker_distribution_file):
        if f is not None:
            background_tasks.add_task(safe_close_upload, f)

    ticker_clean = (ticker or "TICKER").strip().upper()

    try:
        hist_bytes = await historical_file.read()
        tb_bytes = await trade_book_file.read()

        if not hist_bytes:
            raise HTTPException(status_code=400, detail="File CSV Historical Trade kosong.")
        if not tb_bytes:
            raise HTTPException(status_code=400, detail="File JSON Trade-Book kosong.")

        hist_text = hist_bytes.decode("utf-8-sig", errors="replace")
        hist_rows = list(csv.DictReader(io.StringIO(hist_text)))
        if not hist_rows:
            raise HTTPException(status_code=400, detail="Baris data pada CSV Historical Trade tidak ditemukan.")

        try:
            tb_dict = json.loads(tb_bytes.decode("utf-8", errors="replace"))
        except json.JSONDecodeError as je:
            raise HTTPException(status_code=400, detail=f"Format JSON Trade-Book tidak valid: {str(je)}")

        md_dict = await _read_optional_json(market_detector_file, "Market Detector")
        rtc_dict = await _read_optional_json(running_trade_chart_file, "Running Trade Chart")
        bd_dict = await _read_optional_json(broker_distribution_file, "Broker Distribution")

        cfg_override: Dict[str, Any] = {}
        if fee_buy is not None:
            cfg_override["fee_buy_pct"] = fee_buy
        if fee_sell is not None:
            cfg_override["fee_sell_pct"] = fee_sell

        result = analyze_swing_stock(
            historical_source=hist_rows,
            trade_book_source=tb_dict,
            market_detector_source=md_dict,
            running_trade_chart_source=rtc_dict,
            broker_distribution_source=bd_dict,
            ticker=ticker_clean,
            cfg_override=cfg_override,
        )
        return JSONResponse(content=result)

    except HTTPException:
        raise
    except ValueError as ve:
        logger.error(f"Validation error saat memproses swing {ticker_clean}: {ve}")
        raise HTTPException(status_code=422, detail=str(ve))
    except Exception as e:
        logger.exception(f"Unexpected error saat memproses swing {ticker_clean}: {e}")
        raise HTTPException(status_code=500, detail=f"Gagal memproses data swing {ticker_clean}: {str(e)}")


@app.post("/api/v1/scan-zip", tags=["Screener"])
async def scan_batch_zip(
    background_tasks: BackgroundTasks,
    zip_file: UploadFile = File(..., description="File arsip .zip berisi kumpulan CSV & JSON"),
):
    """
    Batch Scanner:
    - Menerima file .zip yang berisi pasangan file CSV dan JSON.
    - Diekstrak ke temporary session folder ber-UUID unik.
    - Mengembalikan leaderboard hasil scan untuk seluruh saham.
    - Menghapus folder temporary dan file residual setelah response kembali via BackgroundTasks.
    """
    background_tasks.add_task(safe_close_upload, zip_file)

    session_id = f"scan_{uuid.uuid4().hex[:10]}"
    temp_extract_dir = TEMP_BASE_DIR / session_id

    # Pastikan direktori sementara terhapus setelah response kembali
    background_tasks.add_task(remove_path, temp_extract_dir)

    try:
        temp_extract_dir.mkdir(parents=True, exist_ok=True)
        zip_bytes = await zip_file.read()

        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
            z.extractall(temp_extract_dir)

        # Jalankan pencarian pasangan file di folder hasil ekstrak
        def execute_batch():
            pairs = find_pairs_in_dir(str(temp_extract_dir))
            summary = []
            for c, j, tk in pairs:
                try:
                    res = analyze_stock(c, j, ticker=tk)
                    m = res['metrics']
                    act = res['action']
                    archs = res['archetypes']
                    setups = res['setups']
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
                    logger.warning(f"Error memproses item {tk} dalam zip: {e}")

            summary.sort(key=lambda x: (x['rank'], -x['setup_pct']))
            return summary

        summary_list = await run_in_threadpool(execute_batch)

        return {
            "total_scanned": len(summary_list),
            "leaderboard": summary_list
        }

    except zipfile.BadZipFile:
        raise HTTPException(status_code=400, detail="File yang diunggah bukan arsip ZIP yang valid.")
    except Exception as e:
        logger.exception(f"Gagal memproses batch zip: {e}")
        raise HTTPException(status_code=500, detail=f"Gagal memproses arsip batch: {str(e)}")


@app.get("/api/v1/archetypes", tags=["Referensi"])
async def list_archetypes():
    """Daftar Arketipe Mikrostruktur Bursa Efek Indonesia."""
    archetypes = [
        {"name": "Growth Markup (VKTR / BUVA)", "type": "Bullish Trend", "desc": "Markup harga bertahap didukung akumulasi konsisten dan support dinamis."},
        {"name": "Low-Float ARA Lock (ASLI)", "type": "Momentum Shakeout", "desc": "Shakeout awal disusul twin sweep agresif menuju batas Auto Rejection Atas (ARA)."},
        {"name": "Lightning Rocket & Churn (FORU)", "type": "Volatility Churn", "desc": "Lonjakan harga cepat di awal sesi disusul rotasi volume tinggi di resistance."},
        {"name": "Staircase Precision (MBMA / KETR)", "type": "Stepwise Trend", "desc": "Tren naik teratur dengan pembentukan higher close antar-interval dan volume stabil."},
        {"name": "Nimble Skirmish (OASA)", "type": "Agile Scalp", "desc": "Kenaikan terukur saham lapis dua dengan konfirmasi zero-ask low dan pantulan bersih."},
        {"name": "Whale Bazooka War (BRMS)", "type": "Institutional Battle", "desc": "Transaksi blok besar institusi (≥ Rp 1 Miliar) dengan penyerapan likuiditas dan pantulan V-Shape."},
        {"name": "Range-Bound Squeeze (PTRO / DOOH)", "type": "Liquidity Coil", "desc": "Kompresi rentang sempit (< 5%) dengan konsentrasi penyerapan volume (≥ 50%) di sekitar VPOC."},
        {"name": "Distribution Blue Chip (AMRT / SMIL)", "type": "Stealth Distribution", "desc": "Distribusi bertahap menggunakan TWAP slicing sell di balik antrean order."},
        {"name": "Speculative Collapse (STRK)", "type": "Panic Waterfall", "desc": "Penarikan bid mendadak disusul tekanan jual agresif tanpa penyerapan likuiditas pembeli."}
    ]
    return {
        "count": len(archetypes),
        "archetypes": archetypes
    }


@app.get("/api/v1/setups", tags=["Referensi"])
async def list_setups():
    """Daftar 8 Setup Playbook Intraday BEI."""
    return {
        "count": 8,
        "setups": [
            {"id": 1, "name": "Zero-Ask Low Reversal", "category": "BULLISH REVERSAL", "desc": "Level harga terendah didominasi 100% HAKI (zero-ask) yang bertahan sebagai support dan memantul minimal 2 tick."},
            {"id": 2, "name": "Twin-Sweep Breakout", "category": "MOMENTUM AGGRESSIVE", "desc": "Dua order beli agresif (≥ batas blok) yang dieksekusi berurutan dalam rentang waktu singkat."},
            {"id": 3, "name": "VPOC Re-test Absorption", "category": "TREND FOLLOWING", "desc": "Pengujian kembali area Volume Point of Control (VPOC) sesi dengan penyerapan antrean bid tebal."},
            {"id": 4, "name": "Staircase Momentum Continuation", "category": "TREND CONTINUATION", "desc": "Tren naik bertahap dengan pembentukan higher close baru di atas level VWAP."},
            {"id": 5, "name": "Selling Climax Exhaustion Reversal", "category": "CONTRARIAN V-SHAPE", "desc": "Klimaks volume jual ekstrem yang gagal menekan harga lebih dalam, disusul pantulan tajam V-Shape."},
            {"id": 6, "name": "Level Psikologis Breakout", "category": "ROUND NUMBER BREAKOUT", "desc": "Penembusan bersih level angka bulat psikologis dengan dukungan volume transaksi signifikan."},
            {"id": 7, "name": "Bearish Waterfall / Dump Collapse", "category": "AVOID / IMMEDIATE CUT LOSS", "desc": "Penurunan harga tajam tanpa pantulan akibat dominasi penjualan agresif dan ketiadaan pembeli."},
            {"id": 8, "name": "Range-Bound Squeeze Absorption", "category": "RANGE SCALPING", "desc": "Peluang transaksi bolak-balik pada saham rentang sempit dengan entri di batas demand support."}
        ]
    }


IDX_STOCK_SUMMARY_URL = "https://www.idx.co.id/primary/TradingSummary/GetStockSummary"
IDX_HEADERS = {
    "Referer": "https://www.idx.co.id/",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9,id;q=0.8",
}


def extract_scrape_do_token(raw_url: Optional[str]) -> Optional[str]:
    """Ekstraksi token Scrape.do dari URL API, proxy URL, atau token mentah."""
    if not raw_url:
        return None
    val = raw_url.strip(" \t\r\n\"'")
    if "scrape.do" in val:
        parsed = urllib.parse.urlparse(val)
        qs = urllib.parse.parse_qs(parsed.query)
        if "token" in qs:
            return qs["token"][0]
        if parsed.username:
            return parsed.username
    if len(val) >= 30 and not val.startswith(("http://", "https://", "socks5://")):
        return val
    return None


@app.get("/api/v1/stock-summary", tags=["IDX Data"])
@app.get("/api/v1/idx/stock-summary", tags=["IDX Data"])
async def get_idx_stock_summary(
    length: int = Query(9999, ge=1, description="Jumlah data yang diambil"),
    start: int = Query(0, ge=0, description="Offset data yang diambil"),
    date: Optional[str] = Query(None, description="Tanggal ringkasan perdagangan (opsional, format YYYYMMDD atau YYYY-MM-DD)"),
):
    """
    Mengambil data ringkasan perdagangan saham terkini langsung dari IDX primary API.
    Mendukung Scrape.do (otomatis bypass Cloudflare) via SCRAPEDO_TOKEN atau IDX_PROXY_URL,
    serta proxy standar via IDX_PROXY_URL / HTTPS_PROXY jika dihosting di datacenter/cloud.
    Endpoint upstream: https://www.idx.co.id/primary/TradingSummary/GetStockSummary
    """
    params = {"length": length, "start": start}
    if date:
        params["date"] = date.replace("-", "")

    proxy_url = os.environ.get("IDX_PROXY_URL") or os.environ.get("IDX_PROXY") or os.environ.get("HTTPS_PROXY")
    scrape_token = os.environ.get("SCRAPEDO_TOKEN") or extract_scrape_do_token(proxy_url)

    # Jalur Scrape.do: otomatis menyelesaikan Cloudflare Bot Challenge di level upstream
    if scrape_token:
        target_with_params = f"{IDX_STOCK_SUMMARY_URL}?{urllib.parse.urlencode(params)}"
        encoded_target = urllib.parse.quote(target_with_params, safe="")
        scrape_endpoint = f"https://api.scrape.do/?token={scrape_token}&url={encoded_target}"
        try:
            async with httpx.AsyncClient(timeout=45.0) as client:
                resp = await client.get(scrape_endpoint)
                if resp.status_code != 200:
                    logger.error(f"Scrape.do upstream error status={resp.status_code}: {resp.text[:200]}")
                    raise HTTPException(
                        status_code=502,
                        detail=f"Scrape.do mengembalikan status {resp.status_code}: {resp.text[:200]}",
                    )
                return resp.json()
        except httpx.HTTPError as err:
            logger.exception(f"Gagal menghubungi Scrape.do API: {err}")
            raise HTTPException(status_code=502, detail=f"Gagal menghubungi Scrape.do API: {str(err)}")
        except HTTPException:
            raise
        except Exception as err:
            logger.exception(f"Unexpected error via Scrape.do: {err}")
            raise HTTPException(status_code=500, detail=f"Terjadi kesalahan internal: {str(err)}")

    if proxy_url:
        proxy_url = proxy_url.strip(" \t\r\n\"'")

    client_kwargs: Dict[str, Any] = {
        "timeout": 20.0,
        "follow_redirects": True,
    }
    if proxy_url:
        client_kwargs["proxy"] = proxy_url

    try:
        async with httpx.AsyncClient(**client_kwargs) as client:
            resp = await client.get(IDX_STOCK_SUMMARY_URL, headers=IDX_HEADERS, params=params)
            if resp.status_code == 403:
                logger.error("IDX upstream memblokir request (Cloudflare Bot Challenge 403).")
                raise HTTPException(
                    status_code=502,
                    detail=(
                        "Server IDX memblokir request cloud datacenter (Cloudflare 403). "
                        "Silakan set environment variable IDX_PROXY_URL di dashboard Vercel dengan residential proxy atau token Scrape.do."
                    ),
                )
            if resp.status_code != 200:
                logger.error(f"IDX API error status={resp.status_code}: {resp.text[:200]}")
                raise HTTPException(
                    status_code=resp.status_code if resp.status_code < 500 else 502,
                    detail=f"Server IDX mengembalikan status {resp.status_code}",
                )
            return resp.json()
    except httpx.ProxyError as err:
        logger.exception(f"Koneksi/autentikasi proxy gagal: {err}")
        detail_msg = f"Koneksi proxy gagal: {str(err)}"
        if "407" in str(err):
            detail_msg = (
                "Proxy mengembalikan 407 Proxy Authentication Required. "
                "Pastikan format IDX_PROXY_URL menggunakan Proxy Username & Password dari menu Proxy List/Settings di dashboard Webshare (bukan email/password login akun Webshare)."
            )
        raise HTTPException(status_code=502, detail=detail_msg)
    except httpx.HTTPError as err:
        logger.exception(f"Gagal menghubungi IDX API: {err}")
        raise HTTPException(status_code=502, detail=f"Gagal menghubungi upstream IDX API: {str(err)}")
    except HTTPException:
        raise
    except Exception as err:
        logger.exception(f"Unexpected error saat fetching IDX stock summary: {err}")
        raise HTTPException(status_code=500, detail=f"Terjadi kesalahan internal: {str(err)}")


