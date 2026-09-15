# lucas-first-repo

## sky_to_hdr.py

把自定义天空图转成 Radiance HDR（`.hdr`），用于 UE 的 SkyLight / HDRI Backdrop。

UE 的贴图导入器只把 Radiance `.hdr` 当经纬展开的立方体贴图处理，导入后直接是
`TextureCube`；`.exr` 会变成 `Texture2D`，塞不进 SkyLight 的 Cubemap 槽。
所以这个脚本严格按 UE 的解析要求写文件：`#?RADIANCE` 头、`FORMAT=32-bit_rle_rgbe`、
`-Y 高 +X 宽` 分辨率行、每一行都是新版 RLE 扫描线。

### 安装

```bash
pip install numpy Pillow
```

### 用法

```bash
# 生成一张程序化天空，用来试跑
python sky_to_hdr.py demo --out sky.png

# 单张 2:1 经纬全景图 -> .hdr，顺手补一个太阳盘
python sky_to_hdr.py convert sky.png --out sky.hdr --sun auto --sun-intensity 6000

# 只有天空的环带 / 朝天顶的鱼眼 / 镜面球照片
python sky_to_hdr.py convert band.jpg --projection skyonly --sky-fov 75 --out sky.hdr
python sky_to_hdr.py convert dome.jpg --projection fisheye180 --out sky.hdr
python sky_to_hdr.py convert ball.jpg --projection mirrorball --out sky.hdr

# 曝光括号合并，物理上最正确的做法
python sky_to_hdr.py merge under.jpg mid.jpg over.jpg --ev -2 0 2 --out sky.hdr

# 校验能否被 UE 导入（convert / merge 末尾会自动跑一次）
python sky_to_hdr.py check sky.hdr

# 出预览：曝光扫描 + 立方体六面（核对朝向）
python sky_to_hdr.py preview sky.hdr --out-dir previews --sweep 0 -3 -6 -9 --montage --cube-faces
```

`convert` 会输出峰值亮度、动态范围档数、立体角加权平均色（≈ SkyLight 的环境光量级），
以及和全景图里太阳对齐的平行光 Pitch / Yaw。

单张 8 bit 图里被削顶的信息是真丢了，脚本做的是平滑重建 + 可选的太阳盘注入，
高光的**相对量级由参数指定**；要物理正确就用 `merge` 做曝光括号。拿 4 张真实
HDRI 当基准真值实测过：晴天天空里日面占总能量的 60~78%，8 bit 一削顶就丢掉这么多，
而把能量补回来主要靠太阳盘而不是高光扩展。默认参数按这组真值标定，
总能量还原到真值的 0.78~1.30 倍。

完整的参数说明、UE 导入步骤、朝向对不上时怎么调、常见问题排查都在
[docs/sky_to_hdr_ue.md](docs/sky_to_hdr_ue.md)。

### 测试

```bash
pip install pytest opencv-python-headless
python -m pytest test_sky_to_hdr.py -v
```

测试全程离线，不需要 UE。其中一条用例拿 OpenCV 的 Radiance 解码器和本工具的
解码器逐位比对，确认输出文件对第三方标准解码器合法；装了 OpenCV 才会跑这条，
没装就自动跳过。

`validate_against_real_hdri.py` 是另一层验证：拿一张真实 HDRI 当基准真值，
把它压成 8 bit 再重建，定量对比能量还原和太阳定位。它需要外部素材，
所以不在离线测试套件里：

```bash
curl -O https://dl.polyhaven.org/file/ph-assets/HDRIs/hdr/1k/kloofendal_43d_clear_1k.hdr
python validate_against_real_hdri.py kloofendal_43d_clear_1k.hdr --out-dir out
```

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
