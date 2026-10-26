# Peoel Screener Py (FastAPI Backend)

Backend engine mikrostruktur pasar dan tape reading saham Bursa Efek Indonesia (BEI) berbasis **FastAPI** modern dan Python Standard Library. Dirancang khusus untuk melayani komputasi data tick berkecepatan tinggi tanpa dependensi komputasi berat, serta siap diintegrasikan langsung dengan frontend modern seperti **Next.js**.

---

## ⚡ Fitur Utama Engine (v3.1)

1. **Ambang Blok Adaptif (`block_lot`)**:
   - Menghitung batas transaksi blok institusi secara dinamis berdasarkan nominal Rupiah ($\approx \text{Rp } 1\text{ Miliar}$ atau $\ge 1\%$ volume kontinu).
   - Saham nominal tinggi (misal: PTRO Rp 3.000) otomatis menggunakan ambang 3.000 lot, bukan patokan statis 50.000 lot (Rp 15 Miliar) yang tidak realistis.
2. **Kalkulasi Net Risk/Reward Ratio (Net RRR) & Potongan Fee Broker**:
   - Menghitung rasio RRR bersih setelah dipotong estimasi biaya transaksi: fee beli (0.15%) + fee jual/PPh (0.25%) = **0.40% round-trip**.
   - Dilengkapi peringatan otomatis `⚠️ TP1 ≤ biaya transaksi` jika target profit tidak cukup menutup fee broker.
3. **Deteksi Extended / Pengejaran Harga (`extended_ticks`)**:
   - Jika harga saat ini sudah bergerak $> 2$ tick di atas zona entry ideal, status otomatis berubah menjadi:
     `🟡 SETUP VALID TAPI EXTENDED - TUNGGU PULLBACK`.
   - Melindungi trader dan algoritma eksekusi dari jebakan FOMO HAKA di pucuk.
4. **Pemisahan Sesi Kontinu vs Lelang (`09:00:00` s/d `15:50:00`)**:
   - Transaksi lelang pembukaan (*pre-opening*) dan penutupan (*closing auction*) dipisahkan agar tidak mendistorsi VWAP, interval delta, dan pembentukan anak tangga (*staircase*).
5. **Konteks Market Profile & Sesi Berjalan**:
   - **Value Area 70%** (VAL dan VAH) di sekitar VPOC.
   - **Opening Range Breakout (ORB 15-Menit)**: Memetakan batas range 09:00–09:15.
   - **Flow 15 Menit Terakhir & Kecepatan Tape**: Mengukur speed of tape dan mendeteksi *Bearish/Bullish Delta Divergence*.
6. **10 Arketipe Mikrostruktur BEI**:
   - *Growth Markup* (VKTR / BUVA)
   - *Low-Float ARA Lock* (ASLI)
   - *Lightning Rocket & Churn* (FORU)
   - *Staircase Precision* (MBMA / KETR)
   - *Nimble Skirmish* (OASA)
   - *Whale Bazooka War* (BRMS)
   - *Range-Bound Squeeze* (PTRO / DOOH)
   - *Distribution Blue Chip* (AMRT / SMIL)
   - *Speculative Collapse* (STRK)
7. **8 Setup Playbook Intraday Teruji**:
   - Setup 1: Zero-Ask Low Reversal (Bullish Reversal)
   - Setup 2: Twin-Sweep Breakout (Momentum Aggressive)
   - Setup 3: VPOC Re-test Absorption (Trend Following)
   - Setup 4: Staircase Momentum Continuation (Trend Continuation)
   - Setup 5: Selling Climax Exhaustion Reversal (Contrarian V-Shape)
   - Setup 6: Level Psikologis Breakout (Round Number Breakout)
   - Setup 7: Bearish Waterfall / Dump Collapse (Avoid / Immediate Cut Loss)
   - Setup 8: Range-Bound Squeeze Absorption (Range Scalping / Ping-Pong Support)

---

