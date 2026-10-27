# AI Agent Project Context & Mandates

This document provides foundational context, architectural boundaries, and operational mandates for any AI coding assistant (Antigravity, Claude Code, Cursor, Codex, Gemini) working in this repository.

> [!IMPORTANT]
> **Strict Zero-Dependency & Pure Python Standard Library Mandate**:
> The core computation engine in this repository is intentionally built with zero heavy mathematical dependencies.
> - **Zero External Math/Data Libraries**: Strictly forbid adding `pandas`, `numpy`, `scipy`, or similar packages to `requirements.txt`. All computations, data parsing, and state evaluations must rely exclusively on Python's built-in standard library (`math`, `collections`, `bisect`, `csv`, `json`, `io`, `pathlib`).
> - **Performance Rationale**: Pure Python standard library algorithms ensure instantaneous cold starts (<500ms), deterministic microsecond tick processing, minimal memory overhead, and friction-free deployment.

> [!IMPORTANT]
> **Zero-Disk In-Memory Processing & Residual File Hygiene Mandate**:
> File processing and stream handling must protect system storage and prevent memory leaks:
> - **In-Memory Streaming (`/api/v1/analyze`)**: Single-stock analysis must process uploaded trade files directly from memory (`io.StringIO` and in-memory byte buffers) without writing temporary files to disk.
> - **FastAPI BackgroundTasks Spool Cleanup**: For uploads exceeding 1 MB spooled to disk by Starlette, endpoints must register `safe_close_upload` from `app.cleanup` into `BackgroundTasks` to guarantee temporary OS files are unlinked immediately after response transmission.
> - **Session Auto-Purge for Batch ZIP (`/api/v1/scan-zip`)**: Uploaded ZIP archives must extract exclusively into unique UUID session directories (`temp_residuals/scan_{uuid}`) and must be purged completely via `BackgroundTasks` once the leaderboard is generated.
> - **Lifespan Startup/Shutdown Pruning**: The FastAPI `lifespan` handler must clean stale residual files older than 1 hour on startup and perform a sweep on shutdown.

