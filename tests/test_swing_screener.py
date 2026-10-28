import asyncio
import io
import json
import sys
from pathlib import Path

from fastapi import BackgroundTasks, UploadFile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.main import analyze_swing_ticker
from app.swing_screener import analyze_swing_stock


def _make_untr_fixtures():
    """Realistic Stage-2 Institutional Accumulation & Breakout fixtures calibrated to UNTR."""
    rows = []
    # 20 trading days leading up to 2026-10-27 breakout at Rp 26,500
    base_prices = [
        ("2026-09-30", 25900, 26100, 25000, 25150, 25433, 52110, 132533525000, 10847, -750, -2.90),
        ("2026-10-01", 25225, 25850, 25150, 25800, 25575, 29489, 75417367500, 7721, 650, 2.58),
        ("2026-10-02", 25775, 25825, 25375, 25450, 25573, 21172, 54143942500, 6235, -350, -1.36),
        ("2026-10-05", 25450, 25450, 25000, 25150, 25175, 20055, 50488502500, 6670, -300, -1.18),
        ("2026-10-06", 25400, 25625, 25225, 25250, 25420, 26417, 67152267500, 7259, 100, 0.40),
        ("2026-10-07", 25175, 25475, 24975, 25275, 25222, 23244, 58626665000, 6468, 25, 0.10),
        ("2026-10-08", 25275, 25950, 25100, 25925, 25660, 32603, 83660665000, 8851, 650, 2.57),
        ("2026-10-09", 25625, 25975, 25550, 25825, 25794, 21586, 55678395000, 5604, -100, -0.39),
        ("2026-10-12", 25750, 26325, 25575, 25925, 26000, 32879, 85485402500, 8868, 100, 0.39),
        ("2026-10-13", 25950, 26125, 24800, 24800, 25243, 47885, 120878042500, 12442, -1125, -4.34),
        ("2026-10-14", 24800, 25250, 24250, 24975, 24755, 50948, 126123892500, 13037, 175, 0.71),
        ("2026-10-15", 25000, 25025, 24250, 24450, 24511, 35383, 86728162500, 9912, -525, -2.10),
        ("2026-10-16", 24200, 24225, 22650, 22925, 23232, 92689, 215332230000, 22929, -1525, -6.24),
        ("2026-10-19", 22100, 22475, 21050, 22325, 21816, 111492, 243229770000, 28863, -600, -2.62),
        ("2026-10-20", 22700, 23450, 22550, 23375, 23051, 56925, 131215495000, 14807, 1050, 4.70),
        ("2026-10-21", 23375, 24350, 23300, 24350, 23945, 50670, 121329095000, 13179, 975, 4.17),
        ("2026-10-22", 24350, 25375, 24100, 25050, 24874, 57731, 143602570000, 13301, 700, 2.87),
        ("2026-10-23", 25150, 25175, 24375, 24950, 24751, 30881, 76435052500, 7456, -100, -0.40),
        ("2026-10-26", 24950, 25200, 24900, 25000, 25052, 15360, 38480340000, 4695, 50, 0.20),
        ("2026-10-27", 25250, 26500, 25125, 26500, 25936, 53209, 138003687500, 13684, 1500, 6.00),
    ]
    for dt, o, h, l, c, avg, vol, val, freq, chg, chg_p in base_prices:
        rows.append({
            "date": dt, "open": o, "high": h, "low": l, "close": c,
            "average": avg, "volume": vol, "value": val, "frequency": freq,
            "change": chg, "change_percentage": chg_p,
        })

    tb = {
        "data": {
            "buy": [
                {"date": r["date"], "lot": {"raw": int(r["volume"] * 0.56)}, "value": {"raw": int(r["value"] * 0.56)}, "frequency": {"raw": int(r["frequency"] * 0.52)}}
                for r in rows
            ],
            "sell": [
                {"date": r["date"], "lot": {"raw": int(r["volume"] * 0.44)}, "value": {"raw": int(r["value"] * 0.44)}, "frequency": {"raw": int(r["frequency"] * 0.48)}}
                for r in rows
            ],
            "big_money_buy": [
                {"date": r["date"], "lot": {"raw": int(r["volume"] * 0.22)}, "value": {"raw": int(r["value"] * 0.22)}, "frequency": {"raw": 120}}
                for r in rows
            ],
            "big_money_sell": [
                {"date": r["date"], "lot": {"raw": int(r["volume"] * 0.14)}, "value": {"raw": int(r["value"] * 0.14)}, "frequency": {"raw": 110}}
                for r in rows
            ],
            "big_money_net_values": [
                {"date": r["date"], "value": {"raw": int(r["value"] * 0.08)}}
                for r in rows
            ],
            "big_money_rt": {
                "buy": [{"date": r["date"], "lot": {"raw": 6000}, "value": {"raw": 15000000000}, "frequency": {"raw": 90}} for r in rows],
                "sell": [{"date": r["date"], "lot": {"raw": 3500}, "value": {"raw": 8500000000}, "frequency": {"raw": 70}} for r in rows],
                "net_values": [{"date": r["date"], "value": {"raw": 6500000000}} for r in rows],
            },
        }
    }

    md = {
        "data": {
            "from": "2026-07-27",
            "to": "2026-10-27",
            "bandar_detector": {
                "broker_accdist": "Acc",
                "average": 24465.25,
                "total_buyer": 32,
                "total_seller": 46,
                "top1": {"percent": 32.90},
                "top3": {"percent": 14.23},
                "top5": {"percent": 10.30},
                "avg5": {"percent": 19.79},
            },
            "broker_summary": {
                "brokers_buy": [
                    {
                        "netbs_broker_code": "AK", "type": "Asing",
                        "blot": "523344", "blotv": "91852600",
                        "bval": "1283542515000", "bvalv": "2252657687500",
                        "freq": "91041", "netbs_buy_avg_price": "24525.79",
                    },
                    {
                        "netbs_broker_code": "RX", "type": "Asing",
                        "blot": "129254", "blotv": "18875900",
                        "bval": "310085680000", "bvalv": "452812702500",
                        "freq": "32681", "netbs_buy_avg_price": "24221.79",
                    },
                    {
                        "netbs_broker_code": "BK", "type": "Asing",
                        "blot": "81232", "blotv": "32920600",
                        "bval": "195725512500", "bvalv": "805000000000",
                        "freq": "57188", "netbs_buy_avg_price": "24522.49",
                    },
                ],
                "brokers_sell": [
                    {
                        "netbs_broker_code": "ZP", "type": "Asing",
                        "slot": "-292319", "slotv": "64899600",
                        "sval": "-709627495000", "svalv": "1590000000000",
                        "freq": "84139", "netbs_sell_avg_price": "24467.74",
                    },
                ],
            },
        }
    }

    rtc = {
        "data": {
            "broker_chart_data": [
                {
                    "type": "TYPE_CHART_VOLUME",
                    "charts": [
                        {
                            "broker_code": "AK",
                            "chart": [
                                {"date": r["date"], "value": {"raw": str(480000 + i * 2200)}}
                                for i, r in enumerate(rows)
                            ],
                        },
                        {
                            "broker_code": "RX",
                            "chart": [
                                {"date": r["date"], "value": {"raw": str(20000 + i * 5500)}}
                                for i, r in enumerate(rows)
                            ],
                        },
                    ],
                }
            ]
        }
    }

    bd = {
        "data": {
            "by_volume": {
                "top_broker_buy": [
                    {
                        "detail": {"code": "AK", "amount": 918526},
                        "distribute_to": [
                            {"code": "ZP", "amount": 168522},
                            {"code": "AK", "amount": 141907},
                            {"code": "YU", "amount": 120614},
                            {"code": "CC", "amount": 80146},
                        ],
                    }
                ],
                "top_broker_sell": [
                    {
                        "detail": {"code": "ZP", "amount": 648996},
                        "distribute_to": [
                            {"code": "AK", "amount": 168522},
                            {"code": "RX", "amount": 39892},
                        ],
                    }
                ],
            }
        }
    }
    return rows, tb, md, rtc, bd


