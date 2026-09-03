#!/usr/bin/env python3
"""老虎证券 OpenAPI 只读行情工具。

只读：本脚本不包含任何下单、撤单、修改仓位的调用。

凭证从环境变量读取，不接受命令行传入，避免出现在 shell history 里：
    TIGER_ID                老虎开放平台的 tiger id
    TIGER_ACCOUNT           账户号（模拟盘或实盘）
    TIGER_PRIVATE_KEY_PATH  RSA 私钥文件路径

用法：
    python tiger_options.py quote AAOI SPCX
    python tiger_options.py expirations AAOI
    python tiger_options.py chain AAOI --expiry 2026-08-21 --min-strike 120 --max-strike 180
    python tiger_options.py spread AAOI --expiry 2026-08-21 --long 133 --short 170 --qty 8 --cost 10.65
    python tiger_options.py spread AVGO --expiry 2026-09-18 --long 370 --short 420 --cost 13.35
    python tiger_options.py journal
    python tiger_options.py positions
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from pathlib import Path

REQUIRED_ENV = ("TIGER_ID", "TIGER_ACCOUNT", "TIGER_PRIVATE_KEY_PATH")
DEFAULT_JOURNAL = Path(__file__).resolve().parent / "trades" / "open.json"


@dataclass
class Credentials:
    tiger_id: str
    account: str
    private_key_path: str


def load_credentials() -> Credentials:
    missing = [name for name in REQUIRED_ENV if not os.environ.get(name)]
    if missing:
        raise SystemExit(
            "缺少环境变量: "
            + ", ".join(missing)
            + "\n\n请先设置:\n"
            + "  export TIGER_ID=your_tiger_id\n"
            + "  export TIGER_ACCOUNT=your_account\n"
            + "  export TIGER_PRIVATE_KEY_PATH=/path/to/rsa_private_key.pem\n"
        )

    key_path = os.path.expanduser(os.environ["TIGER_PRIVATE_KEY_PATH"])
    if not os.path.isfile(key_path):
        raise SystemExit(f"找不到私钥文件: {key_path}")

    return Credentials(
        tiger_id=os.environ["TIGER_ID"],
        account=os.environ["TIGER_ACCOUNT"],
        private_key_path=key_path,
    )


def build_clients(creds: Credentials):
    from tigeropen.common.consts import Language
    from tigeropen.common.util.signature_utils import read_private_key
    from tigeropen.quote.quote_client import QuoteClient
    from tigeropen.tiger_open_config import TigerOpenClientConfig
    from tigeropen.trade.trade_client import TradeClient

    config = TigerOpenClientConfig()
    config.private_key = read_private_key(creds.private_key_path)
    config.tiger_id = creds.tiger_id
    config.account = creds.account
    config.language = Language.zh_CN

    return QuoteClient(config), TradeClient(config)


def _mid(bid, ask):
    """买卖中值。任一侧缺失时退化为另一侧。"""
    have_bid = bid is not None and bid > 0
    have_ask = ask is not None and ask > 0
    if have_bid and have_ask:
        return (bid + ask) / 2
    if have_ask:
        return ask
    if have_bid:
        return bid
    return None


@dataclass
class SpreadEconomics:
    """垂直价差到期结构（debit 为正成本）。"""

    width: float
    cost: float
    qty: int
    max_profit: float
    breakeven: float
    multiplier: int

    @property
    def max_loss(self) -> float:
        return self.cost

    @property
    def max_loss_dollars(self) -> float:
        return self.cost * self.multiplier

    @property
    def max_profit_dollars(self) -> float:
        return self.max_profit * self.multiplier

    @property
    def cost_dollars(self) -> float:
        return self.cost * self.multiplier


def spread_economics(long_strike: float, short_strike: float, cost: float, qty: int = 1) -> SpreadEconomics:
    """Debit 垂直价差的宽度、打平点、最大盈亏。cost 为每组净借方。"""
    width = abs(short_strike - long_strike)
    return SpreadEconomics(
        width=width,
        cost=cost,
        qty=qty,
        max_profit=width - cost,
        breakeven=long_strike + cost,
        multiplier=100 * qty,
    )


def _row_value(row, *names):
    for name in names:
        if name in row and row[name] is not None:
            return row[name]
    return None


def cmd_quote(quote_client, args) -> None:
    briefs = quote_client.get_briefs(args.symbols)
    print(briefs.to_string(index=False))


def cmd_expirations(quote_client, args) -> None:
    expirations = quote_client.get_option_expirations(symbols=[args.symbol])
    print(expirations.to_string(index=False))


def _fetch_chain(quote_client, symbol: str, expiry: str):
    chain = quote_client.get_option_chain(symbol, expiry)
    if chain is None or len(chain) == 0:
        raise SystemExit(f"{symbol} {expiry} 没有返回期权链数据，请确认到期日有效且已开通期权行情权限。")
    return chain


def cmd_chain(quote_client, args) -> None:
    chain = _fetch_chain(quote_client, args.symbol, args.expiry)

    if "put_call" in chain.columns:
        chain = chain[chain["put_call"].str.upper() == args.side.upper()]
    if args.min_strike is not None:
        chain = chain[chain["strike"].astype(float) >= args.min_strike]
    if args.max_strike is not None:
        chain = chain[chain["strike"].astype(float) <= args.max_strike]

    keep = [
        c
        for c in (
            "identifier", "strike", "put_call", "bid_price", "ask_price",
            "latest_price", "volume", "open_interest", "implied_vol", "delta",
        )
        if c in chain.columns
    ]
    print(chain[keep].sort_values("strike").to_string(index=False))


def cmd_spread(quote_client, args) -> None:
    """给垂直价差做实时估值，并对照建仓成本算盈亏。"""
    chain = _fetch_chain(quote_client, args.symbol, args.expiry)
    if "put_call" in chain.columns:
        chain = chain[chain["put_call"].str.upper() == args.side.upper()]
    chain = chain.copy()
    chain["strike"] = chain["strike"].astype(float)

    def leg(strike: float):
        match = chain[chain["strike"] == strike]
        if match.empty:
            raise SystemExit(f"期权链里找不到行权价 {strike}")
        row = match.iloc[0]
        bid = _row_value(row, "bid_price", "bid")
        ask = _row_value(row, "ask_price", "ask")
        bid = float(bid) if bid is not None else None
        ask = float(ask) if ask is not None else None
        return bid, ask, _mid(bid, ask)

    long_bid, long_ask, long_mid = leg(args.long)
    short_bid, short_ask, short_mid = leg(args.short)

    if long_mid is None or short_mid is None:
        raise SystemExit("某一腿没有有效报价，无法估值。")

    # 平掉多头价差要卖长腿、买回短腿，所以按不利一侧估算可实现价值。
    spread_mid = long_mid - short_mid
    spread_exit = None
    if long_bid and short_ask:
        spread_exit = long_bid - short_ask

    print(f"\n{args.symbol}  {args.expiry}  {args.long}/{args.short} {args.side.upper()} 垂直价差  ×{args.qty} 组\n")
    print(f"  长腿 {args.long:>7.2f}   bid {long_bid}  ask {long_ask}  中值 {long_mid:.2f}")
    print(f"  短腿 {args.short:>7.2f}   bid {short_bid}  ask {short_ask}  中值 {short_mid:.2f}")
    print(f"\n  价差中值        {spread_mid:.2f}")
    if spread_exit is not None:
        print(f"  保守平仓价      {spread_exit:.2f}   (卖长腿bid / 买短腿ask)")

    if args.cost is None:
        print("\n  未提供 --cost，跳过盈亏计算。")
        return

    econ = spread_economics(args.long, args.short, args.cost, args.qty)
    print(f"\n  建仓成本        {econ.cost:.2f}   (共 ${econ.cost_dollars:,.0f})")
    print(f"  打平点          {econ.breakeven:.2f}")
    print(f"  最大亏损        {econ.max_loss:.2f}   (共 ${econ.max_loss_dollars:,.0f})")
    print(f"  最大盈利        {econ.max_profit:.2f}   (共 ${econ.max_profit_dollars:,.0f})")

    pnl = (spread_mid - econ.cost) * econ.multiplier
    captured = (spread_mid - econ.cost) / econ.max_profit * 100 if econ.max_profit else 0
    print(f"\n  当前浮动盈亏    ${pnl:,.0f}   (按中值)")
    print(f"  已实现占最大利润 {captured:.1f}%")
    if spread_exit is not None:
        pnl_exit = (spread_exit - econ.cost) * econ.multiplier
        print(f"  按保守价平仓    ${pnl_exit:,.0f}")
    print()


def load_journal(path: Path | None = None) -> list[dict]:
    import json

    journal_path = path or DEFAULT_JOURNAL
    if not journal_path.is_file():
        raise SystemExit(f"找不到交易日志: {journal_path}")
    with journal_path.open(encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, list):
        raise SystemExit("交易日志必须是 JSON 数组。")
    return data


def format_journal_card(trade: dict) -> str:
    qty = int(trade.get("qty") or 1)
    econ = spread_economics(
        float(trade["long"]),
        float(trade["short"]),
        float(trade["cost"]),
        qty,
    )
    reward_risk = econ.max_profit / econ.max_loss if econ.max_loss else 0
    lines = [
        f"{trade.get('id', trade['symbol'])}  {trade['symbol']}  {trade['expiry']}",
        f"  {trade['long']}/{trade['short']} {str(trade.get('side', 'CALL')).upper()}  debit spread  ×{qty} 组",
        f"  建仓净借方      {econ.cost:.2f}   (${econ.cost_dollars:,.0f})",
        f"  宽度            {econ.width:.2f}",
        f"  到期打平        {econ.breakeven:.2f}",
        f"  最大亏损        {econ.max_loss:.2f}   (${econ.max_loss_dollars:,.0f})  ← 仓位止损",
        f"  最大盈利        {econ.max_profit:.2f}   (${econ.max_profit_dollars:,.0f})  盈亏比 {reward_risk:.2f}:1",
    ]
    if trade.get("stop"):
        lines.append(f"  止损            {trade['stop']}")
    if trade.get("take_profit"):
        lines.append(f"  止盈            {trade['take_profit']}")
    if trade.get("note"):
        lines.append(f"  备注            {trade['note']}")
    return "\n".join(lines) + "\n"


def cmd_journal(args) -> None:
    """打印已记录价差的到期结构（不连行情）。"""
    trades = load_journal(Path(args.path) if args.path else None)
    if not trades:
        print("日志为空。")
        return
    for i, trade in enumerate(trades):
        if i:
            print()
        print(format_journal_card(trade))


def cmd_positions(trade_client, args) -> None:
    positions = trade_client.get_positions(account=args.account)
    if not positions:
        print("没有持仓。")
        return
    for p in positions:
        print(p)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="老虎证券 OpenAPI 只读行情工具（不含任何下单功能）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_quote = sub.add_parser("quote", help="股票实时报价")
    p_quote.add_argument("symbols", nargs="+")

    p_exp = sub.add_parser("expirations", help="列出可用到期日")
    p_exp.add_argument("symbol")

    p_chain = sub.add_parser("chain", help="拉取期权链")
    p_chain.add_argument("symbol")
    p_chain.add_argument("--expiry", required=True, help="到期日，格式 YYYY-MM-DD")
    p_chain.add_argument("--side", default="CALL", choices=["CALL", "PUT", "call", "put"])
    p_chain.add_argument("--min-strike", type=float)
    p_chain.add_argument("--max-strike", type=float)

    p_spread = sub.add_parser("spread", help="垂直价差实时估值与盈亏")
    p_spread.add_argument("symbol")
    p_spread.add_argument("--expiry", required=True, help="到期日，格式 YYYY-MM-DD")
    p_spread.add_argument("--long", type=float, required=True, help="买入腿行权价")
    p_spread.add_argument("--short", type=float, required=True, help="卖出腿行权价")
    p_spread.add_argument("--qty", type=int, default=1, help="组数")
    p_spread.add_argument("--cost", type=float, help="每组建仓净成本")
    p_spread.add_argument("--side", default="CALL", choices=["CALL", "PUT", "call", "put"])

    p_pos = sub.add_parser("positions", help="查询当前持仓")
    p_pos.add_argument("--account", default=None)

    p_journal = sub.add_parser("journal", help="打印交易日志里的价差结构（不连行情）")
    p_journal.add_argument("--path", default=None, help="JSON 日志路径，默认 trades/open.json")

    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)

    if args.command == "journal":
        cmd_journal(args)
        return 0

    creds = load_credentials()
    quote_client, trade_client = build_clients(creds)

    if args.command == "positions":
        if args.account is None:
            args.account = creds.account
        cmd_positions(trade_client, args)
    else:
        handler = {
            "quote": cmd_quote,
            "expirations": cmd_expirations,
            "chain": cmd_chain,
            "spread": cmd_spread,
        }[args.command]
        handler(quote_client, args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
