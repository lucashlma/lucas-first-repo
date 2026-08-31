# lucas-first-repo

## tiger_options.py

老虎证券 OpenAPI 的只读行情工具，用来拉实时报价、期权链，并给垂直价差做估值。

脚本里没有任何下单、撤单、改单的调用，只用 `QuoteClient` 的行情接口和 `TradeClient.get_positions`。

### 安装

```bash
pip install tigeropen
```

### 配置

先在老虎的开放平台申请 OpenAPI 权限，生成 RSA 密钥对并上传公钥，然后把凭证放进环境变量。私钥只留在本机，不要提交进仓库。

```bash
export TIGER_ID=your_tiger_id
export TIGER_ACCOUNT=your_account
export TIGER_PRIVATE_KEY_PATH=~/.tiger/rsa_private_key.pem
```

### 用法

```bash
# 股票实时报价
python tiger_options.py quote AAOI SPCX

# 可用到期日
python tiger_options.py expirations AAOI

# 期权链，可按行权价区间过滤
python tiger_options.py chain AAOI --expiry 2026-08-21 --min-strike 120 --max-strike 180

# 垂直价差实时估值 + 对照建仓成本算盈亏
python tiger_options.py spread AAOI --expiry 2026-08-21 --long 133 --short 170 --qty 8 --cost 10.65

# 卖出看跌价差用 --side PUT，--cost 填负数表示收权利金
python tiger_options.py spread SPCX --expiry 2026-09-18 --long 90 --short 100 --side PUT --cost -3.1

# AVGO 财报 debit call spread 实时估值
python tiger_options.py spread AVGO --expiry 2026-09-18 --long 370 --short 420 --cost 13.35

# 已记录仓位的到期结构（不连行情）
python tiger_options.py journal

# 当前持仓
python tiger_options.py positions
```

`spread` 会输出两个价差价格：**中值**（买卖中间价，理论估值）和**保守平仓价**（卖长腿走 bid、买短腿走 ask，即实际能成交的不利一侧）。挂单时参考后者更贴近现实。

### 测试

```bash
pip install pytest
python -m pytest test_tiger_options.py -v
```

测试用假的期权链离线跑，不需要 API 凭证，也不会发出任何网络请求。

## 交易日志

当前开放仓位写在 `trades/open.json`。笔记：

- [AVGO 期权 · 赌财报（370/420 debit call spread）](docs/avgo-earnings-call-spread.md)