def _make_strk_fixtures():
    """Realistic Post-Suspension Blow-Off & Paint-the-Tape Bull-Trap fixtures calibrated to STRK."""
    rows = [
        {"date": "2026-10-08", "open": 57, "high": 59, "low": 56, "close": 57, "average": 57, "volume": 120956, "value": 686168100, "frequency": 672, "change": -1, "change_percentage": -1.72},
        {"date": "2026-10-09", "open": 57, "high": 76, "low": 57, "close": 76, "average": 71, "volume": 2708037, "value": 19198207100, "frequency": 13537, "change": 19, "change_percentage": 33.33},
        {"date": "2026-10-12", "open": 76, "high": 100, "low": 76, "close": 90, "average": 93, "volume": 3592023, "value": 33490935600, "frequency": 28496, "change": 14, "change_percentage": 18.42},
        {"date": "2026-10-13", "open": 90, "high": 94, "low": 78, "close": 89, "average": 86, "volume": 1364631, "value": 11707827300, "frequency": 9897, "change": -1, "change_percentage": -1.11},
        {"date": "2026-10-14", "open": 89, "high": 120, "low": 89, "close": 102, "average": 106, "volume": 4767624, "value": 50666702800, "frequency": 37464, "change": 13, "change_percentage": 14.61},
        {"date": "2026-10-15", "open": 102, "high": 110, "low": 91, "close": 95, "average": 100, "volume": 1618824, "value": 16216526900, "frequency": 12553, "change": -7, "change_percentage": -6.86},
        {"date": "2026-10-16", "open": 95, "high": 104, "low": 91, "close": 96, "average": 98, "volume": 888446, "value": 8716679400, "frequency": 6692, "change": 1, "change_percentage": 1.05},
        {"date": "2026-10-19", "open": 96, "high": 101, "low": 88, "close": 89, "average": 92, "volume": 511711, "value": 4700011600, "frequency": 4208, "change": -7, "change_percentage": -7.29},
        {"date": "2026-10-20", "open": 89, "high": 114, "low": 89, "close": 102, "average": 107, "volume": 2445513, "value": 26101342600, "frequency": 20336, "change": 13, "change_percentage": 14.61},
        {"date": "2026-10-21", "open": 103, "high": 137, "low": 102, "close": 137, "average": 127, "volume": 3853482, "value": 49080168600, "frequency": 26908, "change": 35, "change_percentage": 34.31},
        {"date": "2026-10-22", "open": 137, "high": 137, "low": 137, "close": 137, "average": 137, "volume": 0, "value": 0, "frequency": 0, "change": 0, "change_percentage": 0.00},
        {"date": "2026-10-23", "open": 183, "high": 183, "low": 128, "close": 130, "average": 152, "volume": 4072811, "value": 61882468300, "frequency": 42514, "change": -7, "change_percentage": -5.11},
        {"date": "2026-10-26", "open": 130, "high": 154, "low": 127, "close": 139, "average": 144, "volume": 2742388, "value": 39481690400, "frequency": 26843, "change": 9, "change_percentage": 6.92},
        {"date": "2026-10-27", "open": 143, "high": 144, "low": 130, "close": 130, "average": 136, "volume": 1207537, "value": 16448697100, "frequency": 11594, "change": -9, "change_percentage": -6.47},
    ]

    tb = {
        "data": {
            "buy": [{"date": r["date"], "lot": {"raw": int(r["volume"] * 0.52)}, "value": {"raw": int(r["value"] * 0.52)}, "frequency": {"raw": max(1, int(r["frequency"] * 0.55))}} for r in rows],
            "sell": [{"date": r["date"], "lot": {"raw": int(r["volume"] * 0.48)}, "value": {"raw": int(r["value"] * 0.48)}, "frequency": {"raw": max(1, int(r["frequency"] * 0.45))}} for r in rows],
            "big_money_buy": [{"date": r["date"], "lot": {"raw": int(r["volume"] * 0.05)}, "value": {"raw": int(r["value"] * 0.05)}, "frequency": {"raw": 15}} for r in rows],
            "big_money_sell": [{"date": r["date"], "lot": {"raw": int(r["volume"] * 0.09)}, "value": {"raw": int(r["value"] * 0.09)}, "frequency": {"raw": 25}} for r in rows],
            "big_money_net_values": [{"date": r["date"], "value": {"raw": -int(r["value"] * 0.04)}} for r in rows],
            "big_money_rt": {
                "buy": [{"date": r["date"], "lot": {"raw": 80000}, "value": {"raw": 900000000}, "frequency": {"raw": 30}} for r in rows],
                "sell": [{"date": r["date"], "lot": {"raw": 50000}, "value": {"raw": 600000000}, "frequency": {"raw": 20}} for r in rows],
                "net_values": [{"date": r["date"], "value": {"raw": 300000000}} for r in rows],
            },
        }
    }

    md = {
        "data": {
            "from": "2026-07-27",
            "to": "2026-10-27",
            "bandar_detector": {
                "broker_accdist": "Dist",
                "average": 115.65,
                "total_buyer": 51,
                "total_seller": 26,
                "top1": {"percent": 0.02},
                "top3": {"percent": -17.96},
                "top5": {"percent": -24.96},
                "avg5": {"percent": -15.11},
            },
            "broker_summary": {
                "brokers_buy": [
                    {
                        "netbs_broker_code": "XL", "type": "Lokal",
                        "blot": "660669", "blotv": "1248672000",
                        "bval": "77066756800", "bvalv": "1550000000000",
                        "freq": "89673", "netbs_buy_avg_price": "116.65",
                    },
                    {
                        "netbs_broker_code": "CC", "type": "Pemerintah",
                        "blot": "148086", "blotv": "428132700",
                        "bval": "16267070000", "bvalv": "520000000000",
                        "freq": "23850", "netbs_buy_avg_price": "118.42",
                    },
                    {
                        "netbs_broker_code": "YP", "type": "Asing",
                        "blot": "29315", "blotv": "355800200",
                        "bval": "2750000000", "bvalv": "430000000000",
                        "freq": "40100", "netbs_buy_avg_price": "119.50",
                    },
                ],
                "brokers_sell": [
                    {
                        "netbs_broker_code": "DP", "type": "Asing",
                        "slot": "-659865", "slotv": "65986500",
                        "sval": "-66027981200", "svalv": "66027981200",
                        "freq": "255", "netbs_sell_avg_price": "100.06",
                    },
                ],
            },
        }
    }

    rtc = {
        "data": {
            "broker_chart_data": [
                {
                    "type": "TYPE_CHART_VOLUME",
                    "charts": [
                        {
                            "broker_code": "DP",
                            "chart": [{"date": r["date"], "value": {"raw": "-659865" if i >= 4 else "0"}} for i, r in enumerate(rows)],
                        },
                        {
                            "broker_code": "MG",
                            "chart": [{"date": r["date"], "value": {"raw": str(-50000 - i * 25000)}} for i, r in enumerate(rows)],
                        },
                    ],
                }
            ]
        }
    }

    bd = {
        "data": {
            "by_volume": {
                "top_broker_buy": [
                    {
                        "detail": {"code": "XL", "amount": 12486720},
                        "distribute_to": [
                            {"code": "XL", "amount": 3615088},
                            {"code": "CC", "amount": 1532286},
                        ],
                    }
                ],
                "top_broker_sell": [
                    {
                        "detail": {"code": "DP", "amount": 659865},
                        "distribute_to": [
                            {"code": "XL", "amount": 147435},
                            {"code": "CP", "amount": 120000},
                            {"code": "YP", "amount": 110000},
                            {"code": "CC", "amount": 95000},
                        ],
                    }
                ],
            }
        }
    }
    return rows, tb, md, rtc, bd


def test_swing_screener_untr_strong_buy_archetype():
    rows, tb, md, rtc, bd = _make_untr_fixtures()
    res = analyze_swing_stock(
        historical_source=rows,
        trade_book_source=tb,
        market_detector_source=md,
        running_trade_chart_source=rtc,
        broker_distribution_source=bd,
        ticker="UNTR",
    )
    assert res["ticker"] == "UNTR"
    assert res["active_layers"] == 5
    assert res["swing_score"] >= 70.0
    assert res["action"]["key"] == "STRONG_BUY"
    assert res["trade_plan"]["rr_net"] >= 2.0
    # Verify price-agnostic High-Conviction Institutional classification on Rp 26,500 stock
    hc_codes = [b["code"] for b in res["bandar_structure"]["high_conviction_buyers"]]
    assert "AK" in hc_codes
    assert "RX" in hc_codes
    assert res["broker_trajectory"]["signals"]["sustained_inst_accumulation"] is True


def test_swing_screener_strk_avoid_trap_archetype():
    rows, tb, md, rtc, bd = _make_strk_fixtures()
    res = analyze_swing_stock(
        historical_source=rows,
        trade_book_source=tb,
        market_detector_source=md,
        running_trade_chart_source=rtc,
        broker_distribution_source=bd,
        ticker="STRK",
    )
    assert res["ticker"] == "STRK"
    assert res["flags"]["is_arb_today"] is True
    assert res["flags"]["recent_suspension_10d"] is True
    assert res["flags"]["blow_off_rejection_10d"] is True
    assert res["order_flow"]["execution_regime"] == "PAINT_THE_TAPE_BULL_TRAP"
    assert res["action"]["key"] == "AVOID"


def _make_dooh_fixtures():
    """Realistic Post-Capitulation Double-Bottom & Seller Exhaustion fixtures calibrated to DOOH."""
    rows = [
        {"date": "2026-10-12", "open": 270, "high": 274, "low": 260, "close": 264, "average": 266, "volume": 2200000, "value": 58520000000, "frequency": 9200, "change": -6, "change_percentage": -2.22},
        {"date": "2026-10-13", "open": 264, "high": 266, "low": 250, "close": 252, "average": 256, "volume": 2800000, "value": 71680000000, "frequency": 11500, "change": -12, "change_percentage": -4.55},
        {"date": "2026-10-14", "open": 252, "high": 254, "low": 240, "close": 244, "average": 246, "volume": 3100000, "value": 76260000000, "frequency": 12400, "change": -8, "change_percentage": -3.17},
        {"date": "2026-10-15", "open": 244, "high": 246, "low": 236, "close": 238, "average": 240, "volume": 2900000, "value": 69600000000, "frequency": 11800, "change": -6, "change_percentage": -2.46},
        {"date": "2026-10-16", "open": 238, "high": 240, "low": 224, "close": 228, "average": 231, "volume": 4100000, "value": 94710000000, "frequency": 16200, "change": -10, "change_percentage": -4.20},
        {"date": "2026-10-19", "open": 226, "high": 232, "low": 212, "close": 228, "average": 222, "volume": 3180157, "value": 70599485400, "frequency": 15900, "change": 0, "change_percentage": 0.00},
        {"date": "2026-10-20", "open": 228, "high": 244, "low": 226, "close": 236, "average": 235, "volume": 2950000, "value": 69325000000, "frequency": 13400, "change": 8, "change_percentage": 3.51},
        {"date": "2026-10-21", "open": 236, "high": 246, "low": 234, "close": 240, "average": 239, "volume": 2400000, "value": 57360000000, "frequency": 10900, "change": 4, "change_percentage": 1.69},
        {"date": "2026-10-22", "open": 240, "high": 242, "low": 232, "close": 234, "average": 236, "volume": 1650000, "value": 38940000000, "frequency": 7800, "change": -6, "change_percentage": -2.50},
        {"date": "2026-10-23", "open": 234, "high": 238, "low": 230, "close": 234, "average": 234, "volume": 1420000, "value": 33228000000, "frequency": 6900, "change": 0, "change_percentage": 0.00},
        {"date": "2026-10-26", "open": 234, "high": 238, "low": 230, "close": 234, "average": 234, "volume": 1150000, "value": 26910000000, "frequency": 5600, "change": 0, "change_percentage": 0.00},
        {"date": "2026-10-27", "open": 236, "high": 236, "low": 224, "close": 224, "average": 228, "volume": 806310, "value": 18412264600, "frequency": 5624, "change": -10, "change_percentage": -4.27},
    ]

    tb = {
        "data": {
            "buy": [{"date": r["date"], "lot": {"raw": int(r["volume"] * 0.45)}, "value": {"raw": int(r["value"] * 0.45)}, "frequency": {"raw": int(r["frequency"] * 0.48)}} for r in rows],
            "sell": [{"date": r["date"], "lot": {"raw": int(r["volume"] * 0.55)}, "value": {"raw": int(r["value"] * 0.55)}, "frequency": {"raw": int(r["frequency"] * 0.52)}} for r in rows],
            "big_money_buy": [{"date": r["date"], "lot": {"raw": int(r["volume"] * 0.14)}, "value": {"raw": int(r["value"] * 0.14)}, "frequency": {"raw": 45}} for r in rows],
            "big_money_sell": [{"date": r["date"], "lot": {"raw": int(r["volume"] * 0.18)}, "value": {"raw": int(r["value"] * 0.18)}, "frequency": {"raw": 60}} for r in rows],
            "big_money_net_values": [{"date": r["date"], "value": {"raw": -int(r["value"] * 0.04)}} for r in rows],
            "big_money_rt": {
                "buy": [{"date": r["date"], "lot": {"raw": 20000}, "value": {"raw": 450000000}, "frequency": {"raw": 15}} for r in rows],
                "sell": [{"date": r["date"], "lot": {"raw": 22000}, "value": {"raw": 500000000}, "frequency": {"raw": 16}} for r in rows],
                "net_values": [{"date": r["date"], "value": {"raw": -50000000}} for r in rows],
            },
        }
    }

    md = {
        "data": {
            "from": "2026-07-27",
            "to": "2026-10-27",
            "bandar_detector": {
                "broker_accdist": "Dist",
                "average": 267.97,
                "total_buyer": 42,
                "total_seller": 34,
                "top1": {"percent": -1.73},
                "top3": {"percent": -11.45},
                "top5": {"percent": -14.22},
                "avg5": {"percent": -9.31},
            },
            "broker_summary": {
                "brokers_buy": [
                    {
                        "netbs_broker_code": "XL", "type": "Lokal",
                        "blot": "914377", "blotv": "1046738700",
                        "bval": "24869214000", "bvalv": "282000000000",
                        "freq": "108152", "netbs_buy_avg_price": "271.98",
                    },
                    {
                        "netbs_broker_code": "FZ", "type": "Lokal",
                        "blot": "724854", "blotv": "91130200",
                        "bval": "19022443200", "bvalv": "23868000000",
                        "freq": "3899", "netbs_buy_avg_price": "262.43",
                    },
                    {
                        "netbs_broker_code": "KI", "type": "Lokal",
                        "blot": "443299", "blotv": "48947400",
                        "bval": "10913148200", "bvalv": "12041000000",
                        "freq": "1532", "netbs_buy_avg_price": "246.18",
                    },
                ],
                "brokers_sell": [
                    {
                        "netbs_broker_code": "CC", "type": "Pemerintah",
                        "slot": "-1103335", "slotv": "350000000",
                        "sval": "-29500000000", "svalv": "93000000000",
                        "freq": "18200", "netbs_sell_avg_price": "267.37",
                    },
                ],
            },
        }
    }

    rtc = {
        "data": {
            "broker_chart_data": [
                {
                    "type": "TYPE_CHART_VOLUME",
                    "charts": [
                        {
                            "broker_code": "CC",
                            "chart": [{"date": r["date"], "value": {"raw": "-1103335"}} for r in rows],
                        },
                        {
                            "broker_code": "GR",
                            "chart": [{"date": r["date"], "value": {"raw": str(-613213 + i * 22000)}} for i, r in enumerate(rows)],
                        },
                        {
                            "broker_code": "XL",
                            "chart": [{"date": r["date"], "value": {"raw": str(1277626 - i * 33000)}} for i, r in enumerate(rows)],
                        },
                        {
                            "broker_code": "FZ",
                            "chart": [{"date": r["date"], "value": {"raw": str(680000 + i * 4000)}} for i, r in enumerate(rows)],
                        },
                    ],
                }
            ]
        }
    }

    bd = {
        "data": {
            "by_volume": {
                "top_broker_buy": [
                    {
                        "detail": {"code": "XL", "amount": 10467387},
                        "distribute_to": [
                            {"code": "XL", "amount": 2651519},
                            {"code": "CC", "amount": 1157941},
                        ],
                    }
                ],
                "top_broker_sell": [
                    {
                        "detail": {"code": "CC", "amount": 3500000},
                        "distribute_to": [
                            {"code": "XL", "amount": 1157941},
                            {"code": "FZ", "amount": 260679},
                        ],
                    }
                ],
            }
        }
    }
    return rows, tb, md, rtc, bd