> [!IMPORTANT]
> **Market Microstructure Domain Invariant Mandate**:
> Domain rules reflect Indonesian Stock Exchange (BEI / IDX) market mechanics and must be preserved as invariants:
> - **Broker Fee Round-Trip (0.40%)**: All Net Risk/Reward Ratio (Net RRR) calculations must deduct estimated round-trip transaction costs: 0.15% buy fee + 0.25% sell fee/tax. Emit warning `⚠️ TP1 ≤ biaya transaksi` whenever target profit does not cover transaction costs.
> - **Continuous vs Auction Session Isolation (09:00:00 to 15:50:00 WIB)**: Only trades executed during the continuous session are included in VWAP, interval delta, and staircase calculations. Pre-opening and closing auction trades must remain isolated to prevent price distortion.
> - **Extended Tick Guard (> 2 Ticks)**: If market price trades more than 2 ticks above the ideal entry zone, status must flag `🟡 SETUP VALID TAPI EXTENDED - TUNGGU PULLBACK` to prevent FOMO entries.
> - **Adaptive Block Lot Calculation**: Block size thresholds must be computed dynamically based on ~Rp 1 Billion nominal value or >= 1% continuous volume, with fixed 50,000 lot mode available only as an explicit option.
> - **Intraday Archetypes & Playbook Setups**: Preserve classification integrity for all 10 intraday archetypes and 8 intraday setups in `app/screener.py`.
> - **Swing Trading Engine (Horizon 1 - 2 Weeks / 5 - 10 Trading Days)**:
>   - Implemented in `app/swing_screener.py` and exposed via `POST /api/v1/analyze-swing`.
>   - 5-Layer Composite Scoring Architecture (0 - 100):
>     1. Layer 1 (Price Action & Multi-Day Volume Profile, 25%): VCP contraction, Ascending Value Area migration, 10D/20D/60D VPOC, Stage 2 markup detection, volume dry-up, and volume breakout.
>     2. Layer 2 (Order Flow & PLIR, 25%): Reconstructed parent-order Big Money flows across 1D, 5D, 10D, 22D; anchored delta from swing low; red-day absorption; and Paint-the-Tape Bull-Trap divergence detection.
>     3. Layer 3 (Participant Profile & Bandar Cost Basis, 20%): Conviction ratio (|net| / gross), institutional classification (`HIGH_CONVICTION_INST` >= 45% retention), and separation of Active In-Range Accumulators from Trapped Legacy Positions (>25% underwater).
>     4. Layer 4 (Broker Trajectory & Cumulative Slopes, 20%): 1D/5D/10D/20D cumulative delta trajectory, seller exhaustion, distributor buyback, and crowd capitulation.
>     5. Layer 5 (Network Topology & Anti-Wash, 10%): Self-matching ratio, circular wash rotation, and Many-to-Few absorption vs Few-to-Many dispersion.
>   - Dynamic Weight Normalization: When optional files are omitted, active layer base weights automatically rebalance to 100% (e.g. 2-file mode normalizes Layer 1 and Layer 2 to 50% each).
>   - 6 Swing Playbook Setups:
>     1. Multi-Day Silent Absorption & VCP Base
>     2. Ascending Value Area & Breakout Valid
>     3. Pullback to Demand & Anchored VWAP Re-test
>     4. Capitulation Double-Bottom & Seller Exhaustion
>     5. Institutional Cost-Basis Discount Accumulation
>     6. Multi-Day Distribution / Markdown Waterfall Trap
>   - Swing Action Taxonomy: `STRONG_BUY` (score >= 80), `BUY_ON_WEAKNESS` (score 60 - 79 or tape-painted breakout), `WAIT_FOR_TRIGGER` (score 40 - 59 with valid base/reversal setup), `AVOID` (ARB floor lock or illiquid), `AVOID_DISTRIBUTION` (active markdown waterfall or trapped legacy distribution).
> - **Trap Detection & Broken Support Verification**: Integrate morning ORB bull trap (`orb_bull_trap`), passive bid wall fractures (`broken_walls`), low-level bid collapse (`bid_collapsed_low`), and floor offer locks (`floor_lock`) into safety actions and JSON schemas.
> - **ZIP Pair Key Timestamp Tolerance**: Maintain minute/second download drift tolerance in `pair_key` to avoid unlinked running trade CSV and trade-book JSON pairs.
> - **Client Contract Immutability**: Maintain backward compatibility for the output dictionary structure returned by `app.screener.analyze_stock` and `app.swing_screener.analyze_swing_stock` to avoid breaking frontend clients.

> [!IMPORTANT]
> **Upstream Live IDX API & Cloudflare Proxy Routing Mandate**:
> Handling external market summaries from the official exchange requires managing serverless network constraints:
> - **Cloudflare Datacenter Interception Guard**: Cloudflare on `idx.co.id` challenges cloud/datacenter IP ranges (AWS Lambda, Vercel) with 403 Forbidden. Outbound calls to `https://www.idx.co.id/primary/TradingSummary/GetStockSummary` must support residential proxy routing via `IDX_PROXY_URL` (or `HTTPS_PROXY` / `IDX_PROXY`).
> - **HTTP & SOCKS5 Support**: Proxy routing must support both HTTP/HTTPS and SOCKS5 schemes via `httpx[socks]`.
> - **Actionable 502 Guidance**: If blocked with 403, the endpoint must return a descriptive 502 Bad Gateway response directing operators to configure `IDX_PROXY_URL` rather than propagating opaque upstream errors.

> [!IMPORTANT]
> **Mandatory Ponytail Lazy Senior Developer Standard**:
> AI assistants must follow ponytail principles on every task:
> - **Core Philosophy**: "The best code is the code never written. Solve the whole problem with the least new code." The shortest working diff that completely solves the task wins.
> - **Blast Radius Analysis**: Inspect every touchpoint before writing code: callers, tests, fixtures, config, and exports. Check what the change could break.
> - **Hierarchy of Minimal Implementation**:
>   1. Skip unrequested features, options, and speculative flexibility.
>   2. Reuse existing helpers in `app.cleanup` and `app.screener` before writing new utilities.
>   3. Rely on Python standard library features before proposing new dependencies.
>   4. Avoid premature abstractions, wrappers, or boilerplate layers.
> - **Non-Negotiables**: Never cut input validation, error handling, security checks, or domain accuracy.
> - **Response Conclusion**: End every response with 1 to 2 lines stating what was skipped or not checked, and any risk the user must know.