## 🛡️ Penanganan Residu File (*Residual File Handlers*)

Aplikasi ini mengimplementasikan manajemen residu file berlapis agar sistem penyimpanan server tetap bersih:

1. **Zero-Disk In-Memory Processing (`/api/v1/analyze`)**:
   - Data CSV dan JSON dibaca langsung dari memory buffer (`io.StringIO` dan in-memory bytes).
   - Tidak ada file fisik sementara yang disimpan ke storage/disk untuk analisis saham tunggal standar.
2. **FastAPI BackgroundTasks Spool Cleanup**:
   - Untuk file upload $> 1\text{ MB}$ yang dispool ke folder temporary OS oleh Starlette, endpoint mendaftarkan handler `safe_close_upload` ke `BackgroundTasks`.
   - File temporary OS dilepaskan dan dihapus segera setelah HTTP response dikembalikan ke client.
3. **Session Auto-Purge untuk Batch ZIP (`/api/v1/scan-zip`)**:
   - Arsip `.zip` diekstrak ke folder sesi ber-UUID unik (`temp_residuals/scan_{uuid}`).
   - Folder ekstraksi tersebut otomatis dihapus tuntas melalui background task saat response dikirim.
4. **Lifespan Startup/Shutdown Purge**:
   - Event handler `lifespan` secara berkala menyapu file residual lama (> 1 jam) jika proses server sempat terhenti mendadak.

---

## 📁 Struktur Direktori

```text
peoel-screener-py/
├── app/
│   ├── __init__.py          # Metadata paket & versi API
│   ├── main.py              # FastAPI app, routing, CORS, & background tasks
│   ├── cleanup.py           # Utilitas pembersihan file residual & spool
│   └── screener.py          # Core engine analisis mikrostruktur BEI v3.1
├── tests/
│   └── test_api.py          # Pytest suite untuk seluruh endpoint
├── .gitignore               # Konfigurasi ignore file temp, venv, & cache
├── requirements.txt         # Dependensi Python
├── run.py                   # Script launcher lokal sederhana
└── README.md                # Dokumentasi proyek
```

---

## 🚀 Panduan Memulai Cepat (Quick Start)

### 1. Masuk ke Direktori Proyek
```bash
cd peoel-screener-py
```

### 2. Siapkan Virtual Environment
**Windows (PowerShell):**
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

**Windows (Command Prompt):**
```cmd
python -m venv .venv
.\.venv\Scripts\activate.bat
```

**Linux / macOS:**
```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Pasang Dependensi
```bash
pip install -r requirements.txt
```

### 4. Jalankan Server
**Menggunakan runner bawaan:**
```bash
python run.py
```

**Atau menggunakan Uvicorn langsung (dengan hot-reload):**
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

* Server aktif di: **`http://localhost:8000`**
* Dokumentasi Interaktif Swagger UI: **`http://localhost:8000/docs`**
* Dokumentasi ReDoc: **`http://localhost:8000/redoc`**

---

## 📡 Dokumentasi Endpoint API

### 1. Health & Status
* **`GET /`**: Menampilkan ringkasan status API dan jumlah arketipe/setup yang didukung.
* **`GET /health`**: Endpoint monitoring sederhana untuk probe k8s / load balancer.

### 2. Analisis Saham Tunggal (`POST /api/v1/analyze`)
Menganalisis file Running Trade dan Trade-Book satu saham.

**Format Request:** `multipart/form-data`

| Parameter | Tipe | Wajib | Keterangan |
| :--- | :--- | :---: | :--- |
| `trades_file` | File (CSV) | Ya | File CSV Running Trade BEI |
| `book_file` | File (JSON) | Ya | File JSON Order Trade Chart / Trade-Book |
| `ticker` | String | Tidak | Kode ticker 4 huruf (default: `"TICKER"`, misal: `PTRO`) |
| `fee_buy` | Float | Tidak | Fee beli broker dalam persen (default: `0.15`) |
| `fee_sell` | Float | Tidak | Fee jual + pajak dalam persen (default: `0.25`) |
| `block_mode` | String | Tidak | Mode ambang blok: `"adaptive"` atau `"fixed"` |