def test_swing_screener_dooh_wait_for_trigger_archetype():
    rows, tb, md, rtc, bd = _make_dooh_fixtures()
    res = analyze_swing_stock(
        historical_source=rows,
        trade_book_source=tb,
        market_detector_source=md,
        running_trade_chart_source=rtc,
        broker_distribution_source=bd,
        ticker="DOOH",
    )
    assert res["ticker"] == "DOOH"
    assert res["action"]["key"] == "WAIT_FOR_TRIGGER"
    assert res["broker_trajectory"]["signals"]["seller_exhaustion"] is True
    assert res["broker_trajectory"]["signals"]["distributor_buyback"] is True
    assert res["broker_trajectory"]["signals"]["retail_capitulation"] is True
    assert res["broker_trajectory"]["signals"]["fresh_dip_accumulation"] is True


def _make_elsa_fixtures():
    """Realistic Cup-with-Handle Shakeout Absorption & Cost-Basis Reclaim Breakout calibrated to ELSA."""
    rows = [
        {"date": "2026-09-30", "open": 625, "high": 650, "low": 625, "close": 645, "average": 641, "volume": 136301, "value": 8738282500, "frequency": 2368, "change": 20, "change_percentage": 3.20},
        {"date": "2026-10-01", "open": 650, "high": 650, "low": 615, "close": 620, "average": 627, "volume": 284794, "value": 17859668500, "frequency": 4700, "change": -25, "change_percentage": -3.88},
        {"date": "2026-10-02", "open": 625, "high": 635, "low": 615, "close": 630, "average": 626, "volume": 133529, "value": 8358524000, "frequency": 2594, "change": 10, "change_percentage": 1.61},
        {"date": "2026-10-05", "open": 635, "high": 635, "low": 625, "close": 630, "average": 629, "volume": 88385, "value": 5563587000, "frequency": 2124, "change": 0, "change_percentage": 0.00},
        {"date": "2026-10-06", "open": 635, "high": 650, "low": 630, "close": 645, "average": 644, "volume": 195395, "value": 12582375000, "frequency": 3695, "change": 15, "change_percentage": 2.38},
        {"date": "2026-10-07", "open": 650, "high": 655, "low": 635, "close": 640, "average": 644, "volume": 132651, "value": 8543087500, "frequency": 2610, "change": -5, "change_percentage": -0.78},
        {"date": "2026-10-08", "open": 645, "high": 645, "low": 635, "close": 635, "average": 638, "volume": 95809, "value": 6113946000, "frequency": 1930, "change": -5, "change_percentage": -0.78},
        {"date": "2026-10-09", "open": 635, "high": 640, "low": 630, "close": 630, "average": 634, "volume": 109457, "value": 6935613000, "frequency": 2033, "change": -5, "change_percentage": -0.79},
        {"date": "2026-10-12", "open": 630, "high": 630, "low": 620, "close": 625, "average": 624, "volume": 92561, "value": 5773188000, "frequency": 1998, "change": -5, "change_percentage": -0.79},
        {"date": "2026-10-13", "open": 625, "high": 665, "low": 625, "close": 655, "average": 651, "volume": 388205, "value": 25279680500, "frequency": 5662, "change": 30, "change_percentage": 4.80},
        {"date": "2026-10-14", "open": 660, "high": 685, "low": 650, "close": 680, "average": 669, "volume": 223520, "value": 14957363500, "frequency": 3662, "change": 25, "change_percentage": 3.82},
        {"date": "2026-10-15", "open": 680, "high": 685, "low": 660, "close": 670, "average": 672, "volume": 225851, "value": 15175162500, "frequency": 4208, "change": -10, "change_percentage": -1.47},
        {"date": "2026-10-16", "open": 665, "high": 665, "low": 570, "close": 575, "average": 585, "volume": 700280, "value": 40964527500, "frequency": 13537, "change": -95, "change_percentage": -14.18},
        {"date": "2026-10-19", "open": 575, "high": 580, "low": 540, "close": 570, "average": 562, "volume": 309643, "value": 17393179500, "frequency": 6710, "change": -5, "change_percentage": -0.87},
        {"date": "2026-10-20", "open": 575, "high": 635, "low": 575, "close": 630, "average": 612, "volume": 440785, "value": 26977199500, "frequency": 7634, "change": 60, "change_percentage": 10.53},
        {"date": "2026-10-21", "open": 635, "high": 645, "low": 615, "close": 630, "average": 629, "volume": 216954, "value": 13646394500, "frequency": 3899, "change": 0, "change_percentage": 0.00},
        {"date": "2026-10-22", "open": 630, "high": 665, "low": 625, "close": 660, "average": 649, "volume": 289328, "value": 18771386500, "frequency": 4695, "change": 30, "change_percentage": 4.76},
        {"date": "2026-10-23", "open": 660, "high": 675, "low": 650, "close": 665, "average": 663, "volume": 185145, "value": 12277001500, "frequency": 3120, "change": 5, "change_percentage": 0.76},
        {"date": "2026-10-26", "open": 665, "high": 670, "low": 640, "close": 640, "average": 649, "volume": 143345, "value": 9299974000, "frequency": 2650, "change": -25, "change_percentage": -3.76},
        {"date": "2026-10-27", "open": 650, "high": 685, "low": 640, "close": 685, "average": 670, "volume": 628686, "value": 42129158500, "frequency": 9310, "change": 45, "change_percentage": 7.03},
    ]

    # Contrarian Big Money absorption on red days (16 Oct, 19 Oct, 26 Oct) + breakout sweep on 27 Oct
    bm_net_map = {
        "2026-10-16": 3784048000,
        "2026-10-19": 751814500,
        "2026-10-22": 1261169500,
        "2026-10-26": 352104000,
        "2026-10-27": -77790000,
    }
    ov_net_map = {
        "2026-10-16": -2540000000,
        "2026-10-19": -830000000,
        "2026-10-20": 8220000000,
        "2026-10-26": -1910000000,
        "2026-10-27": 3074363500,
    }
    rt_net_map = {
        "2026-10-19": 1950000000,
        "2026-10-22": 597610000,
        "2026-10-23": 380840000,
        "2026-10-26": -670560000,
        "2026-10-27": 1919804500,
    }

    tb = {
        "data": {
            "buy": [{"date": r["date"], "lot": {"raw": int(r["volume"] * 0.52)}, "value": {"raw": int(r["value"] * 0.52)}, "frequency": {"raw": int(r["frequency"] * 0.46)}} for r in rows],
            "sell": [{"date": r["date"], "lot": {"raw": int(r["volume"] * 0.48)}, "value": {"raw": int(r["value"] * 0.48)}, "frequency": {"raw": int(r["frequency"] * 0.54)}} for r in rows],
            "net_values": [{"date": r["date"], "value": {"raw": ov_net_map.get(r["date"], 250000000)}} for r in rows],
            "big_money_buy": [{"date": r["date"], "lot": {"raw": int(r["volume"] * 0.16)}, "value": {"raw": int(r["value"] * 0.16)}, "frequency": {"raw": 65}} for r in rows],
            "big_money_sell": [{"date": r["date"], "lot": {"raw": int(r["volume"] * 0.10)}, "value": {"raw": int(r["value"] * 0.10)}, "frequency": {"raw": 55}} for r in rows],
            "big_money_net_values": [{"date": r["date"], "value": {"raw": bm_net_map.get(r["date"], 450000000)}} for r in rows],
            "big_money_rt": {
                "buy": [{"date": r["date"], "lot": {"raw": 25000}, "value": {"raw": 1600000000}, "frequency": {"raw": 30}} for r in rows],
                "sell": [{"date": r["date"], "lot": {"raw": 18000}, "value": {"raw": 1150000000}, "frequency": {"raw": 25}} for r in rows],
                "net_values": [{"date": r["date"], "value": {"raw": rt_net_map.get(r["date"], 120000000)}} for r in rows],
            },
        }
    }

    md = {
        "data": {
            "from": "2026-07-27",
            "to": "2026-10-27",
            "bandar_detector": {
                "broker_accdist": "Acc",
                "average": 678.33,
                "total_buyer": 38,
                "total_seller": 43,
                "top1": {"percent": -1.16},
                "top3": {"percent": 2.28},
                "top5": {"percent": 8.94},
                "avg5": {"percent": 2.23},
            },
            "broker_summary": {
                "brokers_buy": [
                    {"netbs_broker_code": "DX", "type": "Pemerintah", "blot": "252607", "blotv": "30352000", "bval": "16910000000", "bvalv": "20290000000", "freq": "2670", "netbs_buy_avg_price": "668.22"},
                    {"netbs_broker_code": "CC", "type": "Pemerintah", "blot": "246269", "blotv": "219972400", "bval": "14480000000", "bvalv": "148000000000", "freq": "23850", "netbs_buy_avg_price": "674.81"},
                    {"netbs_broker_code": "KZ", "type": "Asing", "blot": "234208", "blotv": "27677000", "bval": "15680000000", "bvalv": "18760000000", "freq": "2617", "netbs_buy_avg_price": "678.03"},
                    {"netbs_broker_code": "SQ", "type": "Lokal", "blot": "215096", "blotv": "61749000", "bval": "12910000000", "bvalv": "40460000000", "freq": "4773", "netbs_buy_avg_price": "655.23"},
                    {"netbs_broker_code": "DP", "type": "Asing", "blot": "183112", "blotv": "18311200", "bval": "12930000000", "bvalv": "12930000000", "freq": "1980", "netbs_buy_avg_price": "706.21"},
                ],
                "brokers_sell": [
                    {"netbs_broker_code": "ZP", "type": "Asing", "slot": "-271519", "slotv": "99555700", "sval": "-18500000000", "svalv": "67500000000", "freq": "11200", "netbs_sell_avg_price": "681.35"},
                    {"netbs_broker_code": "OD", "type": "Pemerintah", "slot": "-251836", "slotv": "105599400", "sval": "-17100000000", "svalv": "71500000000", "freq": "9800", "netbs_sell_avg_price": "679.00"},
                ],
            },
        }
    }

    rtc = {
        "data": {
            "broker_chart_data": [
                {
                    "type": "TYPE_CHART_VOLUME",
                    "charts": [
                        {"broker_code": "DX", "chart": [{"date": r["date"], "value": {"raw": str(210000 + i * 2250)}} for i, r in enumerate(rows)]},
                        {"broker_code": "KZ", "chart": [{"date": r["date"], "value": {"raw": str(68000 if i < 10 else 218000 + (i - 10) * 1800)}} for i, r in enumerate(rows)]},
                        {"broker_code": "OD", "chart": [{"date": r["date"], "value": {"raw": str(-276334 if i == 1 else -251836)}} for i, r in enumerate(rows)]},
                        {"broker_code": "ZP", "chart": [{"date": r["date"], "value": {"raw": str(-295619 if i == 18 else -271519)}} for i, r in enumerate(rows)]},
                    ],
                }
            ]
        }
    }

    bd = {
        "data": {
            "by_volume": {
                "top_broker_buy": [
                    {"detail": {"code": "CC", "amount": 2199724}, "distribute_to": [{"code": "CC", "amount": 296059}, {"code": "XL", "amount": 301754}]},
                    {"detail": {"code": "XL", "amount": 1888713}, "distribute_to": [{"code": "XL", "amount": 255413}, {"code": "AK", "amount": 285930}]},
                    *[
                        {"detail": {"code": f"B{idx}", "amount": 500000 - idx * 10000}, "distribute_to": [{"code": "XL", "amount": 50000}]}
                        for idx in range(9)
                    ],
                    {"detail": {"code": "DX", "amount": 303520}, "distribute_to": [{"code": "DX", "amount": 237}, {"code": "XL", "amount": 52694}, {"code": "CC", "amount": 40116}]},
                ],
                "top_broker_sell": [
                    {"detail": {"code": "XL", "amount": 2019101}, "distribute_to": [{"code": "CC", "amount": 301754}, {"code": "DX", "amount": 52694}, {"code": "KZ", "amount": 42932}]},
                ],
            }
        }
    }
    return rows, tb, md, rtc, bd