> [!IMPORTANT]
> **Mandatory Antislop Skill Suite Integration Standard**:
> AI assistants must adhere to antislop filters across all generated code, comments, and copy:
> - **Code Comments (`antislop-code`)**:
>   - Strictly forbid decorative box-drawing banners (`# ===`, `/* === */`, ASCII borders).
>   - Strictly forbid restating the obvious (`# initialize variable`), empty section tags (`# Helpers`, `# Logic`), and step-by-step workflow narration (`# Step 1: parse input`).
>   - Preserve comments that explain non-obvious business rules, market microstructure nuances, hardware/OS constraints, or workarounds. Comments must stay short, natural, and sentence-case.
> - **Copywriting & Documentation (`antislop-copywriting`)**:
>   - Strictly forbid em dash characters (`—`) in prose, documentation, and comments. Use commas, colons, hyphens, or parentheses instead.
>   - Use clear, grounded, technical explanations. Avoid empty marketing buzzwords ("revolutionary", "seamless", "next-generation").
>   - Avoid chatbot conversational fillers in final deliverables.

> [!IMPORTANT]
> **Strict Git Commit & Push Policy**:
> NEVER stage, commit, or push changes unless explicitly requested by the user for each occurrence. This is a strict mandate without exception.

---

## 🛠 Tech Stack & Environment

- **Framework**: FastAPI (>=0.115.0) on Starlette
- **ASGI Server**: Uvicorn standard (>=0.32.0)
- **Language & Runtime**: Python 3.12+ / Python 3.15
- **Schema & Validation**: Pydantic v2 (>=2.9.0)
- **HTTP Client**: HTTPX with SOCKS support (httpx[socks] >= 0.27.0)
- **Testing Framework**: Pytest (>=8.0.0) with FastAPI `TestClient`
- **Standard Library Modules**: `math`, `collections`, `bisect`, `csv`, `json`, `io`, `pathlib`, `tempfile`, `shutil`

---

## 📁 Repository Structure

```text
peoel-screener-py/
├── app/
│   ├── __init__.py          # Package metadata and API version
│   ├── main.py              # FastAPI app, route handlers, CORS, background tasks, lifespan
│   ├── cleanup.py           # In-memory spool release, file deletion, stale residual sweeps
│   ├── screener.py          # Pure Python market microstructure & tape reading engine (v3.1)
│   └── swing_screener.py    # Multi-day 1 - 2 weeks swing trading engine (5-layer composite scoring)
├── tests/
│   ├── test_api.py          # Pytest suite covering intraday API endpoints and scan workflows
│   └── test_swing_screener.py # Pytest suite covering 7 BEI swing archetypes and 2-file fallback
├── temp_residuals/          # Transient directory for temporary ZIP extraction and cleanup
├── requirements.txt         # Pinned project dependencies
├── run.py                   # Local development launcher
├── README.md                # Indonesian technical documentation and API reference
└── AGENTS.md                # Root pointer file for cross-agent discovery
```

---

## 🧪 Quality Assurance & Verification Standards

1. **Mandatory Test Execution**:
   - Before declaring any task complete, run the swing screener test suite and verify that all tests pass:
     ```powershell
     .\.venv\Scripts\pytest tests/test_swing_screener.py -v -p no:cacheprovider
     ```
   - All tests must pass with zero failures and zero unhandled exceptions.
2. **Test Coverage for New Functionality**:
   - Every new route, query parameter, form field, or calculation adjustment must include corresponding test cases in `tests/test_api.py` (intraday) or `tests/test_swing_screener.py` (swing).
3. **Residual Leak Prevention**:
   - Verify that test runs do not leave residual files or orphan directories in `temp_residuals/` or the OS temporary folder.
