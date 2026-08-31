"""tiger_options 估值逻辑的离线测试，用假的期权链，不接触真实 API。"""

import types
import pandas as pd
import pytest

import tiger_options


def make_chain(rows):
    return pd.DataFrame(rows)


class FakeQuoteClient:
    def __init__(self, chain):
        self._chain = chain

    def get_option_chain(self, symbol, expiry):
        return self._chain


AAOI_CHAIN = make_chain([
    {"identifier": "AAOI 20260821 133 CALL", "strike": 133.0, "put_call": "CALL",
     "bid_price": 12.60, "ask_price": 12.80},
    {"identifier": "AAOI 20260821 170 CALL", "strike": 170.0, "put_call": "CALL",
     "bid_price": 4.00, "ask_price": 4.20},
])


def run_spread(capsys, chain, **kwargs):
    args = types.SimpleNamespace(
        symbol="AAOI", expiry="2026-08-21", side="CALL",
        long=133.0, short=170.0, qty=8, cost=10.65,
    )
    for k, v in kwargs.items():
        setattr(args, k, v)
    tiger_options.cmd_spread(FakeQuoteClient(chain), args)
    return capsys.readouterr().out


def test_mid_prices_and_spread_value(capsys):
    out = run_spread(capsys, AAOI_CHAIN)
    # 长腿中值 12.70，短腿中值 4.10，价差 8.60
    assert "中值 12.70" in out
    assert "中值 4.10" in out
    assert "价差中值        8.60" in out


def test_conservative_exit_uses_adverse_side(capsys):
    out = run_spread(capsys, AAOI_CHAIN)
    # 卖长腿走 bid 12.60，买短腿走 ask 4.20 -> 8.40
    assert "保守平仓价      8.40" in out


def test_breakeven_and_max_values(capsys):
    out = run_spread(capsys, AAOI_CHAIN)
    assert "打平点          143.65" in out
    assert "最大亏损        10.65" in out          # 每组
    assert "$8,520" in out                          # 8 组合计
    assert "最大盈利        26.35" in out
    assert "$21,080" in out


def test_unrealized_pnl_matches_broker_screenshot(capsys):
    out = run_spread(capsys, AAOI_CHAIN)
    # (8.60 - 10.65) * 100 * 8 = -1,640
    assert "$-1,640" in out


def test_deep_itm_spread_approaches_max_profit(capsys):
    chain = make_chain([
        {"strike": 133.0, "put_call": "CALL", "bid_price": 44.0, "ask_price": 44.4},
        {"strike": 170.0, "put_call": "CALL", "bid_price": 10.8, "ask_price": 11.2},
    ])
    out = run_spread(capsys, chain)
    # 价差 33.2，占最大利润 (33.2-10.65)/26.35 = 85.6%
    assert "价差中值        33.20" in out
    assert "已实现占最大利润 85.6%" in out


def test_missing_strike_is_reported(capsys):
    with pytest.raises(SystemExit, match="找不到行权价"):
        run_spread(capsys, AAOI_CHAIN, short=175.0)


def test_put_side_is_filtered(capsys):
    chain = make_chain([
        {"strike": 100.0, "put_call": "PUT", "bid_price": 6.5, "ask_price": 6.7},
        {"strike": 90.0, "put_call": "PUT", "bid_price": 3.4, "ask_price": 3.6},
        {"strike": 100.0, "put_call": "CALL", "bid_price": 99.0, "ask_price": 99.9},
    ])
    args = dict(side="PUT", long=90.0, short=100.0, qty=1, cost=-3.1)
    out = run_spread(capsys, chain, **args)
    # 只取 PUT 腿：90 中值 3.50，100 中值 6.60
    assert "中值 3.50" in out
    assert "中值 6.60" in out


def test_one_sided_quote_falls_back():
    assert tiger_options._mid(None, 5.0) == 5.0
    assert tiger_options._mid(3.0, None) == 3.0
    assert tiger_options._mid(None, None) is None
    assert tiger_options._mid(3.0, 5.0) == 4.0


def test_empty_chain_raises():
    with pytest.raises(SystemExit, match="没有返回期权链数据"):
        tiger_options._fetch_chain(FakeQuoteClient(make_chain([])), "AAOI", "2026-08-21")


def test_avgo_debit_call_spread_economics():
    econ = tiger_options.spread_economics(370, 420, 13.35, qty=1)
    assert econ.width == 50
    assert econ.max_loss == 13.35
    assert econ.max_loss_dollars == 1335
    assert round(econ.max_profit, 2) == 36.65
    assert econ.max_profit_dollars == 3665
    assert round(econ.breakeven, 2) == 383.35
    assert round(econ.max_profit / econ.max_loss, 2) == 2.75


def test_avgo_spread_print_matches_economics(capsys):
    chain = make_chain([
        {"strike": 370.0, "put_call": "CALL", "bid_price": 28.0, "ask_price": 28.4},
        {"strike": 420.0, "put_call": "CALL", "bid_price": 8.9, "ask_price": 9.3},
    ])
    out = run_spread(
        capsys, chain,
        symbol="AVGO", expiry="2026-09-18",
        long=370.0, short=420.0, qty=1, cost=13.35,
    )
    assert "打平点          383.35" in out
    assert "最大亏损        13.35   (共 $1,335)" in out
    assert "最大盈利        36.65   (共 $3,665)" in out
    # 中值 28.20 - 9.10 = 19.10；(19.10 - 13.35) * 100 = 575
    assert "价差中值        19.10" in out
    assert "$575" in out


def test_journal_prints_avgo_card(capsys):
    tiger_options.main(["journal"])
    out = capsys.readouterr().out
    assert "AVGO  2026-09-18" in out
    assert "370/420 CALL" in out
    assert "到期打平        383.35" in out
    assert "$1,335" in out
    assert "$3,665" in out
    assert "仓位止损" in out
    assert "420" in out

