#!/usr/bin/env python3
"""老虎证券 OpenAPI 只读行情工具。

只读：本脚本不包含任何下单、撤单、修改仓位的调用。

凭证从环境变量读取，不接受命令行传入，避免出现在 shell history 里。

方式一（推荐）——用开发者中心下载的配置文件：
    TIGER_PROPS_PATH        tiger_openapi_config.properties 所在目录

方式二——手动指定：
    TIGER_ID                老虎开放平台的 tiger id
    TIGER_ACCOUNT           账户号（模拟盘或实盘）
    TIGER_PRIVATE_KEY_PATH  RSA 私钥文件路径
    TIGER_LICENSE           可选，如 TBSG / TBNZ

用法：
    python tiger_options.py permission          # 查看当前行情权限
    python tiger_options.py grab                # 把行情权限抢占到本设备
    python tiger_options.py quote AAOI SPCX
    python tiger_options.py expirations AAOI
    python tiger_options.py chain AAOI --expiry 2026-08-21 --min-strike 120 --max-strike 180
    python tiger_options.py spread AAOI --expiry 2026-08-21 --long 133 --short 170 --qty 8 --cost 10.65
    python tiger_options.py positions
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from datetime import datetime

MANUAL_ENV = ("TIGER_ID", "TIGER_ACCOUNT", "TIGER_PRIVATE_KEY_PATH")

SETUP_HINT = """\
未找到凭证配置。两种方式任选其一：

【方式一 · 推荐】用开发者中心下载的配置文件
  1. 打开 https://developer.itigerup.com/profile
  2. 点「生成密钥」，下载 tiger_openapi_config.properties
  3. 放到某个目录，例如 ~/.tiger/
  4. export TIGER_PROPS_PATH=~/.tiger

【方式二】手动指定
  export TIGER_ID=你的tiger_id
  export TIGER_ACCOUNT=你的账户号
  export TIGER_PRIVATE_KEY_PATH=~/.tiger/rsa_private_key.pem
