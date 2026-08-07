# lucas-first-repo

## tiger_options.py

老虎证券 OpenAPI 的只读行情工具，用来拉实时报价、期权链，并给垂直价差做估值。

脚本里没有任何下单、撤单、改单的调用，只用 `QuoteClient` 的行情接口和 `TradeClient.get_positions`。

### 安装

```bash
pip install tigeropen
```

### 配置

**前提**：已完成老虎证券开户并入金。OpenAPI 本身免费，但 **API 行情权限独立于 APP，需要单独购买**——APP 里能看期权报价不代表 API 能拉到。

**第一步：拿凭证**

登录[开发者中心](https://developer.itigerup.com/profile)，页面上直接显示 Tiger ID。点「生成密钥」生成 RSA 密钥对，下载 `tiger_openapi_config.properties`。

私钥**不会保存在老虎服务端**，页面刷新后就消失，务必当场存好。丢了只能点「重新生成」换一对。

账户号格式：

| 账户类型 | 格式 | 示例 |
|---|---|---|
| 综合账号 | 8 位数字 | `51230321` |
| 环球账号 | U 开头 | `U12300123` |
| 模拟账号 | 17 位数字 | `20191106192858300` |

也可以在老虎 APP「我的 → 账户管理」里查。**建议先用模拟账号跑通再换实盘。**

**第二步：设环境变量**

方式一（推荐），用下载的配置文件：

```bash
mkdir -p ~/.tiger && chmod 700 ~/.tiger
# 把 tiger_openapi_config.properties 放进 ~/.tiger/
echo 'export TIGER_PROPS_PATH=~/.tiger' >> ~/.zshrc && source ~/.zshrc
```

方式二，手动指定：

```bash
export TIGER_ID=你的tiger_id
export TIGER_ACCOUNT=你的账户号
export TIGER_PRIVATE_KEY_PATH=~/.tiger/rsa_private_key.pem
export TIGER_LICENSE=TBSG   # 可选
```

私钥推荐 **PKCS#8** 格式（文件头 `-----BEGIN PRIVATE KEY-----`）。如果拿到的是 PKCS#1（文件头 `-----BEGIN RSA PRIVATE KEY-----`）：

```bash
openssl pkcs8 -topk8 -inform PEM -in private_pkcs1.pem -outform PEM -nocrypt -out private_pkcs8.pem
chmod 600 ~/.tiger/*.pem
```

**第三步：抢占行情权限**

订阅了行情**还不够**。老虎的行情权限同一时间只在**一个设备**上生效，默认被 APP 占着。要先把它抢到 API 这边：

```bash
python tiger_options.py permission   # 先看现在有什么权限
python tiger_options.py grab         # 抢占到本设备
```

抢占后 APP 端的行情会失效；在 APP 里重新看行情又会把权限抢回去，那时 API 就又报 permission denied。**两边来回抢，同一时间只有一个能用。**

`permission` 输出示例：

```
权限名                              到期时间
--------------------------------------------------------
usQuoteBasic                     2026-08-29 10:40:00
usOptionQuote                    2026-08-29 10:40:00
hkStockQuoteLv2                  长期有效

  美股股票行情 (usQuoteBasic):  有
  美股期权行情 (usOptionQuote): 有
```

拉美股报价需要 `usQuoteBasic`，拉期权链需要 `usOptionQuote`。

**第四步：验证**

```bash
python tiger_options.py quote SPCX
```

常见报错：

| 报错 | 原因 |
|---|---|
| `tigerId ... is illegal` | Tiger ID 填错，或有多余空格换行 |
| `public key error` (code=1000) | tiger_id 没正确传到服务端 |
| `Could not deserialize key data` | 私钥格式不对，转成 PKCS#8 |
| `permission denied(... US market)` | 行情权限没抢到本设备，跑 `grab`；若 `permission` 显示无权限则是没订阅 |
| 期权链返回空 | 缺 `usOptionQuote`，需单独订阅美股期权行情 |

私钥只留本机，`.gitignore` 已排除 `*.pem` 和 `.env`。

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