**Contoh Response JSON:**
```json
{
  "ticker": "PTRO",
  "date": "2026-10-23",
  "snapshot_time": "15:49:54",
  "is_live": false,
  "action": {
    "key": "RANGE",
    "label": "RANGE-BOUND SQUEEZE (PING-PONG SCALP ONLY) - TUNGGU HARGA KE SUPPORT",
    "icon": "🟡"
  },
  "ohlc": {
    "o": 3070,
    "h": 3140,
    "l": 3030,
    "c": 3090,
    "last": 3100,
    "prev_close": 3070,
    "ara": 3830,
    "arb": 2610
  },
  "volume": 274606,
  "turnover": 84784260000,
  "levels": {
    "vwap": 3087.4,
    "vpoc": 3100,
    "val": 3070,
    "vah": 3110,
    "orb": {
      "high": 3110,
      "low": 3030,
      "status": "DI DALAM RANGE"
    }
  },
  "block_lot": 3000,
  "tick": 10,
  "archetypes": [
    { "name": "Range-Bound Squeeze (PTRO / DOOH)", "score": 90.0 },
    { "name": "Whale Bazooka War (BRMS)", "score": 80.0 }
  ],
  "setups": [
    {
      "id": 8,
      "name": "Range-Bound Squeeze Absorption",
      "score": 100.0,
      "met": [
        ["Rentang terkompresi ketat & flat", "Rentang: 3.6% (11 tick) | Chg: +0.65%"],
        ["Turnover likuid (> Rp 15B)", "Turnover: Rp 80.34B"]
      ],
      "pending": [],
      "params": {
        "status": "RANGE ACTIVE - HARGA DI TENGAH/ATAS, TUNGGU KE SUPPORT",
        "actionable": false,
        "entry_zone": "3040 - 3050",
        "cut_loss": "3020 (-0.98%)",
        "tp1": "3100 (+1.64%)",
        "tp2": "3130 (+2.62%)",
        "rrr": "1 : 1.7 (gross) | 1 : 0.9 (net fee 0.40%)",
        "trigger_rule": "DISIPLIN PING-PONG: beli hanya di support bawah dengan bid menebal."
      }
    }
  ]
}
```

### 3. Pemindaian Batch Arsip (`POST /api/v1/scan-zip`)
Mengunggah satu file arsip `.zip` berisi kumpulan file CSV dan JSON untuk seluruh saham.

**Format Request:** `multipart/form-data`
* `zip_file`: File `.zip`

**Contoh Response JSON:**
```json
{
  "total_scanned": 13,
  "leaderboard": [
    {
      "ticker": "STRK",
      "close": 130,
      "change": -28.96,
      "val": 61880000000,
      "arch": "Speculative Collapse",
      "best_setup": "Bearish Waterfall / Dump",
      "setup_pct": 100.0,
      "status": "🚨 DANGER"
    },
    {
      "ticker": "PTRO",
      "close": 3090,
      "change": 0.65,
      "val": 84780000000,
      "arch": "Range-Bound Squeeze",
      "best_setup": "Range-Bound Squeeze Abso",
      "setup_pct": 100.0,
      "status": "🟡 RANGE"
    }
  ]
}
```

