# 自定义天空 → 高动态范围 HDR → 导入 UE

这份文档讲怎么用 `sky_to_hdr.py` 把一张自定义天空图转成 Radiance `.hdr`，
以及在 UE 里怎么导入、用哪些设置、朝向对不上时怎么调。

为什么一定是 `.hdr` 而不是 `.exr`：UE 的贴图导入器只把 Radiance `.hdr`
当成经纬展开的立方体贴图（Long-Lat Cubemap）来处理，导入后直接得到
`TextureCube` 资产，可以塞进 SkyLight 的 Cubemap 槽和 HDRI Backdrop。
`.exr` 会被导入成普通的 `Texture2D`，只能拿去做天空球材质，
SkyLight 的 Cubemap 槽是不收的。

---

## 一、先确认你的源图是什么形态

| 源图形态 | `--projection` | 说明 |
| --- | --- | --- |
| 2:1 的 360°×180° 经纬全景图 | `equirect`（默认） | 最理想的输入 |
| 只有天空、没有地面的 360° 环带 | `skyonly` | 垂直方向覆盖角度用 `--sky-fov` 指定，地平线以下自动补地面色 |
| 朝天顶拍的圆形鱼眼 | `fisheye180` | 视场角用 `--fisheye-fov` 指定，等距（equidistant）鱼眼 |
| 铬球 / 镜面球照片 | `mirrorball` | 球心是相机背后，球边缘是相机正前方 |
| 同一机位的多张不同曝光 | 用 `merge` 子命令 | 这是唯一能拿到真实动态范围的路子 |

方向约定（和 UE 一样 Z 轴向上）：

- 图片行从上到下 = 天顶 → 天底
- 图片列从左到右 = 方位角 −180° → +180°，**正中间那一列朝 +X**
- 方位角绕 +Z 逆时针增大，仰角 +90° 是天顶

---

## 二、转换

```bash
# 最常见的情况：一张 2:1 的天空全景图
python sky_to_hdr.py convert my_sky.png --out my_sky.hdr

# 顺手补一个太阳盘，让 SkyLight 能拿到明确的方向性光照
python sky_to_hdr.py convert my_sky.png --out my_sky.hdr \
    --sun auto --sun-radius 1.5 --sun-intensity 6000

# 只有天空、没有地面的图
python sky_to_hdr.py convert sky_band.jpg --projection skyonly --sky-fov 75 --out sky.hdr

# 鱼眼 / 镜面球
python sky_to_hdr.py convert dome.jpg --projection fisheye180 --out sky.hdr
python sky_to_hdr.py convert chrome_ball.jpg --projection mirrorball --out sky.hdr

# 手机/相机的曝光括号，物理上最正确
python sky_to_hdr.py merge under.jpg mid.jpg over.jpg --ev -2 0 2 --out sky.hdr

# 输出尺寸、朝向
python sky_to_hdr.py convert my_sky.png --out sky.hdr --size 4096x2048 --rotate-yaw 90
```

### 单张 LDR 能「变成」HDR 到什么程度

要说清楚：**一张 8 bit 图里被削顶（clip 到 255）的那部分信息是真的丢了**，
任何工具都只能重建一个看起来合理的近似值。这个脚本做的是：

1. 用 sRGB 反传递函数把像素变回线性光——这一步是无损、可逆的；
2. 亮度超过 `--knee` 的区域按 `t^power` 平滑抬升，`t=1`（完全削顶）处抬到 `--peak`。
   曲线在 knee 处一阶导为 0，所以不会出现台阶或色带，增益是乘在 RGB 上的，色相不变；
3. 可选地在指定方向叠一个太阳盘（`--sun`），这才是 SkyLight 和平行光真正需要的
   那个几千倍量级的高光。

也就是说，太阳和云隙高光的**相对量级是你指定的**，不是从图里测出来的。
想要物理正确的量级，用 `merge` 做曝光括号合并，或者干脆从渲染器直接输出 HDR。

常用参数的调法：

