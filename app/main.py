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

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, BackgroundTasks, Query
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

try:
    from app.screener import analyze_stock, CFG, find_pairs_in_dir, compute_all, eval_setups, classify, decide_action, get_setup_score
    from app.cleanup import safe_close_upload, remove_path, clean_stale_files
except ImportError:
    from screener import analyze_stock, CFG, find_pairs_in_dir, compute_all, eval_setups, classify, decide_action, get_setup_score
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
            raise HTTPException(status_code=400, detail="Data baris pada CSV Running Trade tidak ditemukan.")

        # Parse JSON
        try:
            book_dict = json.loads(book_raw_bytes.decode("utf-8", errors="replace"))
        except json.JSONDecodeError as je:
            raise HTTPException(status_code=400, detail=f"File JSON tidak valid: {str(je)}")

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
        raise HTTPException(status_code=400, detail="File upload bukan file ZIP yang valid.")
    except Exception as e:
        logger.exception(f"Gagal memproses batch zip: {e}")
        raise HTTPException(status_code=500, detail=f"Gagal memproses file batch: {str(e)}")


@app.get("/api/v1/archetypes", tags=["Referensi"])
async def list_archetypes():
    """Daftar Arketipe Mikrostruktur Bursa Efek Indonesia."""
    archetypes = [
        {"name": "Growth Markup (VKTR / BUVA)", "type": "Bullish Trend", "desc": "Markup bertahap dengan akumulasi konsisten dan support dinamis."},
        {"name": "Low-Float ARA Lock (ASLI)", "type": "Momentum Shakeout", "desc": "Shakeout awal disusul twin sweep agresif melompat ke batas ARA."},
        {"name": "Lightning Rocket & Churn (FORU)", "type": "Volatility Churn", "desc": "Lonjakan vertikal cepat di pagi hari disusul distribusi di pucuk."},
        {"name": "Staircase Precision (MBMA / KETR)", "type": "Stepwise Trend", "desc": "Pola tangga naik presisi dengan higher close antar-interval dan volume stabil."},
        {"name": "Nimble Skirmish (OASA)", "type": "Agile Scalp", "desc": "Kenaikan terukur saham lapis dua dengan zero-ask low terkonfirmasi dan rebound bersih."},
        {"name": "Whale Bazooka War (BRMS)", "type": "Institutional Battle", "desc": "Pertarungan tembakan bazooka institusi (≥ Rp 1B) disusul pantulan V-Shape."},
        {"name": "Range-Bound Squeeze (PTRO / DOOH)", "type": "Liquidity Coil", "desc": "Kompresi rentang ketat (< 5%) dengan penyerapan 50%+ volume di sekitar VPOC."},
        {"name": "Distribution Blue Chip (AMRT / SMIL)", "type": "Stealth Distribution", "desc": "Pelemahan bertahap dengan TWAP slicing sell tersembunyi di balik order antrean."},
        {"name": "Speculative Collapse (STRK)", "type": "Panic Waterfall", "desc": "Penarikan bid mendadak disusul guyuran HAKI vertikal menuju dasar harga."}
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
            {"id": 1, "name": "Zero-Ask Low Reversal", "category": "BULLISH REVERSAL", "desc": "Level low 100% HAKI (0% buy) yang bertahan dan memantul minimal 2 tick."},
            {"id": 2, "name": "Twin-Sweep Breakout", "category": "MOMENTUM AGGRESSIVE", "desc": "Dua parent buy agresif ≥ batas blok yang dieksekusi berurutan dalam rentang singkat."},
            {"id": 3, "name": "VPOC Re-test Absorption", "category": "TREND FOLLOWING", "desc": "Harga kembali menguji area volume terbesar sesi dan diserap oleh antrean bid besar."},
            {"id": 4, "name": "Staircase Momentum Continuation", "category": "TREND CONTINUATION", "desc": "Tren naik bertahap dengan pembentukan pijakan harga baru di atas VWAP."},
            {"id": 5, "name": "Selling Climax Exhaustion Reversal", "category": "CONTRARIAN V-SHAPE", "desc": "Lonjakan volume jual ekstrem yang gagal menekan harga lebih dalam lalu memantul tajam."},
            {"id": 6, "name": "Level Psikologis Breakout", "category": "ROUND NUMBER BREAKOUT", "desc": "Penembusan bersih level angka bulat yang didukung penyerapan likuiditas tinggi."},
            {"id": 7, "name": "Bearish Waterfall / Dump Collapse", "category": "AVOID / IMMEDIATE CUT LOSS", "desc": "Kejatuhan harga tanpa pantulan akibat dominasi HAKI masif dan pembeli absen."},
            {"id": 8, "name": "Range-Bound Squeeze Absorption", "category": "RANGE SCALPING", "desc": "Strategi ping-pong pada saham terkompresi dengan beli di batas demand support."}
        ]
    }