"""


@dataclass
class Credentials:
    """props_path 与手动字段二选一。"""

    props_path: str | None = None
    tiger_id: str | None = None
    account: str | None = None
    private_key_path: str | None = None
    license: str | None = None


def load_credentials() -> Credentials:
    props_path = os.environ.get("TIGER_PROPS_PATH")
    if props_path:
        props_dir = os.path.expanduser(props_path)
        if os.path.isfile(props_dir):
            props_dir = os.path.dirname(props_dir)
        if not os.path.isdir(props_dir):
            raise SystemExit(f"TIGER_PROPS_PATH 不是有效目录: {props_dir}")
        expected = os.path.join(props_dir, "tiger_openapi_config.properties")
        if not os.path.isfile(expected):
            raise SystemExit(f"目录里没有 tiger_openapi_config.properties: {props_dir}")
        return Credentials(props_path=props_dir, account=os.environ.get("TIGER_ACCOUNT"))

    missing = [name for name in MANUAL_ENV if not os.environ.get(name)]
    if missing:
        raise SystemExit("缺少: " + ", ".join(missing) + "\n\n" + SETUP_HINT)

    key_path = os.path.expanduser(os.environ["TIGER_PRIVATE_KEY_PATH"])
    if not os.path.isfile(key_path):
        raise SystemExit(f"找不到私钥文件: {key_path}")

    return Credentials(
        tiger_id=os.environ["TIGER_ID"],
        account=os.environ["TIGER_ACCOUNT"],
        private_key_path=key_path,
        license=os.environ.get("TIGER_LICENSE"),
    )


def build_clients(creds: Credentials):
    from tigeropen.common.consts import Language
    from tigeropen.common.util.signature_utils import read_private_key
    from tigeropen.quote.quote_client import QuoteClient
    from tigeropen.tiger_open_config import TigerOpenClientConfig
    from tigeropen.trade.trade_client import TradeClient

    if creds.props_path:
        config = TigerOpenClientConfig(props_path=creds.props_path)
    else:
        config = TigerOpenClientConfig()
        config.tiger_id = creds.tiger_id
        config.account = creds.account
        config.private_key = read_private_key(creds.private_key_path)
        if creds.license:
            config.license = creds.license

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


def _row_value(row, *names):
    for name in names:
        if name in row and row[name] is not None:
            return row[name]
    return None


def _print_permissions(permissions) -> None:
    if not permissions:
        print("当前没有任何行情权限。")
        return
    print(f"{'权限名':<32} {'到期时间':<22}")
    print("-" * 56)
    for p in permissions:
        name = p.get("name", "?")
        expire = p.get("expire_at")
        if expire == -1:
            when = "长期有效"
        elif expire:
            when = datetime.fromtimestamp(expire / 1000).strftime("%Y-%m-%d %H:%M:%S")
        else:
            when = "未知"
        print(f"{name:<32} {when:<22}")

    names = {p.get("name") for p in permissions}
    print()
    print(f"  美股股票行情 (usQuoteBasic):  {'有' if 'usQuoteBasic' in names else '无'}")
    print(f"  美股期权行情 (usOptionQuote): {'有' if 'usOptionQuote' in names else '无'}")


def cmd_permission(quote_client, args) -> None:
    _print_permissions(quote_client.get_quote_permission())


def cmd_grab(quote_client, args) -> None:
    """行情权限同一时间只在一个设备上生效，抢占后 APP 端会失效。"""
    print("正在把行情权限抢占到本设备……\n")
    _print_permissions(quote_client.grab_quote_permission())
    print("\n注意：APP 端的行情会因此失效，在 APP 里重新查看行情会把权限抢回去。")


def _render(result) -> str:
    """SDK 有的接口返回 DataFrame，有的返回对象列表，统一成可打印文本。"""
    if result is None:
        return "(无数据)"
    if hasattr(result, "to_string"):
        return "(无数据)" if len(result) == 0 else result.to_string(index=False)
    if isinstance(result, (list, tuple)):
        if not result:
            return "(无数据)"
        return "\n".join(str(item) for item in result)
    return str(result)


def cmd_quote(quote_client, args) -> None:
    # get_briefs 返回对象列表且官方标记为不推荐，get_stock_briefs 返回 DataFrame。
    briefs = quote_client.get_stock_briefs(args.symbols, include_hour_trading=True)
    print(_render(briefs))


def cmd_expirations(quote_client, args) -> None:
    expirations = quote_client.get_option_expirations(symbols=[args.symbol])
    print(_render(expirations))


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
    print(_render(chain[keep].sort_values("strike")))


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

    width = abs(args.short - args.long)
    multiplier = 100 * args.qty

    print(f"\n{args.symbol}  {args.expiry}  {args.long}/{args.short} {args.side.upper()} 垂直价差  ×{args.qty} 组\n")
    print(f"  长腿 {args.long:>7.2f}   bid {long_bid}  ask {long_ask}  中值 {long_mid:.2f}")
    print(f"  短腿 {args.short:>7.2f}   bid {short_bid}  ask {short_ask}  中值 {short_mid:.2f}")
    print(f"\n  价差中值        {spread_mid:.2f}")
    if spread_exit is not None:
        print(f"  保守平仓价      {spread_exit:.2f}   (卖长腿bid / 买短腿ask)")

    if args.cost is None:
        print("\n  未提供 --cost，跳过盈亏计算。")
        return

    max_profit = width - args.cost
    breakeven = args.long + args.cost
    print(f"\n  建仓成本        {args.cost:.2f}   (共 ${args.cost * multiplier:,.0f})")
    print(f"  打平点          {breakeven:.2f}")
    print(f"  最大亏损        {args.cost:.2f}   (共 ${args.cost * multiplier:,.0f})")
    print(f"  最大盈利        {max_profit:.2f}   (共 ${max_profit * multiplier:,.0f})")

    pnl = (spread_mid - args.cost) * multiplier
    captured = (spread_mid - args.cost) / max_profit * 100 if max_profit else 0
    print(f"\n  当前浮动盈亏    ${pnl:,.0f}   (按中值)")
    print(f"  已实现占最大利润 {captured:.1f}%")
    if spread_exit is not None:
        pnl_exit = (spread_exit - args.cost) * multiplier
        print(f"  按保守价平仓    ${pnl_exit:,.0f}")
    print()


def cmd_positions(trade_client, args) -> None:
    positions = trade_client.get_positions(account=args.account)
    if positions is None or len(positions) == 0:
        print("没有持仓。")
        return
    print(_render(positions))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="老虎证券 OpenAPI 只读行情工具（不含任何下单功能）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("permission", help="查看当前行情权限")
    sub.add_parser("grab", help="把行情权限抢占到本设备")

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

    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    creds = load_credentials()
    quote_client, trade_client = build_clients(creds)

    if args.command == "positions":
        if args.account is None:
            args.account = creds.account  # None 时交由 SDK 用配置文件里的默认账户
        cmd_positions(trade_client, args)
    else:
        handler = {
            "permission": cmd_permission,
            "grab": cmd_grab,
            "quote": cmd_quote,
            "expirations": cmd_expirations,
            "chain": cmd_chain,
            "spread": cmd_spread,
        }[args.command]
        handler(quote_client, args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