def test_swing_screener_elsa_cup_handle_cost_reclaim_breakout():
    rows, tb, md, rtc, bd = _make_elsa_fixtures()
    res = analyze_swing_stock(
        historical_source=rows,
        trade_book_source=tb,
        market_detector_source=md,
        running_trade_chart_source=rtc,
        broker_distribution_source=bd,
        ticker="ELSA",
    )
    assert res["ticker"] == "ELSA"
    assert res["swing_score"] >= 80.0
    assert res["action"]["key"] == "STRONG_BUY"
    assert res["trade_plan"]["rr_net"] >= 2.0
    assert res["order_flow"]["anchored_from_swing_low"]["red_day_bm_absorption_10d"] > 0
    assert res["order_flow"]["anchored_from_swing_low"]["red_day_absorption_days_10d"] >= 3
    assert res["broker_network"]["top1_self_match_vs_net_multiple"] <= 0.05
    assert res["broker_trajectory"]["signals"]["distributor_buyback"] is True


def _make_vktr_fixtures():
    """Realistic Stage-4 Markdown Crash & Trapped Institutional Bull-Trap fixtures calibrated to VKTR."""
    rows = [
        {"date": "2026-09-22", "open": 720, "high": 750, "low": 710, "close": 745, "average": 732, "volume": 1200000, "value": 87840000000, "frequency": 9000, "change": 25, "change_percentage": 3.47},
        {"date": "2026-09-23", "open": 745, "high": 760, "low": 735, "close": 740, "average": 748, "volume": 1150000, "value": 86020000000, "frequency": 8800, "change": -5, "change_percentage": -0.67},
        {"date": "2026-09-24", "open": 740, "high": 750, "low": 725, "close": 730, "average": 736, "volume": 1100000, "value": 80960000000, "frequency": 8500, "change": -10, "change_percentage": -1.35},
        {"date": "2026-09-25", "open": 730, "high": 740, "low": 720, "close": 725, "average": 728, "volume": 1050000, "value": 76440000000, "frequency": 8200, "change": -5, "change_percentage": -0.68},
        {"date": "2026-09-28", "open": 725, "high": 735, "low": 715, "close": 720, "average": 724, "volume": 1000000, "value": 72400000000, "frequency": 8000, "change": -5, "change_percentage": -0.69},
        {"date": "2026-09-29", "open": 720, "high": 730, "low": 710, "close": 715, "average": 718, "volume": 980000, "value": 70364000000, "frequency": 7800, "change": -5, "change_percentage": -0.69},
        {"date": "2026-09-30", "open": 715, "high": 725, "low": 705, "close": 710, "average": 714, "volume": 950000, "value": 67830000000, "frequency": 7500, "change": -5, "change_percentage": -0.70},
        {"date": "2026-10-01", "open": 710, "high": 720, "low": 700, "close": 705, "average": 708, "volume": 920000, "value": 65136000000, "frequency": 7200, "change": -5, "change_percentage": -0.70},
        {"date": "2026-10-02", "open": 705, "high": 715, "low": 695, "close": 700, "average": 704, "volume": 900000, "value": 63360000000, "frequency": 7000, "change": -5, "change_percentage": -0.71},
        {"date": "2026-10-05", "open": 700, "high": 705, "low": 680, "close": 685, "average": 692, "volume": 1100000, "value": 76120000000, "frequency": 8500, "change": -15, "change_percentage": -2.14},
        {"date": "2026-10-06", "open": 680, "high": 695, "low": 670, "close": 675, "average": 682, "volume": 1450000, "value": 98890000000, "frequency": 11000, "change": -5, "change_percentage": -0.74},
        {"date": "2026-10-07", "open": 675, "high": 690, "low": 665, "close": 670, "average": 678, "volume": 1320000, "value": 89496000000, "frequency": 10500, "change": -5, "change_percentage": -0.74},
        {"date": "2026-10-08", "open": 670, "high": 675, "low": 640, "close": 645, "average": 655, "volume": 1600000, "value": 104800000000, "frequency": 12000, "change": -25, "change_percentage": -3.73},
        {"date": "2026-10-09", "open": 645, "high": 655, "low": 630, "close": 635, "average": 640, "volume": 1550000, "value": 99200000000, "frequency": 11800, "change": -10, "change_percentage": -1.55},
        {"date": "2026-10-12", "open": 635, "high": 645, "low": 625, "close": 635, "average": 632, "volume": 1770117, "value": 111871394400, "frequency": 13400, "change": 0, "change_percentage": 0.00},
        {"date": "2026-10-13", "open": 630, "high": 630, "low": 570, "close": 570, "average": 595, "volume": 2220172, "value": 132099951600, "frequency": 16500, "change": -65, "change_percentage": -10.24},
        {"date": "2026-10-14", "open": 560, "high": 570, "low": 500, "close": 500, "average": 525, "volume": 1835291, "value": 96352777500, "frequency": 14200, "change": -70, "change_percentage": -12.28},
        {"date": "2026-10-15", "open": 490, "high": 500, "low": 440, "close": 440, "average": 460, "volume": 2361890, "value": 108646940000, "frequency": 17800, "change": -60, "change_percentage": -12.00},
        {"date": "2026-10-16", "open": 374, "high": 374, "low": 374, "close": 374, "average": 374, "volume": 221590, "value": 8287466000, "frequency": 2100, "change": -66, "change_percentage": -15.00},
        {"date": "2026-10-19", "open": 348, "high": 348, "low": 348, "close": 348, "average": 348, "volume": 29406, "value": 1023328800, "frequency": 450, "change": -26, "change_percentage": -6.95},
        {"date": "2026-10-20", "open": 330, "high": 354, "low": 324, "close": 336, "average": 332, "volume": 3189355, "value": 105886586000, "frequency": 24500, "change": -12, "change_percentage": -3.45},
        {"date": "2026-10-21", "open": 340, "high": 368, "low": 316, "close": 360, "average": 342, "volume": 2729201, "value": 93338674200, "frequency": 21200, "change": 24, "change_percentage": 7.14},
        {"date": "2026-10-22", "open": 356, "high": 366, "low": 336, "close": 342, "average": 348, "volume": 3376186, "value": 117491272800, "frequency": 26800, "change": -18, "change_percentage": -5.00},
        {"date": "2026-10-23", "open": 348, "high": 418, "low": 346, "close": 400, "average": 378, "volume": 8134632, "value": 307489089600, "frequency": 61200, "change": 58, "change_percentage": 16.96},
        {"date": "2026-10-26", "open": 390, "high": 422, "low": 372, "close": 372, "average": 397, "volume": 5637485, "value": 223808154500, "frequency": 44500, "change": -28, "change_percentage": -7.00},
        {"date": "2026-10-27", "open": 364, "high": 386, "low": 346, "close": 346, "average": 364, "volume": 2187323, "value": 79648569600, "frequency": 15532, "change": -26, "change_percentage": -6.99},
    ]

    tb = {
        "data": {
            "buy": [{"date": r["date"], "lot": {"raw": int(r["volume"] * 0.46)}, "value": {"raw": int(r["value"] * 0.46)}, "frequency": {"raw": int(r["frequency"] * 0.48)}} for r in rows],
            "sell": [{"date": r["date"], "lot": {"raw": int(r["volume"] * 0.54)}, "value": {"raw": int(r["value"] * 0.54)}, "frequency": {"raw": int(r["frequency"] * 0.52)}} for r in rows],
            "net_values": [
                {"date": "2026-10-21", "value": {"raw": 2400000000}},
                {"date": "2026-10-22", "value": {"raw": -10800000000}},
                {"date": "2026-10-23", "value": {"raw": 18660000000}},
                {"date": "2026-10-26", "value": {"raw": -31580000000}},
                {"date": "2026-10-27", "value": {"raw": -11687706400}},
            ],
            "big_money_buy": [{"date": r["date"], "lot": {"raw": 80000}, "value": {"raw": 3000000000}, "frequency": {"raw": 80}} for r in rows],
            "big_money_sell": [{"date": r["date"], "lot": {"raw": 150000}, "value": {"raw": 6500000000}, "frequency": {"raw": 110}} for r in rows],
            # Reconstructed parent orders dumped heavily on rally days (23 & 26 Okt)
            "big_money_net_values": [
                {"date": "2026-10-21", "value": {"raw": -195000000}},
                {"date": "2026-10-22", "value": {"raw": -4170000000}},
                {"date": "2026-10-23", "value": {"raw": -5735247200}},
                {"date": "2026-10-26", "value": {"raw": -9233249800}},
                {"date": "2026-10-27", "value": {"raw": 1076674600}},
            ],
            # Running trade single prints painted positive tape to lure retail
            "big_money_rt": {
                "buy": [{"date": r["date"], "lot": {"raw": 90000}, "value": {"raw": 5500000000}, "frequency": {"raw": 120}} for r in rows],
                "sell": [{"date": r["date"], "lot": {"raw": 60000}, "value": {"raw": 3500000000}, "frequency": {"raw": 80}} for r in rows],
                "net_values": [
                    {"date": "2026-10-21", "value": {"raw": 5340000000}},
                    {"date": "2026-10-22", "value": {"raw": -3970000000}},
                    {"date": "2026-10-23", "value": {"raw": 11920000000}},
                    {"date": "2026-10-26", "value": {"raw": -7950000000}},
                    {"date": "2026-10-27", "value": {"raw": 63324000}},
                ],
            },
        }
    }

    md = {
        "data": {
            "from": "2026-07-27",
            "to": "2026-10-27",
            "bandar_detector": {
                "broker_accdist": "Dist",
                "average": 569.62,
                "total_buyer": 48,
                "total_seller": 34,
                "top1": {"percent": 7.41},
                "top3": {"percent": -1.83},
                "top5": {"percent": 0.85},
                "avg5": {"percent": 4.86},
            },
            "broker_summary": {
                "brokers_buy": [
                    # RX accumulated at Rp 718.80 before crash, now down -51.9% and inactive
                    {"netbs_broker_code": "RX", "type": "Asing", "blot": "1350185", "blotv": "135018500", "bval": "97051259500", "bvalv": "97051259500", "freq": "10240", "netbs_buy_avg_price": "718.80"},
                    {"netbs_broker_code": "XL", "type": "Lokal", "blot": "1129711", "blotv": "2079543500", "bval": "42300000000", "bvalv": "780000000000", "freq": "95000", "netbs_buy_avg_price": "435.12"},
                    {"netbs_broker_code": "BB", "type": "Lokal", "blot": "574936", "blotv": "65993600", "bval": "21424083600", "bvalv": "27474083600", "freq": "2932", "netbs_buy_avg_price": "416.31"},
                    {"netbs_broker_code": "YP", "type": "Asing", "blot": "392107", "blotv": "475009400", "bval": "18000000000", "bvalv": "218000000000", "freq": "34500", "netbs_buy_avg_price": "458.20"},
                ],
                "brokers_sell": [
                    {"netbs_broker_code": "IN", "type": "Lokal", "slot": "-1144070", "slotv": "167775900", "sval": "-49071001200", "svalv": "76177332000", "freq": "7765", "netbs_sell_avg_price": "454.04"},
                    {"netbs_broker_code": "AO", "type": "Lokal", "slot": "-813465", "slotv": "114356700", "sval": "-37430443500", "svalv": "61216860800", "freq": "6705", "netbs_sell_avg_price": "535.32"},
                    {"netbs_broker_code": "HP", "type": "Lokal", "slot": "-764870", "slotv": "88004500", "sval": "-26451089900", "svalv": "33649473400", "freq": "3591", "netbs_sell_avg_price": "382.36"},
                ],
            },
        }
    }

    rtc = {
        "data": {
            "broker_chart_data": [
                {
                    "type": "TYPE_CHART_VOLUME",
                    "charts": [
                        # RX accumulated in Sep/Oct and frozen at 1.35M lot (0 delta last 11 days)
                        {"broker_code": "RX", "chart": [{"date": r["date"], "value": {"raw": "1350185"}} for r in rows]},
                        # IN actively dumped from -35k to -1.14M lot
                        {"broker_code": "IN", "chart": [{"date": r["date"], "value": {"raw": str(-35000 - i * 74000)}} for i, r in enumerate(rows)]},
                        # XL (retail) actively caught knife from 200k to 1.13M lot
                        {"broker_code": "XL", "chart": [{"date": r["date"], "value": {"raw": str(200000 + i * 62000)}} for i, r in enumerate(rows)]},
                    ],
                }
            ]
        }
    }

    bd = {
        "data": {
            "by_volume": {
                "top_broker_buy": [
                    {"detail": {"code": "XL", "amount": 20795435}, "distribute_to": [{"code": "XL", "amount": 5126214}, {"code": "AK", "amount": 2192703}, {"code": "MG", "amount": 1617003}]},
                    {"detail": {"code": "AK", "amount": 6630560}, "distribute_to": [{"code": "XL", "amount": 1978821}, {"code": "AK", "amount": 800000}]},
                    {"detail": {"code": "MG", "amount": 5926564}, "distribute_to": [{"code": "XL", "amount": 1617003}, {"code": "MG", "amount": 400000}]},
                    {"detail": {"code": "RX", "amount": 1350185}, "distribute_to": [{"code": "RX", "amount": 0}, {"code": "XL", "amount": 250000}]},
                ],
                "top_broker_sell": [
                    {"detail": {"code": "IN", "amount": 1677759}, "distribute_to": [{"code": "XL", "amount": 1200000}, {"code": "YP", "amount": 200000}]},
                    {"detail": {"code": "XL", "amount": 19665724}, "distribute_to": [{"code": "AK", "amount": 1978821}, {"code": "MG", "amount": 1617003}]},
                ],
            }
        }
    }
    return rows, tb, md, rtc, bd