| 参数 | 默认 | 什么时候调 |
| --- | --- | --- |
| `--knee` | 0.75 | 云层灰蒙蒙的话调高到 0.85，避免整片云都被抬亮 |
| `--peak` | 48 | 只是想要柔和天光就降到 10~20；要强反差就上 100+ |
| `--expand-power` | 3 | 调大 → 只有最亮的核心被抬起来 |
| `--sun-intensity` | 4000 | 直接决定平行光/高光反射的强度量级 |
| `--sun-radius` | 1.5 | 真实太阳的角半径约 0.27°；调大会让高光反射更软 |
| `--output-ev` | 0 | 整体亮度不合适时整体加减曝光档数 |

### 输出尺寸

默认把输出宽度对齐到最接近的 2 的幂并保持 2:1（比如源图 3000 宽 → 4096×2048），
因为 UE 由经纬图生成立方体面时，2:1 + 2 的幂是最省事、不触发警告的组合。
用 `--size` 可以指定，`--no-pot` 可以关掉对齐。4096×2048 一般够用，
8192 宽的文件会显著拖慢导入并吃显存。

---

## 三、导入前先自检

```bash
python sky_to_hdr.py check my_sky.hdr
```

`convert` / `merge` 结束时会自动跑一遍同样的检查。它按 UE 的 `.hdr`
解析要求逐条核对：

- 文件以 `#?RADIANCE` 开头
- 头里有 `FORMAT=32-bit_rle_rgbe`
- 分辨率行是 `-Y 高 +X 宽` 这种朝向（UE 不接受别的排列）
- **每一行**都是新版 RLE 扫描线（以 `0x02 0x02 宽高字节` 开头），宽度落在 [8, 32767]

另外会给出警告：不是 2:1、不是 2 的幂、尺寸过大、内容其实还是 LDR
（最大亮度 ≤ 1.0，这种图导进去 SkyLight 拿不到任何高光信息）。

统计里最值得看的是 `动态范围档数`：LDR 图撑死 8 档，正常的天空 HDR 会在
12~20 档。还有 `立体角加权平均色`，它约等于 SkyLight 会给场景的环境光量级。

想直观确认，出一组预览图：

```bash
python sky_to_hdr.py preview my_sky.hdr --out-dir previews --sweep 0 -3 -6 -9 --montage --cube-faces
```

曝光每降 3 档，天空会明显变暗而日面依旧亮着——这就是动态范围真的存在的证据。
`--cube-faces` 会输出立方体六个面，用来核对朝向：`+Z` 应该是天顶，`-Z` 是地面，
四个侧面的地平线应该都在画面正中。

---

## 四、在 UE 里导入

1. 把 `.hdr` 拖进 Content Browser，应该直接得到一个 **`TextureCube`** 资产。
2. 如果拿到的是 `Texture2D`，说明这个项目没把 `.hdr` 当经纬立方体贴图：
   - UE 5 的 Interchange 路径：Project Settings → Interchange → Content Import Settings
     → Pipeline Stacks → Textures → DefaultTexturePipeline → *File Extensions to Import
     as Long Lat cubemap*，确认里面有 `hdr`；
   - 旧的导入路径：`Config/DefaultEditor.ini` 里加
     ```ini
     [TextureImporter]
     LoadHdrAsLongLatCubemap=1
     ```
3. 双击贴图，确认这几项：

| 设置 | 值 | 为什么 |
| --- | --- | --- |
| sRGB | **不勾** | 文件里存的是线性光，再套一次 sRGB 会把亮度关系全弄错 |
| Compression Settings | `HDR (RGB, no alpha)`，显存紧就用 `HDR Compressed (BC6H)` | 保住浮点范围；用 DXT 之类会直接把高光压没 |
| Maximum Texture Size | 0（不限）或 4096 | 控制显存 |
| Mip Gen Settings | 默认 | SkyLight 的漫反射卷积需要 mip |

---

## 五、三种用法

### 1. HDRI Backdrop（既当背景又当光源）

需要先启用插件：Edit → Plugins 搜 `HDRI Backdrop`，勾上重启编辑器。
然后从 Place Actors 拖一个 HDRI Backdrop 进关卡，把 Cubemap 设成你的贴图。
`Intensity` 调亮度，`Size` 让地面投影正好套住场景，`Rotation` 转朝向。

