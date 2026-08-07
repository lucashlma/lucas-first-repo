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


class FakePermClient:
    def __init__(self, perms):
        self._perms = perms
        self.grabbed = False

    def get_quote_permission(self):
        return self._perms

    def grab_quote_permission(self):
        self.grabbed = True
        return self._perms


PERMS = [
    {"name": "usQuoteBasic", "expire_at": 1788000000000},
    {"name": "usOptionQuote", "expire_at": 1788000000000},
    {"name": "hkStockQuoteLv2", "expire_at": -1},
]


def test_permission_lists_us_stock_and_option(capsys):
    tiger_options.cmd_permission(FakePermClient(PERMS), None)
    out = capsys.readouterr().out
    assert "usQuoteBasic" in out
    assert "usOptionQuote" in out
    assert "美股股票行情 (usQuoteBasic):  有" in out
    assert "美股期权行情 (usOptionQuote): 有" in out


def test_permission_reports_missing_option_entitlement(capsys):
    tiger_options.cmd_permission(FakePermClient([PERMS[0]]), None)
    out = capsys.readouterr().out
    assert "美股股票行情 (usQuoteBasic):  有" in out
    assert "美股期权行情 (usOptionQuote): 无" in out


def test_permanent_entitlement_shown_as_long_lived(capsys):
    tiger_options.cmd_permission(FakePermClient([PERMS[2]]), None)
    assert "长期有效" in capsys.readouterr().out


def test_empty_permission_list(capsys):
    tiger_options.cmd_permission(FakePermClient([]), None)
    assert "当前没有任何行情权限" in capsys.readouterr().out


def test_grab_calls_sdk_and_warns_about_app(capsys):
    client = FakePermClient(PERMS)
    tiger_options.cmd_grab(client, None)
    out = capsys.readouterr().out
    assert client.grabbed is True
    assert "抢占到本设备" in out
    assert "APP 端的行情会因此失效" in out


class FakeQuoteBrief:
    """模拟 SDK 返回的对象（非 DataFrame）。"""

    def __init__(self, symbol, price):
        self.symbol = symbol
        self.latest_price = price

    def __str__(self):
        return f"QuoteBrief(symbol={self.symbol}, latest_price={self.latest_price})"


def test_render_dataframe():
    df = make_chain([{"symbol": "SPCX", "latest_price": 114.92}])
    out = tiger_options._render(df)
    assert "SPCX" in out and "114.92" in out


def test_render_object_list_does_not_crash():
    # 这正是 get_briefs 返回 list 时曾触发 AttributeError 的场景
    out = tiger_options._render([FakeQuoteBrief("SPCX", 114.92), FakeQuoteBrief("AAOI", 133.77)])
    assert "SPCX" in out and "AAOI" in out
    assert "114.92" in out


def test_render_empty_cases():
    assert tiger_options._render(None) == "(无数据)"
    assert tiger_options._render([]) == "(无数据)"
    assert tiger_options._render(make_chain([])) == "(无数据)"


def test_quote_uses_stock_briefs_not_briefs(capsys):
    calls = []

    class C:
        def get_stock_briefs(self, symbols, include_hour_trading=False):
            calls.append(("get_stock_briefs", symbols))
            return make_chain([{"symbol": s, "latest_price": 114.92} for s in symbols])

        def get_briefs(self, symbols):
            raise AssertionError("不应调用已弃用的 get_briefs")

    tiger_options.cmd_quote(C(), types.SimpleNamespace(symbols=["SPCX"]))
    assert calls == [("get_stock_briefs", ["SPCX"])]
    assert "SPCX" in capsys.readouterr().out