def test_swing_screener_vktr_stage4_markdown_dead_cat_bull_trap():
    rows, tb, md, rtc, bd = _make_vktr_fixtures()
    res = analyze_swing_stock(
        historical_source=rows,
        trade_book_source=tb,
        market_detector_source=md,
        running_trade_chart_source=rtc,
        broker_distribution_source=bd,
        ticker="VKTR",
    )
    assert res["ticker"] == "VKTR"
    assert res["swing_score"] <= 35.0
    assert res["action"]["key"] == "AVOID_DISTRIBUTION"
    assert res["trade_plan"]["status"] == "DANGER_ACTIVE"
    assert res["trade_plan"]["rr_net"] == 0.0
    assert res["bandar_structure"]["cost_basis_map"]["top1_buyer_legacy_trapped"] is True
    assert res["broker_network"]["network_topology"] in ("CIRCULAR_WASH_ROTATION", "FEW_TO_MANY_DISPERSION")
    assert res["broker_trajectory"]["signals"]["active_multi_day_distribution"] is True
    assert res["order_flow"]["paint_the_tape_trap"] is True


def _make_pwon_fixtures():
    """Realistic V-Shaped Capitulation Reversal into Sustained Institutional Markup Breakout fixtures calibrated to PWON."""
    rows = [
        {"date": "2026-09-28", "open": 268, "high": 268, "low": 258, "close": 258, "average": 262, "volume": 366928, "value": 9595831600, "frequency": 3733, "change": -8, "change_percentage": -3.01},
        {"date": "2026-09-29", "open": 258, "high": 264, "low": 254, "close": 260, "average": 259, "volume": 226989, "value": 5874924600, "frequency": 2228, "change": 2, "change_percentage": 0.78},
        {"date": "2026-09-30", "open": 260, "high": 262, "low": 256, "close": 258, "average": 259, "volume": 281305, "value": 7273621400, "frequency": 2835, "change": -2, "change_percentage": -0.77},
        {"date": "2026-10-01", "open": 258, "high": 262, "low": 250, "close": 252, "average": 254, "volume": 430368, "value": 10949214400, "frequency": 3204, "change": -6, "change_percentage": -2.33},
        {"date": "2026-10-02", "open": 254, "high": 258, "low": 250, "close": 256, "average": 254, "volume": 296898, "value": 7532044600, "frequency": 2029, "change": 4, "change_percentage": 1.59},
        {"date": "2026-10-05", "open": 256, "high": 258, "low": 254, "close": 256, "average": 255, "volume": 133901, "value": 3420510000, "frequency": 1390, "change": 0, "change_percentage": 0.00},
        {"date": "2026-10-06", "open": 256, "high": 270, "low": 256, "close": 266, "average": 264, "volume": 351646, "value": 9296553400, "frequency": 1905, "change": 10, "change_percentage": 3.91},
        {"date": "2026-10-07", "open": 266, "high": 270, "low": 258, "close": 270, "average": 263, "volume": 258990, "value": 6813245600, "frequency": 2173, "change": 4, "change_percentage": 1.50},
        {"date": "2026-10-08", "open": 268, "high": 270, "low": 264, "close": 266, "average": 267, "volume": 158920, "value": 4244049200, "frequency": 1515, "change": -4, "change_percentage": -1.48},
        {"date": "2026-10-09", "open": 266, "high": 270, "low": 264, "close": 268, "average": 267, "volume": 147267, "value": 3933012000, "frequency": 866, "change": 2, "change_percentage": 0.75},
        {"date": "2026-10-12", "open": 272, "high": 272, "low": 266, "close": 270, "average": 269, "volume": 282573, "value": 7611117400, "frequency": 2325, "change": 2, "change_percentage": 0.75},
        {"date": "2026-10-13", "open": 272, "high": 284, "low": 268, "close": 278, "average": 277, "volume": 688696, "value": 19043244400, "frequency": 3873, "change": 8, "change_percentage": 2.96},
        {"date": "2026-10-14", "open": 278, "high": 290, "low": 278, "close": 288, "average": 285, "volume": 940052, "value": 26835092000, "frequency": 5574, "change": 10, "change_percentage": 3.60},
        {"date": "2026-10-15", "open": 288, "high": 294, "low": 284, "close": 294, "average": 290, "volume": 1193721, "value": 34632500000, "frequency": 6919, "change": 6, "change_percentage": 2.08},
        {"date": "2026-10-16", "open": 282, "high": 282, "low": 250, "close": 264, "average": 266, "volume": 1276602, "value": 33994619800, "frequency": 5972, "change": -30, "change_percentage": -10.20},
        {"date": "2026-10-19", "open": 264, "high": 266, "low": 246, "close": 254, "average": 253, "volume": 1630363, "value": 41252500800, "frequency": 6903, "change": -10, "change_percentage": -3.79},
        {"date": "2026-10-20", "open": 254, "high": 274, "low": 254, "close": 270, "average": 268, "volume": 1028283, "value": 27600268600, "frequency": 5067, "change": 16, "change_percentage": 6.30},
        {"date": "2026-10-21", "open": 272, "high": 278, "low": 268, "close": 278, "average": 273, "volume": 728638, "value": 19858512800, "frequency": 5749, "change": 8, "change_percentage": 2.96},
        {"date": "2026-10-22", "open": 276, "high": 282, "low": 270, "close": 280, "average": 277, "volume": 687914, "value": 19082803000, "frequency": 4228, "change": 2, "change_percentage": 0.72},
        {"date": "2026-10-23", "open": 280, "high": 284, "low": 278, "close": 282, "average": 281, "volume": 789082, "value": 22180327000, "frequency": 3558, "change": 2, "change_percentage": 0.71},
        {"date": "2026-10-26", "open": 282, "high": 288, "low": 278, "close": 284, "average": 284, "volume": 561093, "value": 15926338600, "frequency": 3618, "change": 2, "change_percentage": 0.71},
        {"date": "2026-10-27", "open": 286, "high": 294, "low": 282, "close": 294, "average": 291, "volume": 1894109, "value": 55110991000, "frequency": 6557, "change": 10, "change_percentage": 3.52},
    ]

    tb = {
        "data": {
            "buy": [{"date": r["date"], "lot": {"raw": int(r["volume"] * 0.53)}, "value": {"raw": int(r["value"] * 0.53)}, "frequency": {"raw": int(r["frequency"] * 0.51)}} for r in rows],
            "sell": [{"date": r["date"], "lot": {"raw": int(r["volume"] * 0.47)}, "value": {"raw": int(r["value"] * 0.47)}, "frequency": {"raw": int(r["frequency"] * 0.49)}} for r in rows],
            "net_values": [
                {"date": "2026-10-21", "value": {"raw": 1577520400}},
                {"date": "2026-10-22", "value": {"raw": -4500116800}},
                {"date": "2026-10-23", "value": {"raw": -5489884200}},
                {"date": "2026-10-26", "value": {"raw": -144400400}},
                {"date": "2026-10-27", "value": {"raw": -91848200}},
            ],
            "big_money_buy": [{"date": r["date"], "lot": {"raw": int(r["volume"] * 0.20)}, "value": {"raw": int(r["value"] * 0.20)}, "frequency": {"raw": 75}} for r in rows],
            "big_money_sell": [{"date": r["date"], "lot": {"raw": int(r["volume"] * 0.12)}, "value": {"raw": int(r["value"] * 0.12)}, "frequency": {"raw": 65}} for r in rows],
            "big_money_net_values": [
                {"date": "2026-10-21", "value": {"raw": 1850000000}},
                {"date": "2026-10-22", "value": {"raw": 1200000000}},
                {"date": "2026-10-23", "value": {"raw": 1450000000}},
                {"date": "2026-10-26", "value": {"raw": 800000000}},
                {"date": "2026-10-27", "value": {"raw": -524773200}},
            ],
            "big_money_rt": {
                "buy": [{"date": r["date"], "lot": {"raw": 35000}, "value": {"raw": 1000000000}, "frequency": {"raw": 40}} for r in rows],
                "sell": [{"date": r["date"], "lot": {"raw": 45000}, "value": {"raw": 1300000000}, "frequency": {"raw": 50}} for r in rows],
                "net_values": [
                    {"date": "2026-10-21", "value": {"raw": -800000000}},
                    {"date": "2026-10-22", "value": {"raw": -1200000000}},
                    {"date": "2026-10-23", "value": {"raw": -1500000000}},
                    {"date": "2026-10-26", "value": {"raw": -600000000}},
                    {"date": "2026-10-27", "value": {"raw": -91848200}},
                ],
            },
        }
    }

    md = {
        "data": {
            "from": "2026-07-27",
            "to": "2026-10-27",
            "bandar_detector": {
                "broker_accdist": "Acc",
                "average": 277.79,
                "total_buyer": 24,
                "total_seller": 52,
                "top1": {"percent": 7.70},
                "top3": {"percent": 41.75},
                "top5": {"percent": 36.35},
                "avg5": {"percent": 31.17},
            },
            "broker_summary": {
                "brokers_buy": [
                    {"netbs_broker_code": "CC", "type": "Pemerintah", "blot": "2153602", "blotv": "594237100", "bval": "57716812000", "bvalv": "159964205400", "freq": "22893", "netbs_buy_avg_price": "269.19"},
                    {"netbs_broker_code": "AK", "type": "Asing", "blot": "1782834", "blotv": "779017500", "bval": "52023203200", "bvalv": "212786443000", "freq": "49764", "netbs_buy_avg_price": "273.15"},
                    {"netbs_broker_code": "KZ", "type": "Asing", "blot": "1106154", "blotv": "127122500", "bval": "30246766000", "bvalv": "34538479600", "freq": "5509", "netbs_buy_avg_price": "271.69"},
                    {"netbs_broker_code": "OD", "type": "Pemerintah", "blot": "247250", "blotv": "94884900", "bval": "6234227400", "bvalv": "25270955800", "freq": "4550", "netbs_buy_avg_price": "266.33"},
                ],
                "brokers_sell": [
                    {"netbs_broker_code": "ZP", "type": "Asing", "slot": "-1710665", "slotv": "237937400", "sval": "-47880000000", "svalv": "66200000000", "freq": "18400", "netbs_sell_avg_price": "279.90"},
                    {"netbs_broker_code": "PD", "type": "Lokal", "slot": "-495172", "slotv": "169542000", "sval": "-13980000000", "svalv": "47200000000", "freq": "14200", "netbs_sell_avg_price": "282.40"},
                    {"netbs_broker_code": "XL", "type": "Lokal", "slot": "-260689", "slotv": "326084000", "sval": "-7620000000", "svalv": "91000000000", "freq": "26500", "netbs_sell_avg_price": "292.40"},
                ],
            },
        }
    }

    rtc = {
        "data": {
            "broker_chart_data": [
                {
                    "type": "TYPE_CHART_VOLUME",
                    "charts": [
                        {"broker_code": "AK", "chart": [{"date": r["date"], "value": {"raw": str(50000 + i * 80000)}} for i, r in enumerate(rows)]},
                        {"broker_code": "CC", "chart": [{"date": r["date"], "value": {"raw": str(200000 + i * 90000)}} for i, r in enumerate(rows)]},
                        {"broker_code": "ZP", "chart": [{"date": r["date"], "value": {"raw": str(-200000 - i * 70000)}} for i, r in enumerate(rows)]},
                    ],
                }
            ]
        }
    }

    bd = {
        "data": {
            "by_volume": {
                "top_broker_buy": [
                    {"detail": {"code": "AK", "amount": 7790175}, "distribute_to": [{"code": "AK", "amount": 1505473}, {"code": "CC", "amount": 784399}, {"code": "XL", "amount": 598554}]},
                    {"detail": {"code": "CC", "amount": 5942371}, "distribute_to": [{"code": "CC", "amount": 686534}, {"code": "AK", "amount": 755248}, {"code": "XL", "amount": 376913}]},
                    {"detail": {"code": "KZ", "amount": 1271225}, "distribute_to": [{"code": "KZ", "amount": 7415}, {"code": "AK", "amount": 250000}]},
                ],
                "top_broker_sell": [
                    {"detail": {"code": "ZP", "amount": 2379374}, "distribute_to": [{"code": "AK", "amount": 600000}, {"code": "CC", "amount": 500000}]},
                    {"detail": {"code": "XL", "amount": 3260840}, "distribute_to": [{"code": "AK", "amount": 591849}, {"code": "CC", "amount": 528990}]},
                ],
            }
        }
    }
    return rows, tb, md, rtc, bd