### 2. SkyLight（只要光，不要背景）

放一个 SkyLight，`Source Type` 设为 **SLS Specified Cubemap**，
Cubemap 指向你的贴图，**Real Time Capture 要关掉**（那个模式捕捉的是场景里的天空，
不是你指定的立方体贴图）。改完点 Recapture。`Intensity Scale` 从 1.0 起调。

### 3. 自己写天空球材质（要美术可控性时）

材质里用 `TextureSampleParameterCube` 采样，UV 接 `ReflectionVector`，
Shading Model 设 Unlit、双面，输出接 Emissive Color。

---

## 六、配一盏平行光

SkyLight 给的是软的环境光，**投不出清晰的阴影**。要阴影就得再加一盏平行光，
方向跟全景图里的太阳对上。`convert` 结束时会直接把角度算好：

```
最亮方向: 方位角 35.0 度，仰角 24.7 度
配套平行光旋转: Pitch -24.7  Yaw -145.0
```

把 Pitch / Yaw 填进平行光的 Rotation 即可（平行光的朝向是光线传播方向，
所以方位角要转 180°、仰角取负，脚本已经换算过了）。

如果你在 UE 里用 HDRI Backdrop 的 Rotation 或 SkyLight 转了全景图的朝向，
记得给这里的 Yaw 加上同样的角度。

---

## 七、朝向对不上怎么办

脚本的约定是「图片正中间那一列朝 +X」，UE 的经纬展开有它自己的起始方位角，
两者不一定重合。垂直方向是确定的（上就是天顶），水平方向差一个常数偏移，
处理办法二选一：

- 在 UE 里转：HDRI Backdrop 的 `Rotation`，或天空球 Actor 的 Yaw；
- 在源头转：`--rotate-yaw 90` 之类，重新导出一次。

先看着 `--cube-faces` 出的六面图确认天顶/地面没颠倒，再调水平朝向，效率最高。

---

## 八、常见问题

| 现象 | 原因 / 处理 |
| --- | --- |
| 导入后是 Texture2D，不是 TextureCube | 见第四节第 2 条的 Interchange / ini 设置 |
| SkyLight 的 Cubemap 槽拖不进去 | 槽只收 `TextureCube`；`.exr`、`.jpg` 导入的是 `Texture2D` |
| 天空发灰、对比度全无 | 贴图的 sRGB 没关，或 Compression 不是 HDR |
| 场景整体过暗/过亮 | 调 SkyLight 的 `Intensity Scale` 或 HDRI Backdrop 的 `Intensity`，不用重新导出 |
| 有环境光但没有清晰阴影 | 正常，SkyLight 不投硬阴影，按第六节加平行光 |
| 太阳位置和阴影方向不一致 | 平行光的 Yaw 没有跟着全景图的旋转一起改 |
| 左右接缝有条缝 | 源图本身不是无缝循环的全景图；`equirect` 采样是横向循环的，缝在源图里 |
| 天顶附近拉花 | 经纬图在极点的固有拉伸；源图分辨率不够时更明显 |
| 导入很慢 / 显存吃紧 | 用 `--size 4096x2048`，或把 Compression 换成 BC6H |

---

## 九、这套流程验证到什么程度

已经验证的：

- 写出的字节流通过了按 UE `.hdr` 解析要求逐条实现的检查（魔术字、FORMAT 行、
  分辨率行朝向、每行都是新版 RLE）；
- OpenCV 的 Radiance 解码器读出来的浮点数据与本工具的解码器**逐位一致**，
  说明文件对第三方标准解码器是合法的；
- RGBE 编解码、RLE（含长重复段、噪声行、边界宽度）、投影映射、
  高光扩展、太阳注入的能量与方向、多曝光合并的还原精度都有单元测试覆盖。

没有验证的：**没有在 UE 编辑器里实际跑过一次导入**（这个环境里没有 UE）。
第四、五节的设置项来自 UE 的公开文档与社区实践，属于操作指引，不是本仓库测过的结论。
