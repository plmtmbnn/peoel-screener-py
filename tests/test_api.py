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


def test_pair_key_timestamp_tolerance():
    from app.screener import pair_key
    assert pair_key("running-trade_PTRO_20261026-2220.csv") == pair_key("trade-book_PTRO_20261026-2219.json")
    assert pair_key("running-trade_DOOH_20261026-2218.csv") == pair_key("trade-book_DOOH_20261026-2217.json")


def test_stock_summary_endpoint():
    from unittest.mock import patch, AsyncMock
    mock_payload = {
        "draw": 0,
        "recordsTotal": 1,
        "recordsFiltered": 1,
        "data": [{"StockCode": "AADI", "Previous": 11375.0, "Close": 11500.0}],
    }
    mock_resp = AsyncMock()
    mock_resp.status_code = 200
    mock_resp.json = lambda: mock_payload

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_resp
        res = client.get("/api/v1/stock-summary")
        assert res.status_code == 200
        data = res.json()
        assert data["recordsTotal"] == 1
        assert data["data"][0]["StockCode"] == "AADI"

        res_alias = client.get("/api/v1/idx/stock-summary?length=10&start=0&date=2026-10-23")
        assert res_alias.status_code == 200


def test_stock_summary_upstream_error():
    from unittest.mock import patch, AsyncMock
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_resp = AsyncMock()
        mock_resp.status_code = 500
        mock_resp.text = "Internal Server Error"
        mock_get.return_value = mock_resp

        res = client.get("/api/v1/stock-summary")
        assert res.status_code == 502


def test_stock_summary_cloudflare_403():
    from unittest.mock import patch, AsyncMock
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_resp = AsyncMock()
        mock_resp.status_code = 403
        mock_resp.text = "Just a moment..."
        mock_get.return_value = mock_resp

        res = client.get("/api/v1/stock-summary")
        assert res.status_code == 502
        assert "Cloudflare 403" in res.json()["detail"]


def test_stock_summary_proxy_env():
    from unittest.mock import patch, AsyncMock, MagicMock
    with patch.dict(os.environ, {"IDX_PROXY_URL": "http://1.2.3.4:8080"}):
        with patch("httpx.AsyncClient", autospec=True) as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__.return_value = mock_client
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"draw": 0, "recordsTotal": 0, "data": []}
            mock_client.get.return_value = mock_resp

            res = client.get("/api/v1/stock-summary")
            assert res.status_code == 200
            _, kwargs = mock_client_cls.call_args
            assert kwargs.get("proxy") == "http://1.2.3.4:8080"


def test_stock_summary_proxy_407_error():
    from unittest.mock import patch, AsyncMock
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        import httpx
        mock_get.side_effect = httpx.ProxyError("407 Proxy Authentication Required")

        res = client.get("/api/v1/stock-summary")
        assert res.status_code == 502
        assert "407 Proxy Authentication Required" in res.json()["detail"]