def test_swing_screener_pwon_iceberg_absorption_markup():
    rows, tb, md, rtc, bd = _make_pwon_fixtures()
    res = analyze_swing_stock(
        historical_source=rows,
        trade_book_source=tb,
        market_detector_source=md,
        running_trade_chart_source=rtc,
        broker_distribution_source=bd,
        ticker="PWON",
    )
    assert res["ticker"] == "PWON"
    assert res["swing_score"] >= 80.0
    assert res["action"]["key"] == "STRONG_BUY"
    assert res["trade_plan"]["status"] == "READY"
    assert res["trade_plan"]["rr_net"] >= 2.0
    assert res["order_flow"]["execution_regime"] == "PASSIVE_ICEBERG_ABSORPTION"
    assert res["broker_network"]["network_topology"] == "MANY_TO_FEW_ABSORPTION"
    assert res["broker_network"]["top1_self_match_vs_net_multiple"] <= 0.50
    assert res["bandar_structure"]["bandar_summary"]["broker_accdist"] == "Acc"


def _make_intp_fixtures():
    """Realistic Multi-Month Base Breakout with Circular Broker Churn fixtures calibrated to INTP."""
    rows = [
        {"date": "2026-09-28", "open": 5075, "high": 5075, "low": 4920, "close": 4960, "average": 4983, "volume": 9432, "value": 4700361500, "frequency": 1786, "change": -115, "change_percentage": -2.27},
        {"date": "2026-09-29", "open": 4960, "high": 5025, "low": 4840, "close": 5000, "average": 4960, "volume": 6986, "value": 3464992000, "frequency": 771, "change": 40, "change_percentage": 0.81},
        {"date": "2026-09-30", "open": 5000, "high": 5000, "low": 4830, "close": 4860, "average": 4884, "volume": 16574, "value": 8094771000, "frequency": 1277, "change": -140, "change_percentage": -2.80},
        {"date": "2026-10-01", "open": 4850, "high": 4880, "low": 4760, "close": 4820, "average": 4815, "volume": 7294, "value": 3511933000, "frequency": 910, "change": -40, "change_percentage": -0.82},
        {"date": "2026-10-02", "open": 4820, "high": 4930, "low": 4780, "close": 4880, "average": 4867, "volume": 10389, "value": 5056541000, "frequency": 1216, "change": 60, "change_percentage": 1.24},
        {"date": "2026-10-05", "open": 4900, "high": 5025, "low": 4900, "close": 5025, "average": 4968, "volume": 12296, "value": 6109039000, "frequency": 1418, "change": 145, "change_percentage": 2.97},
        {"date": "2026-10-06", "open": 5050, "high": 5100, "low": 4970, "close": 5075, "average": 5019, "volume": 6008, "value": 3015214000, "frequency": 861, "change": 50, "change_percentage": 1.00},
        {"date": "2026-10-07", "open": 5025, "high": 5075, "low": 4920, "close": 4960, "average": 4959, "volume": 7681, "value": 3808865000, "frequency": 1344, "change": -115, "change_percentage": -2.27},
        {"date": "2026-10-08", "open": 4960, "high": 5000, "low": 4900, "close": 4950, "average": 4956, "volume": 10560, "value": 5233311000, "frequency": 1367, "change": -10, "change_percentage": -0.20},
        {"date": "2026-10-09", "open": 4900, "high": 5125, "low": 4900, "close": 5050, "average": 5054, "volume": 5336, "value": 2696788500, "frequency": 924, "change": 100, "change_percentage": 2.02},
        {"date": "2026-10-12", "open": 5050, "high": 5275, "low": 5025, "close": 5200, "average": 5211, "volume": 29966, "value": 15616500000, "frequency": 2625, "change": 150, "change_percentage": 2.97},
        {"date": "2026-10-13", "open": 5225, "high": 5275, "low": 5200, "close": 5200, "average": 5225, "volume": 12734, "value": 6653380000, "frequency": 1490, "change": 0, "change_percentage": 0.00},
        {"date": "2026-10-14", "open": 5250, "high": 5375, "low": 5250, "close": 5250, "average": 5322, "volume": 17953, "value": 9554235000, "frequency": 2231, "change": 50, "change_percentage": 0.96},
        {"date": "2026-10-15", "open": 5225, "high": 5375, "low": 5175, "close": 5375, "average": 5294, "volume": 12174, "value": 6445420000, "frequency": 1552, "change": 125, "change_percentage": 2.38},
        {"date": "2026-10-16", "open": 5025, "high": 5225, "low": 4570, "close": 5150, "average": 5018, "volume": 47533, "value": 23854004500, "frequency": 3281, "change": -225, "change_percentage": -4.19},
        {"date": "2026-10-19", "open": 5025, "high": 5150, "low": 4860, "close": 5025, "average": 4965, "volume": 30676, "value": 15231282500, "frequency": 3053, "change": -125, "change_percentage": -2.43},
        {"date": "2026-10-20", "open": 5100, "high": 5450, "low": 5025, "close": 5450, "average": 5301, "volume": 17044, "value": 9035760000, "frequency": 2879, "change": 425, "change_percentage": 8.46},
        {"date": "2026-10-21", "open": 5450, "high": 5500, "low": 5300, "close": 5500, "average": 5424, "volume": 19982, "value": 10837930000, "frequency": 3282, "change": 50, "change_percentage": 0.92},
        {"date": "2026-10-22", "open": 5500, "high": 5750, "low": 5400, "close": 5625, "average": 5616, "volume": 20851, "value": 11709032500, "frequency": 3298, "change": 125, "change_percentage": 2.27},
        {"date": "2026-10-23", "open": 5625, "high": 5775, "low": 5575, "close": 5650, "average": 5684, "volume": 13753, "value": 7817337500, "frequency": 2065, "change": 25, "change_percentage": 0.44},
        {"date": "2026-10-26", "open": 5650, "high": 5750, "low": 5575, "close": 5625, "average": 5667, "volume": 13682, "value": 7753385000, "frequency": 2573, "change": -25, "change_percentage": -0.44},
        {"date": "2026-10-27", "open": 5625, "high": 5950, "low": 5450, "close": 5950, "average": 5913, "volume": 111203, "value": 65749032500, "frequency": 1648, "change": 325, "change_percentage": 5.78},
    ]

    tb = {
        "data": {
            "buy": [{"date": r["date"], "lot": {"raw": int(r["volume"] * 0.53)}, "value": {"raw": int(r["value"] * 0.53)}, "frequency": {"raw": int(r["frequency"] * 0.51)}} for r in rows],
            "sell": [{"date": r["date"], "lot": {"raw": int(r["volume"] * 0.47)}, "value": {"raw": int(r["value"] * 0.47)}, "frequency": {"raw": int(r["frequency"] * 0.49)}} for r in rows],
            "net_values": [
                {"date": "2026-10-21", "value": {"raw": 827732500}},
                {"date": "2026-10-22", "value": {"raw": 1522015000}},
                {"date": "2026-10-23", "value": {"raw": 73050000}},
                {"date": "2026-10-26", "value": {"raw": 73927500}},
                {"date": "2026-10-27", "value": {"raw": 1767982500}},
            ],
            "big_money_buy": [{"date": r["date"], "lot": {"raw": 1500}, "value": {"raw": 850000000}, "frequency": {"raw": 25}} for r in rows],
            "big_money_sell": [{"date": r["date"], "lot": {"raw": 2200}, "value": {"raw": 1250000000}, "frequency": {"raw": 35}} for r in rows],
            "big_money_net_values": [
                {"date": "2026-10-21", "value": {"raw": -1200000000}},
                {"date": "2026-10-22", "value": {"raw": -1500000000}},
                {"date": "2026-10-23", "value": {"raw": -850000000}},
                {"date": "2026-10-26", "value": {"raw": -900000000}},
                {"date": "2026-10-27", "value": {"raw": 303200000}},
            ],
            "big_money_rt": {
                "buy": [{"date": r["date"], "lot": {"raw": 4000}, "value": {"raw": 2300000000}, "frequency": {"raw": 45}} for r in rows],
                "sell": [{"date": r["date"], "lot": {"raw": 2500}, "value": {"raw": 1400000000}, "frequency": {"raw": 30}} for r in rows],
                "net_values": [
                    {"date": "2026-10-21", "value": {"raw": 900000000}},
                    {"date": "2026-10-22", "value": {"raw": 1200000000}},
                    {"date": "2026-10-23", "value": {"raw": 350000000}},
                    {"date": "2026-10-26", "value": {"raw": 450000000}},
                    {"date": "2026-10-27", "value": {"raw": 1767982500}},
                ],
            },
        }
    }

    md = {
        "data": {
            "from": "2026-07-27",
            "to": "2026-10-27",
            "bandar_detector": {
                "broker_accdist": "Acc",
                "average": 5310.83,
                "total_buyer": 20,
                "total_seller": 50,
                "top1": {"percent": 46.15},
                "top3": {"percent": 46.72},
                "top5": {"percent": 42.39},
                "avg5": {"percent": 45.97},
            },
            "broker_summary": {
                "brokers_buy": [
                    {"netbs_broker_code": "AK", "type": "Asing", "blot": "159884", "blotv": "50622000", "bval": "86214065500", "bvalv": "273183080500", "freq": "38085", "netbs_buy_avg_price": "5396.53"},
                    {"netbs_broker_code": "RX", "type": "Asing", "blot": "36761", "blotv": "6356300", "bval": "18797450500", "bvalv": "32743721000", "freq": "5999", "netbs_buy_avg_price": "5151.38"},
                    {"netbs_broker_code": "CD", "type": "Lokal", "blot": "15479", "blotv": "1565400", "bval": "8191376500", "bvalv": "8279917000", "freq": "539", "netbs_buy_avg_price": "5289.33"},
                ],
                "brokers_sell": [
                    {"netbs_broker_code": "YU", "type": "Asing", "slot": "-46168", "slotv": "5500000", "sval": "-24313822000", "svalv": "29000000000", "freq": "2100", "netbs_sell_avg_price": "5266.00"},
                    {"netbs_broker_code": "XL", "type": "Lokal", "slot": "-25953", "slotv": "6906200", "sval": "-13722198500", "svalv": "36000000000", "freq": "7200", "netbs_sell_avg_price": "5287.00"},
                    {"netbs_broker_code": "DX", "type": "Pemerintah", "slot": "-24900", "slotv": "4485700", "sval": "-13259616500", "svalv": "24000000000", "freq": "1950", "netbs_sell_avg_price": "5325.00"},
                ],
            },
        }
    }

    rtc = {
        "data": {
            "broker_chart_data": [
                {
                    "type": "TYPE_CHART_VOLUME",
                    "charts": [
                        {"broker_code": "AK", "chart": [{"date": r["date"], "value": {"raw": str(117000 + i * 2000)}} for i, r in enumerate(rows)]},
                        {"broker_code": "RX", "chart": [{"date": r["date"], "value": {"raw": str(8000 + i * 1300)}} for i, r in enumerate(rows)]},
                        {"broker_code": "DX", "chart": [{"date": r["date"], "value": {"raw": str(-33000 + i * 400)}} for i, r in enumerate(rows)]},
                    ],
                }
            ]
        }
    }

    bd = {
        "data": {
            "by_volume": {
                "top_broker_buy": [
                    {"detail": {"code": "AK", "amount": 506220}, "distribute_to": [{"code": "AK", "amount": 169860}, {"code": "CC", "amount": 52798}, {"code": "ZP", "amount": 31952}]},
                    {"detail": {"code": "CC", "amount": 134143}, "distribute_to": [{"code": "AK", "amount": 52798}, {"code": "CC", "amount": 16614}]},
                ],
                "top_broker_sell": [
                    {"detail": {"code": "AK", "amount": 346336}, "distribute_to": [{"code": "CC", "amount": 32707}, {"code": "RX", "amount": 22059}]},
                    {"detail": {"code": "CC", "amount": 131802}, "distribute_to": [{"code": "AK", "amount": 52798}, {"code": "ZP", "amount": 12753}]},
                ],
            }
        }
    }
    return rows, tb, md, rtc, bd


