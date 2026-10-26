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
   - Maintain client contract stability for `app.screener.analyze_stock` output dictionary.
4. **Ponytail Lazy Senior Developer Standard**:
   - Shortest working diff wins.
   - Inspect blast radius before writing code: callers, tests, fixtures, config.
   - End every response with 1 to 2 lines on what was skipped or not checked, and any risk.
5. **Antislop Comment & Copywriting Hygiene**:
   - Code comments: no decorative banner separators (`# ===`), no workflow step narration (`# Step 1:`), no restating the obvious. Keep comments short and explain non-obvious *why*.
   - Copywriting: zero em dashes (`—`) in text or comments. Use commas, colons, hyphens, or parentheses instead.
6. **Strict Git Commit & Push Policy**:
   - NEVER stage, commit, or push changes unless explicitly requested by the user for each occurrence.
7. **Mandatory Test Verification**:
   - Always run and verify all tests before completing any task:
     ```powershell
     .\.venv\Scripts\pytest
     ```

<!-- antislop:start -->
## antislop
For code comments or copywriting work, read the matching skill:
- Code comments: `skills/antislop-code/SKILL.md`
- Copy & text: `skills/antislop-copywriting/SKILL.md`
<!-- antislop:end -->
