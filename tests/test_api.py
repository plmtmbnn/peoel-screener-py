import os
import sys
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

# Pastikan path import terarah ke project root
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.main import app

client = TestClient(app)

SAMPLE_TRADES_CSV = """time,action,price,lot,trade_number,buy_order_number,sell_order_number,amount,change
09:00:19,sell,198,782,1001,5001,6001,15483600,-2.0
09:01:05,buy,200,1000,1002,5002,6002,20000000,+1.0
09:02:10,buy,202,1500,1003,5003,6003,30300000,+2.0
09:05:00,buy,204,2000,1004,5004,6004,40800000,+3.0
15:49:50,buy,210,1200,1005,5005,6005,25200000,+6.0
"""

SAMPLE_ORDER_TRADE_JSON = """{
  "date": "2026-10-23",
  "data": {
    "book_total": {
      "big_money_buy_percentage": 55,
      "big_money_sell_percentage": 45,
      "big_money_rt": {
        "percentage": {"buy": 58, "sell": 42}
      }
    },
    "big_money_rt": {
      "buy": [{"lot": {"raw": 4000}}],
      "sell": [{"lot": {"raw": 2000}}]
    }
  }
}"""


def test_root():
    res = client.get("/")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "online"
    assert data["version"] == "3.1.0"


def test_health():
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"


def test_archetypes_endpoint():
    res = client.get("/api/v1/archetypes")
    assert res.status_code == 200
    data = res.json()
    assert data["count"] == len(data["archetypes"])
    assert data["count"] >= 9


def test_setups_endpoint():
    res = client.get("/api/v1/setups")
    assert res.status_code == 200
    data = res.json()
    assert data["count"] == 8
    assert len(data["setups"]) == 8


def test_analyze_endpoint():
    files = {
        "trades_file": ("test_trades.csv", SAMPLE_TRADES_CSV, "text/csv"),
        "book_file": ("test_book.json", SAMPLE_ORDER_TRADE_JSON, "application/json"),
    }
    data = {"ticker": "TEST"}
    res = client.post("/api/v1/analyze", files=files, data=data)
    assert res.status_code == 200
    payload = res.json()
    assert payload["ticker"] == "TEST"
    assert "action" in payload
    assert "ohlc" in payload
    assert "levels" in payload
    assert "setups" in payload
    assert len(payload["setups"]) == 8


def test_scan_zip_endpoint():
    import io
    import zipfile

    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w") as zf:
        zf.writestr("running-trade_TEST.csv", SAMPLE_TRADES_CSV)
        zf.writestr("trade-book_TEST.json", SAMPLE_ORDER_TRADE_JSON)
    zip_buf.seek(0)

    files = {"zip_file": ("watchlist.zip", zip_buf.getvalue(), "application/zip")}
    res = client.post("/api/v1/scan-zip", files=files)
    assert res.status_code == 200
    data = res.json()
    assert data["total_scanned"] == 1
    assert len(data["leaderboard"]) == 1
    assert data["leaderboard"][0]["ticker"] == "TEST"


def test_vercel_asgi_wrapper():
    from api.index import app as vercel_app

    c = TestClient(vercel_app)
    # Test path unwrapping when Vercel rewrites to entrypoint
    res_health = c.get("/api/index.py", headers={"x-matched-path": "/health"})
    assert res_health.status_code == 200
    assert res_health.json()["status"] == "ok"

    res_root = c.get("/api/index.py", headers={"x-matched-path": "/"})
    assert res_root.status_code == 200
    assert res_root.json()["status"] == "online"

    res_archetypes = c.get("/api/index.py", headers={"x-matched-path": "/api/v1/archetypes"})
    assert res_archetypes.status_code == 200
    assert res_archetypes.json()["count"] >= 9