def test_swing_screener_intp_buy_on_weakness_breakout():
    rows, tb, md, rtc, bd = _make_intp_fixtures()
    res = analyze_swing_stock(
        historical_source=rows,
        trade_book_source=tb,
        market_detector_source=md,
        running_trade_chart_source=rtc,
        broker_distribution_source=bd,
        ticker="INTP",
    )
    assert res["ticker"] == "INTP"
    assert 60.0 <= res["swing_score"] <= 75.0
    assert res["action"]["key"] == "BUY_ON_WEAKNESS"
    assert res["trade_plan"]["status"] == "READY"
    assert res["trade_plan"]["rr_net"] >= 2.0
    assert res["order_flow"]["paint_the_tape_trap"] is True
    assert res["broker_network"]["network_topology"] == "CIRCULAR_WASH_ROTATION"
    assert res["layer_scores"]["layer1_price"]["score"] == 100.0
    assert res["layer_scores"]["layer4_trajectory"]["score"] == 100.0


def test_swing_screener_2file_proportional_fallback_and_endpoint():
    rows, tb, _, _, _ = _make_untr_fixtures()
    res = analyze_swing_stock(
        historical_source=rows,
        trade_book_source=tb,
        ticker="UNTR",
    )
    assert res["active_layers"] == 2
    assert res["layer_scores"]["layer1_price"]["effective_weight_pct"] == 50.0
    assert res["layer_scores"]["layer2_orderflow"]["effective_weight_pct"] == 50.0
    assert res["layer_scores"]["layer3_bandar"]["score"] is None

    # Verify FastAPI route registration for POST /api/v1/analyze-swing
    from app.main import app
    swing_routes = [
        r for r in app.routes
        if getattr(r, "path", None) == "/api/v1/analyze-swing" and "POST" in getattr(r, "methods", set())
    ]
    assert len(swing_routes) == 1
    assert swing_routes[0].endpoint is analyze_swing_ticker