### 4. Ringkasan Perdagangan Saham IDX (Live Data)
* **`GET /api/v1/stock-summary`** (alias: `GET /api/v1/idx/stock-summary`):
  Mengambil data seluruh ringkasan saham langsung dari upstream IDX (`https://www.idx.co.id/primary/TradingSummary/GetStockSummary?length=9999&start=0`).
  * Query parameters:
    * `length` (default: `9999`): Jumlah record yang diambil.
    * `start` (default: `0`): Offset data awal.
    * `date` (opsional): Format `YYYYMMDD` atau `YYYY-MM-DD`.
  * Konfigurasi Proxy / Cloudflare Bypass (Vercel / Cloud Datacenter):
    * Cloudflare pada `idx.co.id` memblokir IP serverless/datacenter (AWS/Vercel) dengan challenge 403.
    * Opsi 1 (Scrape.do, Otomatis Bypass Cloudflare): Set `IDX_PROXY_URL` (atau `SCRAPEDO_TOKEN`) dengan token Scrape.do atau URL Scrape.do.
    * Opsi 2 (Residential Proxy): Set `IDX_PROXY_URL` dengan format `http://user:pass@host:port` atau `socks5://host:port`.



### 5. Referensi Arketipe & Setup
* **`GET /api/v1/archetypes`**: Daftar 10 arketipe mikrostruktur BEI.
* **`GET /api/v1/setups`**: Daftar 8 setup playbook intraday beserta kategori dan deskripsinya.


---

## 📋 Persyaratan Format Data Input

### 1. File Running Trade (CSV)
Kolom wajib yang harus ada di header CSV:
* `time`: Waktu transaksi (`HH:MM:SS`)
* `action`: Aksi agresi (`buy` atau `sell`)
* `price`: Harga pelaksanaan
* `lot`: Jumlah lot transaksi
* `amount`: Nilai transaksi Rupiah (opsional, jika tidak ada dihitung `price * lot * 100`)
* `buy_order_number` / `sell_order_number`: ID order induk untuk rekonstruksi parent order

### 2. File Trade-Book / Order Trade Chart (JSON)
Objek JSON standar bursa/sekuritas yang memuat:
* `data.book_total`: Akumulasi order buy/sell
* `data.big_money_rt`: Data kumulatif transaksi Big Money

---

## 💻 Contoh Pengujian Request via cURL

```bash
# Analisis Saham PTRO
curl -X POST "http://localhost:8000/api/v1/analyze" \
  -F "trades_file=@running-trade_PTRO.csv" \
  -F "book_file=@trade-book_PTRO.json" \
  -F "ticker=PTRO"

# Batch Scan via File Zip
curl -X POST "http://localhost:8000/api/v1/scan-zip" \
  -F "zip_file=@watchlist_data.zip"
```

---

## 🌐 Contoh Integrasi Frontend (Next.js / TypeScript)

```typescript
// app/services/screenerService.ts
export interface ScreenerResponse {
  ticker: string;
  action: { key: string; label: string; icon: string };
  ohlc: { o: number; h: number; l: number; c: number; last: number };
  levels: { vwap: number; vpoc: number; val: number; vah: number };
  archetypes: Array<{ name: string; score: number }>;
  setups: Array<{ id: number; name: string; score: number; params: any }>;
}

export async function requestIntradayAnalysis(
  csvFile: File,
  jsonFile: File,
  tickerCode: string
): Promise<ScreenerResponse> {
  const formData = new FormData();
  formData.append("trades_file", csvFile);
  formData.append("book_file", jsonFile);
  formData.append("ticker", tickerCode.toUpperCase());

  const response = await fetch("http://localhost:8000/api/v1/analyze", {
    method: "POST",
    body: formData,
  });

  if (!response.ok) {
    const errorBody = await response.json();
    throw new Error(errorBody.detail || "Analisis saham gagal.");
  }

  return response.json();
}
```

---

## 🧪 Menjalankan Test Suite (Pytest)

Proyek ini telah dilengkapi automated test untuk seluruh endpoint dan skenario upload file:

```bash
pytest tests/test_api.py -v
```

---

## 🚢 Panduan Deployment Produksi

Untuk lingkungan produksi, jalankan Uvicorn dengan beberapa worker process di belakang reverse proxy:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4
```

**Rekomendasi Konfigurasi Reverse Proxy (Nginx):**
Pastikan batas ukuran body upload mencukupi untuk file CSV/ZIP berukuran besar:
```nginx
client_max_body_size 35M;
```
