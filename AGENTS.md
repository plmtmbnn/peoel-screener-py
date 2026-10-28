# AI Agent Instructions for Peoel Screener Py

This repository contains the FastAPI backend and high-speed market microstructure engine for Indonesia Stock Exchange (BEI / IDX) tape reading and tick analysis.

The comprehensive project context, architectural invariants, and agent mandates are defined in:
**[`.agents/AGENTS.md`](file:///.agents/AGENTS.md)**

All AI coding assistants (Antigravity, Claude Code, Cursor, Codex, Gemini) must follow the canonical mandates defined in that file.

---

## ⚡ Core Operational Mandates

1. **Strict Zero-Dependency Rule**:
   - Strictly forbid adding `pandas`, `numpy`, `scipy`, or heavy math packages.
   - All analytics and data parsing must use Python's built-in standard library (`math`, `collections`, `bisect`, `csv`, `json`).
2. **Zero-Disk In-Memory Processing & Cleanup**:
   - Single-ticker analyses (`/api/v1/analyze`) process trades in-memory (`io.StringIO`).
   - Multipart uploads (>1 MB) spooled to disk must be registered with FastAPI `BackgroundTasks` via `safe_close_upload` in `app.cleanup`.
   - Batch ZIP scans (`/api/v1/scan-zip`) extract only to `temp_residuals/scan_{uuid}` and must be purged immediately post-response.
3. **Microstructure Domain Invariants**:
   - Deduct 0.40% round-trip broker fees (0.15% buy + 0.25% sell/tax) in Net RRR. Warn if `TP1 ≤ biaya transaksi`.
   - Continuous session is strictly 09:00:00 to 15:50:00 WIB. Auction trades (pre-opening and closing) must be isolated.
   - Guard against extended entries (>2 ticks above ideal entry zone triggers `🟡 SETUP VALID TAPI EXTENDED - TUNGGU PULLBACK`).
   - Maintain client contract stability for `app.screener.analyze_stock` and `app.swing_screener.analyze_swing_stock` output dictionaries.
4. **Swing Trading Screener Engine (Horizon 1 - 2 Weeks / 5 - 10 Trading Days)**:
   - Module `app.swing_screener` and endpoint `POST /api/v1/analyze-swing`.
   - 5-Layer Composite Scoring Architecture (0 - 100): Price Action & Multi-Day VP (25%), Order Flow & PLIR (25%), Participant Profile & Bandar Cost Basis (20%), Broker Trajectory & Cumulative Slopes (20%), Network Topology & Anti-Wash (10%).
   - Dynamic weight normalization: automatically rebalances active base weights to 100% when optional files are omitted (e.g. 2-file mode normalizes Layer 1 and Layer 2 to 50% each).
   - 6 Playbook Setups & Execution Invariants:
     1. Multi-Day Silent Absorption & VCP Base (requires 5D net buy > 0, confirmed VCP contraction, non-distribution execution regime, and base ceiling <= VAH * 1.04).
     2. Ascending Value Area & Breakout Valid (momentum breakout above VAH with volume confirmation).
     3. Pullback to Demand & Anchored VWAP Re-test (strictly requires MA50 / Stage 2 Uptrend AND proximity to AVWAP/VPOC <= 4% before marking status READY).
     4. Capitulation Double-Bottom & Seller Exhaustion (volume dry-up retest with seller exhaustion and daily reversal close >= VWAP).
     5. Institutional Cost-Basis Discount Accumulation (adaptive non-collapsing entry range between intraday VWAP and Close with minimum 2-tick buffer).
     6. Multi-Day Distribution / Markdown Waterfall Trap (triggers on ARB locks, >Rp 1B 5D net dumps, trapped legacy liquidation, or drawdowns >15%; prioritizes capital protection AVOID_DISTRIBUTION).
   - Measured Move Swing Target Caps: TP1 capped at +25% and TP2 capped at +45% (or nearest overhead supply wall) to eliminate unrealistic post-crash target distortions and distorted risk/reward ratios.
   - Precision Microstructure Filters: Differentiates Active In-Range Institutional Accumulators from Trapped Legacy Positions (>25% underwater), flags Paint-the-Tape Bull Traps, identifies Passive Iceberg Absorption, and detects Circular Wash Rotation.
5. **Upstream Live IDX Data & Cloudflare Proxy Routing**:
   - `GET /api/v1/stock-summary` (alias `GET /api/v1/idx/stock-summary`) queries `https://www.idx.co.id/primary/TradingSummary/GetStockSummary`.
   - Cloudflare on `idx.co.id` challenges cloud datacenter IP ranges (AWS Lambda, Vercel) with 403 Forbidden. Outbound requests must support residential proxy routing via `IDX_PROXY_URL` (or `HTTPS_PROXY` / `IDX_PROXY`) with `httpx[socks]` for both HTTP and SOCKS5.
   - If blocked by Cloudflare (403), return an actionable 502 Bad Gateway response directing operators to configure `IDX_PROXY_URL`.
6. **Trap Detection & Batch Pairing Resilience**:
   - Morning ORB Bull Trap (`orb_bull_trap`): Flag false breakouts where early buying pierces ORB High then collapses below ORB Low.
   - Broken Bid Wall Tracking (`broken_walls`): Quantify breached passive bid walls to detect forced liquidations.
   - Bid Collapsed at Low (`bid_collapsed_low`): Identify when session low flips to offer queue, confirming broken support.
   - Floor Offer Lock (`floor_lock`): Quantify time locked at price floor / ARB to prevent buying illiquid traps.
   - ZIP Pair Key Timestamp Tolerance: `pair_key` in `app/screener.py` must tolerate download timestamp minute/second differences when pairing running trade CSV with trade-book JSON.
7. **Ponytail Lazy Senior Developer Standard**:
   - Shortest working diff wins.
   - Inspect blast radius before writing code: callers, tests, fixtures, config.
   - End every response with 1 to 2 lines on what was skipped or not checked, and any risk.
8. **Antislop Comment & Copywriting Hygiene**:
   - Code comments: no decorative banner separators (`# ===`), no workflow step narration (`# Step 1:`), no restating the obvious. Keep comments short and explain non-obvious *why*.
   - Copywriting: zero em dashes (`—`) in text or comments. Use commas, colons, hyphens, or parentheses instead.
9. **Strict Git Commit & Push Policy**:
   - NEVER stage, commit, or push changes unless explicitly requested by the user for each occurrence.
10. **Mandatory Test Verification**:
   - Always run and verify all tests before completing any task:
     ```powershell
     .\.venv\Scripts\pytest tests/test_swing_screener.py -v -p no:cacheprovider
     ```

<!-- antislop:start -->
## antislop
For code comments or copywriting work, read the matching skill:
- Code comments: `skills/antislop-code/SKILL.md`
- Copy & text: `skills/antislop-copywriting/SKILL.md`
<!-- antislop:end -->