def test_swing_screener_bbca_institutional_cost_discount():
    bbca_dir = Path(r"C:\Users\polma\.gemini\antigravity\brain\9ca8275e-1507-49cc-a2f7-97b664c84502\scratch\zips\zip_4")
    if not bbca_dir.exists():
        return
    hist_f = next(bbca_dir.glob("*historical-trade*"))
    tb_f = next(bbca_dir.glob("*trade-book*"))
    md_f = next(bbca_dir.glob("*market-detector*"), None)
    rt_f = next(bbca_dir.glob("*running-trade*"), None)
    bd_f = next(bbca_dir.glob("*broker-distribution*"), None)

    res = analyze_swing_stock(
        historical_source=str(hist_f),
        trade_book_source=str(tb_f),
        market_detector_source=str(md_f) if md_f else None,
        running_trade_chart_source=str(rt_f) if rt_f else None,
        broker_distribution_source=str(bd_f) if bd_f else None,
        ticker="BBCA",
    )
    assert res["ticker"] == "BBCA"
    assert res["action"]["key"] == "WAIT_FOR_TRIGGER"
    assert res["action"]["best_setup"] == "Institutional Cost-Basis Discount Accumulation"
    tp = res["trade_plan"]
    assert tp["status"] == "READY"
    assert tp["entry_low"] < tp["entry_high"]
    assert tp["rr_net"] >= 2.0


def test_swing_screener_foru_markdown_waterfall_trap():
    foru_dir = Path(r"C:\Users\polma\.gemini\antigravity\brain\9ca8275e-1507-49cc-a2f7-97b664c84502\scratch\zips\zip_2")
    if not foru_dir.exists():
        return
    hist_f = next(foru_dir.glob("*historical-trade*"))
    tb_f = next(foru_dir.glob("*trade-book*"))
    md_f = next(foru_dir.glob("*market-detector*"), None)
    rt_f = next(foru_dir.glob("*running-trade*"), None)
    bd_f = next(foru_dir.glob("*broker-distribution*"), None)

    res = analyze_swing_stock(
        historical_source=str(hist_f),
        trade_book_source=str(tb_f),
        market_detector_source=str(md_f) if md_f else None,
        running_trade_chart_source=str(rt_f) if rt_f else None,
        broker_distribution_source=str(bd_f) if bd_f else None,
        ticker="FORU",
    )
    assert res["ticker"] == "FORU"
    assert res["action"]["key"] == "AVOID_DISTRIBUTION"
    assert res["action"]["best_setup"] == "Multi-Day Distribution / Markdown Waterfall Trap"
    assert res["trade_plan"]["rr_net"] == 0.0


def test_swing_screener_emtk_institutional_discount_buy_on_weakness():
    emtk_dir = Path(r"C:\Users\polma\.gemini\antigravity\brain\9ca8275e-1507-49cc-a2f7-97b664c84502\scratch\zips_batch2\zip_3")
    if not emtk_dir.exists():
        return
    hist_f = next(emtk_dir.glob("*historical-trade*"))
    tb_f = next(emtk_dir.glob("*trade-book*"))
    md_f = next(emtk_dir.glob("*market-detector*"), None)
    rt_f = next(emtk_dir.glob("*running-trade*"), None)
    bd_f = next(emtk_dir.glob("*broker-distribution*"), None)

    res = analyze_swing_stock(
        historical_source=str(hist_f),
        trade_book_source=str(tb_f),
        market_detector_source=str(md_f) if md_f else None,
        running_trade_chart_source=str(rt_f) if rt_f else None,
        broker_distribution_source=str(bd_f) if bd_f else None,
        ticker="EMTK",
    )
    assert res["ticker"] == "EMTK"
    assert res["action"]["key"] == "BUY_ON_WEAKNESS"
    assert res["action"]["best_setup"] == "Institutional Cost-Basis Discount Accumulation"
    tp = res["trade_plan"]
    assert tp["status"] == "READY"
    assert tp["rr_net"] >= 2.0


def test_swing_screener_ptro_avoid_distribution_trap():
    ptro_dir = Path(r"C:\Users\polma\.gemini\antigravity\brain\9ca8275e-1507-49cc-a2f7-97b664c84502\scratch\zips_batch2\zip_1")
    if not ptro_dir.exists():
        return
    hist_f = next(ptro_dir.glob("*historical-trade*"))
    tb_f = next(ptro_dir.glob("*trade-book*"))
    md_f = next(ptro_dir.glob("*market-detector*"), None)
    rt_f = next(ptro_dir.glob("*running-trade*"), None)
    bd_f = next(ptro_dir.glob("*broker-distribution*"), None)

    res = analyze_swing_stock(
        historical_source=str(hist_f),
        trade_book_source=str(tb_f),
        market_detector_source=str(md_f) if md_f else None,
        running_trade_chart_source=str(rt_f) if rt_f else None,
        broker_distribution_source=str(bd_f) if bd_f else None,
        ticker="PTRO",
    )
    assert res["ticker"] == "PTRO"
    assert res["action"]["key"] == "AVOID_DISTRIBUTION"
    assert res["action"]["best_setup"] == "Multi-Day Distribution / Markdown Waterfall Trap"
    assert res["trade_plan"]["rr_net"] == 0.0


def test_swing_screener_asii_ascending_breakout_buy_on_weakness():
    asii_dir = Path(r"C:\Users\polma\.gemini\antigravity\brain\9ca8275e-1507-49cc-a2f7-97b664c84502\scratch\zips_batch3\zip_2")
    if not asii_dir.exists():
        return
    hist_f = next(asii_dir.glob("*historical-trade*"))
    tb_f = next(asii_dir.glob("*trade-book*"))
    md_f = next(asii_dir.glob("*market-detector*"), None)
    rt_f = next(asii_dir.glob("*running-trade*"), None)
    bd_f = next(asii_dir.glob("*broker-distribution*"), None)

    res = analyze_swing_stock(
        historical_source=str(hist_f),
        trade_book_source=str(tb_f),
        market_detector_source=str(md_f) if md_f else None,
        running_trade_chart_source=str(rt_f) if rt_f else None,
        broker_distribution_source=str(bd_f) if bd_f else None,
        ticker="ASII",
    )
    assert res["ticker"] == "ASII"
    assert res["action"]["key"] == "BUY_ON_WEAKNESS"
    assert res["action"]["best_setup"] == "Ascending Value Area & Breakout Valid"
    tp = res["trade_plan"]
    assert tp["status"] == "READY"
    assert tp["rr_net"] >= 2.0


def test_swing_screener_toba_avoid_markdown_trap():
    toba_dir = Path(r"C:\Users\polma\.gemini\antigravity\brain\9ca8275e-1507-49cc-a2f7-97b664c84502\scratch\zips_batch3\zip_4")
    if not toba_dir.exists():
        return
    hist_f = next(toba_dir.glob("*historical-trade*"))
    tb_f = next(toba_dir.glob("*trade-book*"))
    md_f = next(toba_dir.glob("*market-detector*"), None)
    rt_f = next(toba_dir.glob("*running-trade*"), None)
    bd_f = next(toba_dir.glob("*broker-distribution*"), None)

    res = analyze_swing_stock(
        historical_source=str(hist_f),
        trade_book_source=str(tb_f),
        market_detector_source=str(md_f) if md_f else None,
        running_trade_chart_source=str(rt_f) if rt_f else None,
        broker_distribution_source=str(bd_f) if bd_f else None,
        ticker="TOBA",
    )
    assert res["ticker"] == "TOBA"
    assert res["action"]["key"] == "AVOID_DISTRIBUTION"
    assert res["action"]["best_setup"] == "Multi-Day Distribution / Markdown Waterfall Trap"
    assert res["trade_plan"]["rr_net"] == 0.0
    assert res["action"]["best_setup"] == "Multi-Day Distribution / Markdown Waterfall Trap"
    assert res["trade_plan"]["rr_net"] == 0.0
