#!/usr/bin/env python3
"""把自定义天空图转成 Radiance HDR(.hdr)，用于 UE 的 SkyLight / HDRIBackdrop。

写出来的 .hdr 严格按 UE 的 .hdr 解析器要求来：`#?RADIANCE` 头 +
`FORMAT=32-bit_rle_rgbe` + `-Y 高 +X 宽` 分辨率行 + 新版 RLE 扫描线
（每行以 0x02 0x02 宽高字节开头），因此宽度必须落在 [8, 32767]。

方向约定（和 UE 一致的 Z 轴向上）：
    图片行 从上到下 = 天顶 -> 天底（theta 0 -> 180 度）
    图片列 从左到右 = 方位角 -180 -> 180 度，正中间那一列朝 +X
    方位角绕 +Z 逆时针增大，仰角 90 度为天顶

用法：
    python sky_to_hdr.py demo --out sky.png
    python sky_to_hdr.py convert sky.png --out sky.hdr
    python sky_to_hdr.py convert sky.png --out sky.hdr --sun auto
    python sky_to_hdr.py convert dome.jpg --projection fisheye180 --out sky.hdr
    python sky_to_hdr.py merge under.jpg mid.jpg over.jpg --ev -2 0 2 --out sky.hdr
    python sky_to_hdr.py check sky.hdr
    python sky_to_hdr.py preview sky.hdr --out-dir previews --sweep 0 -3 -6 -9
"""

from __future__ import annotations

import argparse
import math
import os
import sys
from dataclasses import dataclass, field

import numpy as np

RADIANCE_MAGIC = b"#?RADIANCE"
RGBE_MAGIC = b"#?RGBE"
FORMAT_LINE = "FORMAT=32-bit_rle_rgbe"

# 新版 RLE 扫描线只能表示这个宽度区间，UE 的解析器也是照这个来的。
MIN_RLE_WIDTH = 8
MAX_RLE_WIDTH = 0x7FFF

# 低于这个值直接写成 RGBE 全零，避免指数下溢。
MIN_RADIANCE = 1e-32

LUMA = np.array([0.2126, 0.7152, 0.0722], dtype=np.float64)

# 4K/8K 全景图上，一次性铺开 float64 中间结果动辄上 G，所以按行块算。
CHUNK_ROWS = 128

PROJECTIONS = ("equirect", "skyonly", "fisheye180", "mirrorball")


# --------------------------------------------------------------------------
# 分块处理的公用件
# --------------------------------------------------------------------------
def luminance(image: np.ndarray, chunk_rows: int = CHUNK_ROWS) -> np.ndarray:
    """按行块算亮度，返回 float32。"""
    image = np.asarray(image)
    if image.ndim != 3 or image.shape[2] != 3:
        raise ValueError(f"需要 (高, 宽, 3) 的图像，收到 {image.shape}")
    out = np.empty(image.shape[:2], dtype=np.float32)
    luma = LUMA.astype(np.float32)
    for row0 in range(0, image.shape[0], chunk_rows):
        out[row0 : row0 + chunk_rows] = image[row0 : row0 + chunk_rows] @ luma
    return out


def map_rows(image: np.ndarray, fn, dtype=np.float32) -> np.ndarray:
    """按行块套用逐像素函数，把中间结果的峰值内存压到一块的量级。"""
    image = np.asarray(image)
    out = np.empty(image.shape, dtype=dtype)
    for row0 in range(0, image.shape[0], CHUNK_ROWS):
        out[row0 : row0 + CHUNK_ROWS] = fn(image[row0 : row0 + CHUNK_ROWS])
    return out


def sanitize_linear(image: np.ndarray) -> np.ndarray:
    """就地把 NaN/Inf/负值清掉。大图上另开两份拷贝要多吃几百 MB。"""
    largest = float(np.finfo(np.float32).max)
    for row0 in range(0, image.shape[0], CHUNK_ROWS):
        block = image[row0 : row0 + CHUNK_ROWS]
        np.nan_to_num(block, copy=False, nan=0.0, posinf=largest, neginf=0.0)
        np.clip(block, 0.0, None, out=block)
    return image


# --------------------------------------------------------------------------
# Radiance RGBE 编解码
# --------------------------------------------------------------------------
def float_to_rgbe(rgb: np.ndarray) -> np.ndarray:
    """线性 float RGB -> 打包的 RGBE 字节，(..., 3) -> (..., 4)。"""
    rgb = np.asarray(rgb, dtype=np.float64)
    if rgb.shape[-1] != 3:
        raise ValueError(f"需要 (..., 3) 的 RGB 数组，收到 {rgb.shape}")
    rgb = np.nan_to_num(rgb, nan=0.0, posinf=np.finfo(np.float32).max, neginf=0.0)
    rgb = np.clip(rgb, 0.0, np.finfo(np.float32).max)

    peak = rgb.max(axis=-1)
    out = np.zeros(rgb.shape[:-1] + (4,), dtype=np.uint8)
    live = peak > MIN_RADIANCE
    if not np.any(live):
        return out

    _, exponent = np.frexp(peak)  # peak = 尾数 * 2**exponent，尾数属于 [0.5, 1)
    # 指数字节是 exponent + 128，夹到 [1, 255] 保证字节合法。
    exponent = np.clip(np.where(live, exponent, 0), -127, 127)
    scale = np.ldexp(np.ones_like(peak), 8 - exponent)
    # 最大通道算出来是 尾数*256 < 256，所以向下取整不会溢出。
    mantissa = np.clip(np.floor(rgb * scale[..., None]), 0.0, 255.0)

    out[..., :3] = mantissa.astype(np.uint8)
    out[..., 3] = (exponent + 128).astype(np.uint8)
    out[~live] = 0
    return out


def rgbe_to_float(rgbe: np.ndarray) -> np.ndarray:
    """打包的 RGBE 字节 -> 线性 float RGB，和 UE / OpenCV 的解码方式一致。"""
    rgbe = np.asarray(rgbe)
    if rgbe.shape[-1] != 4:
        raise ValueError(f"需要 (..., 4) 的 RGBE 数组，收到 {rgbe.shape}")
    exponent = rgbe[..., 3].astype(np.int32)
    scale = np.where(exponent == 0, 0.0, np.ldexp(1.0, exponent - (128 + 8)))
    return (rgbe[..., :3].astype(np.float32) * scale[..., None].astype(np.float32)).astype(np.float32)


def _encode_literal_only(values: np.ndarray) -> bytearray:
    """全部按字面块编码。新版 RLE 允许纯字面块，成本是每 128 字节多 1 个头字节。"""
    out = bytearray()
    for start in range(0, values.size, 128):
        chunk = values[start : start + 128]
        out.append(chunk.size)
        out += chunk.tobytes()
    return out


def _encode_channel(values: np.ndarray) -> bytearray:
    """单通道扫描线 -> 新版 RLE 字节流。"""
    width = values.size
    starts = np.concatenate(([0], np.flatnonzero(values[1:] != values[:-1]) + 1))
    # 细节多的行几乎没有可用的重复段，直接走向量化的字面块路径更快。
    if starts.size > max(16, width // 8):
        return _encode_literal_only(values)

    lengths = np.diff(np.concatenate((starts, [width])))
    out = bytearray()
    literal = bytearray()

    def flush_literal() -> None:
        for start in range(0, len(literal), 128):
            chunk = literal[start : start + 128]
            out.append(len(chunk))
            out.extend(chunk)
        literal.clear()

    for start, length in zip(starts.tolist(), lengths.tolist()):
        if length >= 4:
            flush_literal()
            value = int(values[start])
            while length > 0:
                run = min(length, 127)
                out += bytes((128 + run, value))
                length -= run
        else:
            literal += values[start : start + length].tobytes()
            if len(literal) >= 128:
                head, literal[:] = literal[:128], literal[128:]
                out.append(128)
                out += head
    flush_literal()
    return out


def _encode_scanline(rgbe_row: np.ndarray) -> bytearray:
    """一行 RGBE -> 新版 RLE 扫描线（含 0x02 0x02 宽度头）。"""
    width = rgbe_row.shape[0]
    out = bytearray((2, 2, (width >> 8) & 0xFF, width & 0xFF))
    for channel in range(4):
        out += _encode_channel(np.ascontiguousarray(rgbe_row[:, channel]))
    return out


def write_hdr(path: str, rgb: np.ndarray, rle: bool = True, comment: str | None = None) -> None:
    """把线性 float RGB 写成 Radiance .hdr。"""
    rgb = np.asarray(rgb)
    if rgb.ndim != 3 or rgb.shape[2] != 3:
        raise ValueError(f"需要 (高, 宽, 3) 的图像，收到 {rgb.shape}")
    height, width = rgb.shape[:2]
    if width < 1 or height < 1:
        raise ValueError("图像尺寸必须为正")

    use_rle = rle and MIN_RLE_WIDTH <= width <= MAX_RLE_WIDTH

    # 头部按 ASCII 写，非 ASCII 注释会被替换掉：Radiance 头是字节流，
    # UE 那边按单字节字符读，塞多字节字符有解析出错的风险。
    note = (comment or "made with sky_to_hdr.py").encode("ascii", "replace").decode("ascii")
    header = [
        RADIANCE_MAGIC.decode(),
        f"# {note}",
        FORMAT_LINE,
        "EXPOSURE=1.0",
        "",
        f"-Y {height} +X {width}",
    ]

    with open(path, "wb") as fh:
        fh.write(("\n".join(header) + "\n").encode("ascii"))
        # 分块转换，避免整幅图的 float64 中间结果占满内存。
        for row0 in range(0, height, 64):
            block = float_to_rgbe(rgb[row0 : row0 + 64])
            if use_rle:
                fh.writelines(bytes(_encode_scanline(row)) for row in block)
            else:
                fh.write(np.ascontiguousarray(block).tobytes())


def _read_header(data: bytes) -> tuple[dict, int]:
    if data.startswith(RADIANCE_MAGIC):
        magic = RADIANCE_MAGIC.decode()
    elif data.startswith(RGBE_MAGIC):
        magic = RGBE_MAGIC.decode()
    else:
        raise ValueError("不是 Radiance HDR 文件：缺少 #?RADIANCE 魔术字")

    pos = data.index(b"\n") + 1
    info = {"magic": magic, "format": None, "exposure": None, "lines": []}
    while True:
        end = data.find(b"\n", pos)
        if end < 0:
            raise ValueError("HDR 头部不完整")
        line = data[pos:end].decode("latin-1").strip()
        pos = end + 1
        if not line:
            break
        info["lines"].append(line)
        if line.startswith("FORMAT="):
            info["format"] = line
        elif line.startswith("EXPOSURE="):
            try:
                info["exposure"] = float(line.split("=", 1)[1])
            except ValueError:
                pass

    end = data.find(b"\n", pos)
    if end < 0:
        raise ValueError("HDR 缺少分辨率行")
    resolution = data[pos:end].decode("latin-1").strip()
    pos = end + 1
    info["resolution"] = resolution

    parts = resolution.split()
    if len(parts) != 4 or parts[0] != "-Y" or parts[2] != "+X":
        raise ValueError(f"分辨率行不是 UE 支持的 '-Y 高 +X 宽' 形式: {resolution!r}")
    info["height"] = int(parts[1])
    info["width"] = int(parts[3])
    if info["height"] <= 0 or info["width"] <= 0:
        raise ValueError(f"分辨率非法: {resolution!r}")
    return info, pos


def _read_rgbe(path: str) -> tuple[np.ndarray, dict]:
    with open(path, "rb") as fh:
        data = fh.read()
    info, pos = _read_header(data)
    width, height = info["width"], info["height"]

    rgbe = np.zeros((height, width, 4), dtype=np.uint8)
    rle_rows = 0
    for y in range(height):
        head = data[pos : pos + 4]
        if (
            len(head) == 4
            and head[0] == 2
            and head[1] == 2
            and ((head[2] << 8) | head[3]) == width
            and MIN_RLE_WIDTH <= width <= MAX_RLE_WIDTH
        ):
            rle_rows += 1
            pos += 4
            for channel in range(4):
                x = 0
                while x < width:
                    if pos >= len(data):
                        raise ValueError(f"第 {y} 行数据被截断")
                    code = data[pos]
                    pos += 1
                    if code == 0:
                        raise ValueError(f"第 {y} 行出现非法的 0 计数")
                    if code > 128:
                        run = code - 128
                        if x + run > width:
                            raise ValueError(f"第 {y} 行的重复段越过行宽")
                        rgbe[y, x : x + run, channel] = data[pos]
                        pos += 1
                        x += run
                    else:
                        if x + code > width:
                            raise ValueError(f"第 {y} 行的字面段越过行宽")
                        rgbe[y, x : x + code, channel] = np.frombuffer(data, np.uint8, code, pos)
                        pos += code
                        x += code
        else:
            if head[:3] == b"\x01\x01\x01":
                raise ValueError("旧版 RLE(0x01 重复码) 不支持，请用新版 RLE 重新导出")
            need = width * 4
            if pos + need > len(data):
                raise ValueError(f"第 {y} 行数据被截断")
            rgbe[y] = np.frombuffer(data, np.uint8, need, pos).reshape(width, 4)
            pos += need

    info["rle_rows"] = rle_rows
    info["trailing_bytes"] = len(data) - pos
    info["file_size"] = len(data)
    return rgbe, info


def read_hdr(path: str) -> np.ndarray:
    """读 Radiance .hdr -> 线性 float RGB。"""
    rgbe, _ = _read_rgbe(path)
    return rgbe_to_float(rgbe)


# --------------------------------------------------------------------------
# UE 导入兼容性检查
# --------------------------------------------------------------------------
@dataclass
class CheckResult:
    path: str
    width: int = 0
    height: int = 0
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    stats: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.errors


def _is_pot(value: int) -> bool:
    return value > 0 and (value & (value - 1)) == 0


def check_hdr_for_ue(path: str) -> CheckResult:
    """按 UE 的 .hdr 导入要求校验文件，返回错误与警告清单。"""
    result = CheckResult(path=path)
    try:
        rgbe, info = _read_rgbe(path)
    except Exception as exc:  # noqa: BLE001 - 不管什么原因解析不了，对 UE 都是导入失败
        result.errors.append(str(exc))
        return result

    result.width, result.height = info["width"], info["height"]

    if info["magic"] != RADIANCE_MAGIC.decode():
        result.warnings.append(f"魔术字是 {info['magic']}，UE 上最稳的是 #?RADIANCE")
    if info["format"] != FORMAT_LINE:
        result.errors.append(f"FORMAT 行必须是 {FORMAT_LINE!r}，实际是 {info['format']!r}")
    if info["rle_rows"] != result.height:
        result.errors.append(
            f"只有 {info['rle_rows']}/{result.height} 行是新版 RLE 扫描线；"
            "UE 的解析器要求每行都以 0x02 0x02 开头"
        )
    if not (MIN_RLE_WIDTH <= result.width <= MAX_RLE_WIDTH):
        result.errors.append(f"宽度 {result.width} 超出新版 RLE 能表示的 [8, 32767]")
    if info["exposure"] not in (None, 1.0):
        result.warnings.append(
            f"EXPOSURE={info['exposure']}，UE 会忽略它，建议把曝光烘进像素值并写 1.0"
        )
    if info["trailing_bytes"] > 0:
        result.warnings.append(f"像素数据后还有 {info['trailing_bytes']} 字节多余内容")

    if result.width != result.height * 2:
        result.warnings.append(
            f"{result.width}x{result.height} 不是 2:1，UE 需要 2:1 的经纬展开图才能当立方体贴图"
        )
    if not (_is_pot(result.width) and _is_pot(result.height)):
        result.warnings.append(f"{result.width}x{result.height} 不是 2 的幂，UE 会提示非 POT 贴图")
    if result.width > 8192:
        result.warnings.append(f"宽度 {result.width} 偏大，UE 导入会很慢且占显存，一般 4096 够用")

    # 分块解码算亮度，避免为了统计再铺开一整幅浮点图。
    lum = np.empty(rgbe.shape[:2], dtype=np.float32)
    for row0 in range(0, rgbe.shape[0], CHUNK_ROWS):
        lum[row0 : row0 + CHUNK_ROWS] = luminance(rgbe_to_float(rgbe[row0 : row0 + CHUNK_ROWS]))
    positive = lum[lum > 0]
    result.stats = {
        "文件大小MB": info["file_size"] / (1024 * 1024),
        "最大亮度": float(lum.max()) if lum.size else 0.0,
        "平均亮度": float(lum.mean()) if lum.size else 0.0,
        "中位亮度": float(np.median(positive)) if positive.size else 0.0,
        "动态范围档数": (
            float(np.log2(lum.max() / np.percentile(positive, 5)))
            if positive.size and lum.max() > 0
            else 0.0
        ),
        "超过1.0占比%": float((lum > 1.0).mean() * 100) if lum.size else 0.0,
    }
    if result.stats["最大亮度"] <= 0:
        result.errors.append("整幅图全黑")
    elif result.stats["最大亮度"] <= 1.0:
        result.warnings.append("最大亮度不超过 1.0，其实还是 LDR 的动态范围，SkyLight 拿不到高光信息")
    return result


# --------------------------------------------------------------------------
# 输入输出：LDR 读入 / 传递函数
# --------------------------------------------------------------------------
def srgb_to_linear(x: np.ndarray) -> np.ndarray:
    x = np.asarray(x, dtype=np.float32)
    return np.where(x <= 0.04045, x / 12.92, ((x + 0.055) / 1.055) ** 2.4).astype(np.float32)


def linear_to_srgb(x: np.ndarray) -> np.ndarray:
    x = np.clip(np.asarray(x, dtype=np.float32), 0.0, 1.0)
    return np.where(x <= 0.0031308, x * 12.92, 1.055 * x ** (1 / 2.4) - 0.055).astype(np.float32)


def load_image_linear(path: str, gamma: str = "srgb") -> np.ndarray:
    """读一张图，返回线性光的 (高, 宽, 3) float32。.hdr 输入本来就是线性的。"""
    if path.lower().endswith(".hdr"):
        return read_hdr(path)

    from PIL import Image

    with Image.open(path) as img:
        img.load()
        if img.mode in ("I;16", "I;16B", "I;16L", "I"):
            raw = np.repeat(np.asarray(img)[:, :, None], 3, axis=2)
            full_scale = 65535.0
        else:
            raw = np.asarray(img.convert("RGB"))
            full_scale = 255.0

    if gamma == "srgb":
        return map_rows(raw, lambda block: srgb_to_linear(block / full_scale))
    value = float(gamma)
    if value <= 0:
        raise ValueError("--gamma 必须为正数或 srgb")
    return map_rows(raw, lambda block: np.power(block / full_scale, value, dtype=np.float64))


def save_png(path: str, rgb_srgb: np.ndarray) -> None:
    from PIL import Image

    data = np.clip(np.asarray(rgb_srgb) * 255.0 + 0.5, 0, 255).astype(np.uint8)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    Image.fromarray(data, mode="RGB").save(path)


# --------------------------------------------------------------------------
# 方向与投影
# --------------------------------------------------------------------------
def equirect_directions(width: int, height: int, row0: int = 0, rows: int | None = None,
                        yaw_deg: float = 0.0) -> np.ndarray:
    """经纬图像素 -> 单位方向向量，Z 轴向上，正中间那一列朝 +X。"""
    rows = height if rows is None else rows
    theta = (np.arange(row0, row0 + rows, dtype=np.float64) + 0.5) / height * np.pi
    phi = (np.arange(width, dtype=np.float64) + 0.5) / width * 2 * np.pi - np.pi
    phi = phi - math.radians(yaw_deg)

    sin_t, cos_t = np.sin(theta)[:, None], np.cos(theta)[:, None]
    cos_p, sin_p = np.cos(phi)[None, :], np.sin(phi)[None, :]
    return np.stack(
        [sin_t * cos_p, sin_t * sin_p, np.broadcast_to(cos_t, (rows, width))], axis=-1
    )


def direction_to_azel(direction) -> tuple[float, float]:
    x, y, z = [float(v) for v in direction]
    norm = math.sqrt(x * x + y * y + z * z) or 1.0
    return math.degrees(math.atan2(y, x)), math.degrees(math.asin(max(-1.0, min(1.0, z / norm))))


def azel_to_direction(azimuth_deg: float, elevation_deg: float) -> np.ndarray:
    az, el = math.radians(azimuth_deg), math.radians(elevation_deg)
    return np.array(
        [math.cos(el) * math.cos(az), math.cos(el) * math.sin(az), math.sin(el)], dtype=np.float64
    )


def directions_to_source_uv(dirs: np.ndarray, projection: str,
                            fisheye_fov_deg: float = 180.0,
                            sky_fov_deg: float = 90.0) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """方向向量 -> 源图归一化 uv 以及有效区域掩码。"""
    x, y, z = dirs[..., 0], dirs[..., 1], dirs[..., 2]

    if projection == "equirect":
        u = np.arctan2(y, x) / (2 * np.pi) + 0.5
        v = np.arccos(np.clip(z, -1.0, 1.0)) / np.pi
        return u, v, np.ones(u.shape, dtype=bool)

    if projection == "skyonly":
        # 源图覆盖 360 度方位角，垂直方向只覆盖顶部 sky_fov 度。
        u = np.arctan2(y, x) / (2 * np.pi) + 0.5
        theta = np.degrees(np.arccos(np.clip(z, -1.0, 1.0)))
        v = theta / max(sky_fov_deg, 1e-6)
        return u, np.clip(v, 0.0, 1.0), v <= 1.0

    if projection == "fisheye180":
        # 朝天顶拍的等距鱼眼：图像 +X 轴对世界 +X，图像上方对世界 +Y。
        theta = np.arccos(np.clip(z, -1.0, 1.0))
        radius = theta / math.radians(max(fisheye_fov_deg, 1e-6) / 2.0)
        angle = np.arctan2(y, x)
        u = 0.5 + 0.5 * radius * np.cos(angle)
        v = 0.5 - 0.5 * radius * np.sin(angle)
        return u, v, radius <= 1.0

    if projection == "mirrorball":
        # 相机看向世界 +X，相机空间 (右, 上, 前) = (+Y, +Z, +X)，入射方向 V = (0, 0, 1)。
        # 反射到 R 的那个点，朝向相机的法线是 n = normalize(R - V)，
        # 球面图坐标就取 (n_x, n_y)；代入 |R - V| = sqrt(2(1 - Rz)) 化简后
        # 半径正好是 sqrt((1 + Rz) / 2)：球心映射到相机背后，球边缘是相机正前方。
        rx, ry, rz = y, z, x
        radius = np.sqrt(np.clip((1.0 + rz) * 0.5, 0.0, 1.0))
        angle = np.arctan2(ry, rx)
        u = 0.5 + 0.5 * radius * np.cos(angle)
        v = 0.5 - 0.5 * radius * np.sin(angle)
        return u, v, np.ones(u.shape, dtype=bool)

    raise ValueError(f"未知的投影方式: {projection}")


def sample_bilinear(src: np.ndarray, u: np.ndarray, v: np.ndarray, wrap_x: bool = False) -> np.ndarray:
    """双线性采样，uv 归一化到 [0, 1]。"""
    height, width = src.shape[:2]
    x = np.asarray(u, dtype=np.float64) * width - 0.5
    y = np.asarray(v, dtype=np.float64) * height - 0.5

    x0f, y0f = np.floor(x), np.floor(y)
    fx = (x - x0f)[..., None].astype(np.float32)
    fy = (y - y0f)[..., None].astype(np.float32)
    x0, y0 = x0f.astype(np.int64), y0f.astype(np.int64)
    x1, y1 = x0 + 1, y0 + 1

    if wrap_x:
        x0, x1 = np.mod(x0, width), np.mod(x1, width)
    else:
        x0, x1 = np.clip(x0, 0, width - 1), np.clip(x1, 0, width - 1)
    y0, y1 = np.clip(y0, 0, height - 1), np.clip(y1, 0, height - 1)

    c00, c10 = src[y0, x0], src[y0, x1]
    c01, c11 = src[y1, x0], src[y1, x1]
    top = c00 * (1.0 - fx) + c10 * fx
    bottom = c01 * (1.0 - fx) + c11 * fx
    return (top * (1.0 - fy) + bottom * fy).astype(np.float32)


def reproject_to_equirect(src: np.ndarray, out_width: int, out_height: int,
                          projection: str = "equirect", yaw_deg: float = 0.0,
                          fisheye_fov_deg: float = 180.0, sky_fov_deg: float = 90.0,
                          chunk_rows: int = 128) -> tuple[np.ndarray, np.ndarray]:
    """把任意投影的源图重采样成经纬展开图，返回 (图像, 有效掩码)。"""
    if projection not in PROJECTIONS:
        raise ValueError(f"未知的投影方式: {projection}")

    if (
        projection == "equirect"
        and yaw_deg == 0.0
        and src.shape[0] == out_height
        and src.shape[1] == out_width
    ):
        return src.astype(np.float32, copy=True), np.ones((out_height, out_width), dtype=bool)

    out = np.zeros((out_height, out_width, 3), dtype=np.float32)
    valid = np.zeros((out_height, out_width), dtype=bool)
    wrap_x = projection in ("equirect", "skyonly")

    for row0 in range(0, out_height, chunk_rows):
        rows = min(chunk_rows, out_height - row0)
        dirs = equirect_directions(out_width, out_height, row0, rows, yaw_deg)
        u, v, mask = directions_to_source_uv(dirs, projection, fisheye_fov_deg, sky_fov_deg)
        block = sample_bilinear(src, u, v, wrap_x=wrap_x)
        out[row0 : row0 + rows] = block * mask[..., None]
        valid[row0 : row0 + rows] = mask
    return out, valid


def fill_ground(img: np.ndarray, valid: np.ndarray, albedo: float = 0.25,
                blend_deg: float = 20.0) -> np.ndarray:
    """把地平线以下没有像素的区域补上地面色，避免 SkyLight 采到黑洞。"""
    out = img.copy()
    height = img.shape[0]
    rows_valid = valid.any(axis=1)
    if rows_valid.all() or not rows_valid.any():
        return out

    horizon = int(np.flatnonzero(rows_valid)[-1]) + 1
    edge_rows = img[max(0, horizon - max(1, height // 128)) : horizon]
    horizon_color = edge_rows.reshape(-1, img.shape[1], 3).mean(axis=0)
    ground_color = horizon_color.mean(axis=0) * albedo

    blend_rows = max(1, round(blend_deg / 180.0 * height))
    for row in range(horizon, height):
        weight = min(1.0, (row - horizon + 1) / blend_rows)
        out[row] = horizon_color * (1.0 - weight) + ground_color * weight
    return out


# --------------------------------------------------------------------------
# 动态范围扩展
# --------------------------------------------------------------------------
def expand_highlights(linear: np.ndarray, knee: float = 0.85, peak: float = 16.0,
                      power: float = 3.0) -> np.ndarray:
    """把接近削顶的高光按平滑曲线抬高，恢复出 LDR 里丢掉的动态范围。

    亮度低于 knee 的像素完全不动；knee 以上按 t**power 平滑增益，t=1 时增益为 peak。
    增益是按像素乘在 RGB 上的，所以色相不变。
    """
    if not 0.0 <= knee < 1.0:
        raise ValueError("--knee 必须在 [0, 1) 区间")
    if peak < 1.0:
        raise ValueError("--peak 必须 >= 1")
    if power <= 0:
        raise ValueError("--expand-power 必须为正")

    linear = np.asarray(linear, dtype=np.float32)
    out = np.empty_like(linear)
    for row0 in range(0, linear.shape[0], CHUNK_ROWS):
        block = linear[row0 : row0 + CHUNK_ROWS]
        t = np.clip((luminance(block) - knee) / (1.0 - knee), 0.0, 1.0)
        gain = 1.0 + (peak - 1.0) * np.power(t, power, dtype=np.float32)
        out[row0 : row0 + CHUNK_ROWS] = block * gain[..., None]
    return out


def _brightest_pixel_directions(equirect_linear: np.ndarray, plateau: float,
                                max_samples: int, seed: int = 0):
    """取出「最亮那一档」像素的方向和立体角权重。

    不能按能量找太阳：8 bit 图里日面被削顶到 1.0 往往只占千分之几的像素，
    能量早被大片亮天空盖过去；也不能直接取最亮像素，因为削顶会让一大片并列最亮。
    但「最亮那一档像素」在两种情况下都指向日面：没削顶时只有日面能接近峰值，
    削顶时日面周围那圈光晕就是最大的一块平顶。
    """
    height, width = equirect_linear.shape[:2]
    lum = luminance(equirect_linear)
    if lum.max() <= 0:
        return None, None

    rows, cols = np.nonzero(lum >= lum.max() * plateau)
    if rows.size == 0:
        return None, None
    if rows.size > max_samples:
        picked = np.random.default_rng(seed).choice(rows.size, max_samples, replace=False)
        rows, cols = rows[picked], cols[picked]

    theta = (rows + 0.5) / height * math.pi
    phi = (cols + 0.5) / width * 2 * math.pi - math.pi
    dirs = np.stack(
        [np.sin(theta) * np.cos(phi), np.sin(theta) * np.sin(phi), np.cos(theta)], axis=-1
    )
    # 立体角权重，避免极区那些挤在一起的像素被当成密集团块。
    return dirs, np.sin(theta) * lum[rows, cols].astype(np.float64)


def detect_sun(equirect_linear: np.ndarray, kernel_deg: float = 8.0, plateau: float = 0.98,
               max_samples: int = 4000, iterations: int = 20) -> tuple[float, float]:
    """估计太阳方向，返回 (方位角, 仰角)，单位度。

    对「最亮那一档」像素做核密度估计，取密度最高点当种子，再用同一个核做
    mean shift 收敛到密度峰。核用高斯而不是硬锥有两个好处：削顶形成的平顶
    不会出现一大片并列最大值（硬锥下密度完全相同，argmax 只能任选一个，
    偏差可达核半径），而十几度以外的另一块高亮区权重会被压到 3% 以下，
    不会把重心拽走。

    在 4 张真实 HDRI 模拟出的 8 bit 照片上实测偏差 0.3~0.9 度（阴天那张没有
    明确日面，不适用）。局限：如果图里另有一片同样削顶、面积还更大的高亮区
    （比如过曝的水面），会被判成太阳；这种情况直接用 --sun '方位角,仰角' 指定。
    """
    dirs, weight = _brightest_pixel_directions(equirect_linear, plateau, max_samples)
    if dirs is None or weight.sum() <= 0:
        return 0.0, 45.0

    # 核写成 exp(-(1 - cos) / (1 - cos kernel))，角度越大权重越小，且不用反三角函数。
    scale = 1.0 - math.cos(math.radians(kernel_deg))

    density = np.empty(dirs.shape[0], dtype=np.float64)
    for start in range(0, dirs.shape[0], 512):
        block = dirs[start : start + 512] @ dirs.T
        density[start : start + 512] = np.exp((block - 1.0) / scale) @ weight
    center = dirs[int(np.argmax(density))]

    cos_tolerance = math.cos(math.radians(0.02))
    for _ in range(iterations):
        moved = dirs.T @ (weight * np.exp((dirs @ center - 1.0) / scale))
        norm = np.linalg.norm(moved)
        if norm <= 0:
            break
        moved /= norm
        converged = float(moved @ center) >= cos_tolerance
        center = moved
        if converged:
            break
    return direction_to_azel(center)


def add_sun(equirect_linear: np.ndarray, azimuth_deg: float, elevation_deg: float,
            radius_deg: float = 1.5, intensity: float = 2000.0,
            color=(1.0, 0.97, 0.92), softness: float = 0.35) -> np.ndarray:
    """在指定方向叠一个太阳盘，让 SkyLight 能捕到明确的方向性光照。"""
    if radius_deg <= 0:
        raise ValueError("--sun-radius 必须为正")
    height, width = equirect_linear.shape[:2]
    out = equirect_linear.astype(np.float32, copy=True)
    sun_dir = azel_to_direction(azimuth_deg, elevation_deg)
    color = np.asarray(color, dtype=np.float32)

    outer = math.radians(radius_deg)
    inner = outer * (1.0 - min(max(softness, 0.0), 0.99))
    for row0 in range(0, height, 128):
        rows = min(128, height - row0)
        dirs = equirect_directions(width, height, row0, rows)
        cos_angle = np.clip(dirs @ sun_dir, -1.0, 1.0)
        angle = np.arccos(cos_angle)
        weight = np.clip((outer - angle) / max(outer - inner, 1e-9), 0.0, 1.0)
        weight = weight * weight * (3.0 - 2.0 * weight)  # smoothstep
        out[row0 : row0 + rows] += (
            weight[..., None] * (intensity * color)
        ).astype(np.float32)
    return out


def solid_angle_weighted_mean(equirect: np.ndarray) -> np.ndarray:
    """按立体角加权的平均颜色，等于 SkyLight 拿到的整体环境光强度。"""
    height, width = equirect.shape[:2]
    theta = (np.arange(height) + 0.5) / height * np.pi
    weight = np.sin(theta)
    total = np.zeros(3, dtype=np.float64)
    for row0 in range(0, height, CHUNK_ROWS):
        block = equirect[row0 : row0 + CHUNK_ROWS].astype(np.float64)
        total += (block * weight[row0 : row0 + CHUNK_ROWS, None, None]).sum(axis=(0, 1))
    return total / (weight.sum() * width)


# --------------------------------------------------------------------------
# 多曝光合并
# --------------------------------------------------------------------------
def merge_exposures(images_linear: list[np.ndarray], evs: list[float]) -> np.ndarray:
    """把一组不同曝光的线性图合成一张辐照度图。

    权重用以 0.5 为中心的高斯，两端再乘一个很小的系数压掉过曝/欠曝像素。
    """
    if len(images_linear) != len(evs):
        raise ValueError("图片数量和 --ev 数量不一致")
    if not images_linear:
        raise ValueError("至少需要一张图")
    shape = images_linear[0].shape
    for img in images_linear:
        if img.shape != shape:
            raise ValueError("多曝光合并要求所有输入尺寸一致")

    out = np.empty(shape, dtype=np.float32)
    for row0 in range(0, shape[0], CHUNK_ROWS):
        rows = slice(row0, row0 + CHUNK_ROWS)
        numerator = np.zeros(images_linear[0][rows].shape, dtype=np.float64)
        denominator = np.zeros(numerator.shape[:2] + (1,), dtype=np.float64)
        for img, ev in zip(images_linear, evs):
            block = img[rows]
            display = np.clip(luminance(linear_to_srgb(block)), 0.0, 1.0).astype(np.float64)
            weight = np.exp(-((display - 0.5) ** 2) / (2 * 0.16**2))
            weight = np.where(display > 0.98, weight * 1e-3, weight)
            weight = np.where(display < 0.01, weight * 1e-3, weight)
            weight = np.maximum(weight, 1e-9)[..., None]
            numerator += weight * block.astype(np.float64) / (2.0**ev)
            denominator += weight
        out[rows] = numerator / denominator
    return out


# --------------------------------------------------------------------------
# 预览与色调映射
# --------------------------------------------------------------------------
def tonemap_aces(linear: np.ndarray, ev: float = 0.0) -> np.ndarray:
    """Narkowicz 的 ACES 近似曲线 + sRGB 编码，只用来出预览图。"""
    scale = np.float32(2.0**ev)

    def curve(block: np.ndarray) -> np.ndarray:
        x = np.clip(np.asarray(block, dtype=np.float32) * scale, 0.0, None)
        mapped = (x * (2.51 * x + 0.03)) / (x * (2.43 * x + 0.59) + 0.14)
        return linear_to_srgb(np.clip(mapped, 0.0, 1.0))

    return map_rows(linear, curve)


CUBE_FACES = {
    "+X": ((1, 0, 0), (0, 1, 0), (0, 0, 1)),
    "-X": ((-1, 0, 0), (0, -1, 0), (0, 0, 1)),
    "+Y": ((0, 1, 0), (-1, 0, 0), (0, 0, 1)),
    "-Y": ((0, -1, 0), (1, 0, 0), (0, 0, 1)),
    "+Z(天顶)": ((0, 0, 1), (0, 1, 0), (-1, 0, 0)),
    "-Z(天底)": ((0, 0, -1), (0, 1, 0), (1, 0, 0)),
}


def extract_cube_face(equirect: np.ndarray, face: str, size: int = 256) -> np.ndarray:
    """从经纬图里抠一个 90 度视场的立方体面，用来核对朝向。"""
    forward, right, up = [np.asarray(v, dtype=np.float64) for v in CUBE_FACES[face]]
    axis = (np.arange(size) + 0.5) / size * 2.0 - 1.0
    s = axis[None, :, None]
    t = -axis[:, None, None]
    dirs = forward + right * s + up * t
    dirs /= np.linalg.norm(dirs, axis=-1, keepdims=True)
    u, v, _ = directions_to_source_uv(dirs, "equirect")
    return sample_bilinear(equirect, u, v, wrap_x=True)


# 预览图标签是中英混排的，而系统里这两类字形常常分在不同字体里
# （DejaVu 没有汉字，Droid 的 fallback 字体没有拉丁字母），所以分开挑。
LATIN_FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/croscore/Arimo-Regular.ttf",
)
CJK_FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
)


def _load_font(candidates, size: int):
    from PIL import ImageFont

    for path in candidates:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # 老版本 Pillow 不支持 size 参数
        return ImageFont.load_default()


def load_label_fonts(size: int = 22):
    return _load_font(LATIN_FONT_CANDIDATES, size), _load_font(CJK_FONT_CANDIDATES, size)


def draw_mixed_text(draw, xy, text: str, fonts, fill=(235, 235, 240)) -> None:
    """按 ASCII / 非 ASCII 切段分别用对应字体画，避免出现豆腐块。"""
    latin_font, cjk_font = fonts
    x, y = xy
    for char in text:
        font = latin_font if char.isascii() else cjk_font
        draw.text((x, y), char, fill=fill, font=font)
        x += draw.textlength(char, font=font)


def montage(tiles: list[tuple[str, np.ndarray]], columns: int = 0, gap: int = 8,
            label_height: int = 34, title: str | None = None):
    """把若干 sRGB 图块拼成一张带标题的对比图，返回 PIL Image。"""
    from PIL import Image, ImageDraw

    if not tiles:
        raise ValueError("没有图块可拼")
    columns = columns or len(tiles)
    rows = math.ceil(len(tiles) / columns)
    tile_h, tile_w = tiles[0][1].shape[:2]

    title_height = 40 if title else 0
    width = columns * tile_w + (columns + 1) * gap
    height = rows * (tile_h + label_height) + (rows + 1) * gap + title_height
    canvas = Image.new("RGB", (width, height), (18, 18, 20))
    draw = ImageDraw.Draw(canvas)
    fonts = load_label_fonts(22)
    if title:
        draw_mixed_text(draw, (gap + 4, 10), title, load_label_fonts(26), (250, 250, 255))

    for index, (label, tile) in enumerate(tiles):
        col, row = index % columns, index // columns
        x = gap + col * (tile_w + gap)
        y = title_height + gap + row * (tile_h + label_height + gap)
        data = np.clip(np.asarray(tile) * 255.0 + 0.5, 0, 255).astype(np.uint8)
        canvas.paste(Image.fromarray(data, mode="RGB"), (x, y))
        draw_mixed_text(draw, (x + 4, y + tile_h + 6), label, fonts)
    return canvas


def resize_srgb(rgb_srgb: np.ndarray, width: int) -> np.ndarray:
    from PIL import Image

    data = np.clip(np.asarray(rgb_srgb) * 255.0 + 0.5, 0, 255).astype(np.uint8)
    img = Image.fromarray(data, mode="RGB")
    height = max(1, round(width * img.height / img.width))
    return np.asarray(img.resize((width, height), Image.LANCZOS)).astype(np.float32) / 255.0


# --------------------------------------------------------------------------
# 程序化演示天空
# --------------------------------------------------------------------------
def _value_noise(height: int, width: int, cells: int, rng) -> np.ndarray:
    """左右可循环的平滑值噪声。"""
    from PIL import Image

    grid = rng.random((max(2, cells // 2 + 1), max(2, cells)))
    grid = np.concatenate([grid, grid[:, :1]], axis=1)  # 让横向首尾相接
    img = Image.fromarray(grid.astype(np.float32), mode="F")
    resized = np.asarray(img.resize((width + 1, height), Image.BICUBIC))
    return resized[:, :width]


def make_demo_sky(width: int = 2048, height: int = 1024, seed: int = 7,
                  sun_azimuth: float = 35.0, sun_elevation: float = 25.0) -> np.ndarray:
    """生成一张程序化的「自定义天空」LDR 图，太阳区域故意削顶到 255。"""
    rng = np.random.default_rng(seed)
    dirs = equirect_directions(width, height)
    z = dirs[..., 2]
    sun_dir = azel_to_direction(sun_azimuth, sun_elevation)
    cos_sun = np.clip(dirs @ sun_dir, -1.0, 1.0)
    toward_sun = np.clip(cos_sun, 0.0, 1.0)

    up = np.clip(z, 0.0, 1.0)
    zenith = np.array([0.14, 0.32, 0.72])
    horizon = np.array([0.76, 0.83, 0.90])
    sky = horizon + (zenith - horizon) * up[..., None] ** 0.55

    sky += np.array([1.0, 0.90, 0.72]) * (0.30 * toward_sun**6)[..., None]  # 大范围天光
    sky += np.array([1.0, 0.88, 0.66]) * (0.60 * toward_sun**60)[..., None]  # 太阳周围光晕
    sky += np.array([1.0, 0.97, 0.92]) * (4.0 * toward_sun**4000)[..., None]  # 会削顶的日面

    clouds = sum(
        _value_noise(height, width, cells, rng) * amp
        for cells, amp in ((5, 0.55), (13, 0.27), (30, 0.13), (68, 0.05))
    )
    # 云只长在地平线以上，靠近太阳那一侧边缘偏暖。
    coverage = np.clip((clouds - 0.52) * 3.2, 0.0, 1.0) * np.clip(up * 2.4, 0.0, 1.0)
    cloud_color = np.array([0.96, 0.96, 0.97]) + np.array([0.04, 0.01, -0.05]) * toward_sun[..., None]
    sky = sky * (1.0 - coverage[..., None]) + cloud_color * coverage[..., None]

    ground_noise = _value_noise(height, width, 24, rng) * 0.6 + _value_noise(height, width, 90, rng) * 0.4
    ground = np.array([0.30, 0.27, 0.22]) * (0.6 + 0.5 * np.clip(-z * 2.5, 0.0, 1.0))[..., None]
    ground = ground * (0.92 + 0.16 * ground_noise)[..., None]
    below = np.clip(-z * 8.0, 0.0, 1.0)
    sky = sky * (1.0 - below[..., None]) + ground * below[..., None]

    return np.clip(sky, 0.0, 1.0).astype(np.float32)


# --------------------------------------------------------------------------
# 尺寸推导
# --------------------------------------------------------------------------
def nearest_pot(value: int, low: int = 512, high: int = 8192) -> int:
    value = int(min(max(value, low), high))
    return 1 << round(math.log2(value))


def resolve_output_size(src_shape, projection: str, size: str | None, pot: bool) -> tuple[int, int]:
    if size:
        if "x" in size.lower():
            w, h = [int(v) for v in size.lower().split("x", 1)]
        else:
            w = int(size)
            h = w // 2
        if w < 1 or h < 1:
            raise ValueError("--size 必须为正")
        return w, h

    src_h, src_w = src_shape[:2]
    target = src_w if projection in ("equirect", "skyonly") else 2 * max(src_w, src_h)
    width = nearest_pot(target) if pot else int(min(max(target, 512), 8192))
    return width, max(1, width // 2)


# --------------------------------------------------------------------------
# 子命令
# --------------------------------------------------------------------------
def _print_check(result: CheckResult) -> None:
    print(f"\n检查 {result.path}  ({result.width}x{result.height})")
    for key, value in result.stats.items():
        print(f"  {key:<14} {value:,.4g}")
    for message in result.warnings:
        print(f"  [警告] {message}")
    for message in result.errors:
        print(f"  [错误] {message}")
    print("  结论: " + ("可以导入 UE" if result.ok else "UE 导入会失败"))


def _parse_sun(value: str | None) -> tuple[str, float, float]:
    """--sun 支持 none / auto / '方位角,仰角'。"""
    if value is None or value.lower() == "none":
        return "none", 0.0, 0.0
    if value.lower() == "auto":
        return "auto", 0.0, 0.0
    parts = value.replace(" ", "").split(",")
    if len(parts) != 2:
        raise SystemExit("--sun 只接受 none / auto / '方位角,仰角'（度）")
    return "fixed", float(parts[0]), float(parts[1])


def _build_hdr(args, source_linear: np.ndarray) -> tuple[np.ndarray, tuple[float, float] | None]:
    out_w, out_h = resolve_output_size(source_linear.shape, args.projection, args.size, not args.no_pot)
    print(f"  输出经纬图 {out_w}x{out_h}（投影 {args.projection}，偏转 {args.rotate_yaw:g} 度）")

    equirect, valid = reproject_to_equirect(
        source_linear, out_w, out_h, args.projection,
        yaw_deg=args.rotate_yaw, fisheye_fov_deg=args.fisheye_fov, sky_fov_deg=args.sky_fov,
    )
    covered = float(valid.mean() * 100)
    if covered < 99.9:
        print(f"  源图只覆盖了球面的 {covered:.1f}%，其余用地面色补（albedo {args.ground_albedo:g}）")
        equirect = fill_ground(equirect, valid, args.ground_albedo, args.ground_blend)

    before_peak = float(luminance(equirect).max())
    if args.expand != "none":
        equirect = expand_highlights(equirect, args.knee, args.peak, args.expand_power)
        after_peak = float(luminance(equirect).max())
        print(f"  高光扩展 knee={args.knee:g} peak={args.peak:g} power={args.expand_power:g}："
              f"峰值亮度 {before_peak:.3g} -> {after_peak:.3g}")

    mode, azimuth, elevation = _parse_sun(args.sun)
    sun = None
    if mode != "none":
        if mode == "auto":
            azimuth, elevation = detect_sun(equirect)
            print(f"  自动定位太阳：方位角 {azimuth:.1f} 度，仰角 {elevation:.1f} 度")
        equirect = add_sun(
            equirect, azimuth, elevation, args.sun_radius, args.sun_intensity,
            softness=args.sun_softness,
        )
        sun = (azimuth, elevation)
        print(f"  注入太阳盘：半径 {args.sun_radius:g} 度，峰值 {args.sun_intensity:g}")

    if args.output_ev:
        equirect = (equirect * np.float32(2.0**args.output_ev)).astype(np.float32)
        print(f"  整体曝光 {args.output_ev:+g} 档")

    return sanitize_linear(equirect), sun


def directional_light_rotation(azimuth_deg: float, elevation_deg: float) -> tuple[float, float]:
    """太阳方向 -> UE 平行光的 (Pitch, Yaw)。

    平行光的朝向是光线传播方向，也就是太阳方向的反向：方位角转 180 度、仰角取负。
    """
    yaw = (azimuth_deg + 180.0 + 180.0) % 360.0 - 180.0
    return -elevation_deg, yaw


def _finish(args, built: tuple[np.ndarray, tuple[float, float] | None]) -> int:
    equirect, sun = built
    write_hdr(args.out, equirect, rle=not args.no_rle, comment=args.comment)
    print(f"  已写出 {args.out}")

    ambient = solid_angle_weighted_mean(equirect)
    print(f"  立体角加权平均色（SkyLight 拿到的环境光）: "
          f"R {ambient[0]:.4g}  G {ambient[1]:.4g}  B {ambient[2]:.4g}")

    azimuth, elevation = sun if sun else detect_sun(equirect)
    pitch, yaw = directional_light_rotation(azimuth, elevation)
    print(f"  最亮方向: 方位角 {azimuth:.1f} 度，仰角 {elevation:.1f} 度")
    print(f"  配套平行光旋转: Pitch {pitch:.1f}  Yaw {yaw:.1f}"
          "（全景图在 UE 里转了多少度，这里的 Yaw 就跟着加多少）")

    # 校验要把文件整个读回来，先把内存里的图放掉，8K 时能省几百 MB。
    del equirect, built
    result = check_hdr_for_ue(args.out)
    _print_check(result)
    return 0 if result.ok else 1


def cmd_convert(args) -> int:
    print(f"读入 {args.input}")
    source = load_image_linear(args.input, args.gamma)
    print(f"  源图 {source.shape[1]}x{source.shape[0]}，传递函数 {args.gamma}")
    return _finish(args, _build_hdr(args, source))


def cmd_merge(args) -> int:
    if len(args.inputs) < 2:
        raise SystemExit("merge 至少需要两张不同曝光的图")
    if len(args.ev) != len(args.inputs):
        raise SystemExit(f"给了 {len(args.inputs)} 张图但 {len(args.ev)} 个 --ev 值")

    images = []
    for path, ev in zip(args.inputs, args.ev):
        print(f"读入 {path}  (EV {ev:+g})")
        images.append(load_image_linear(path, args.gamma))
    merged = merge_exposures(images, args.ev)
    lum = luminance(merged)
    print(f"  合并完成：峰值亮度 {lum.max():.4g}，最暗有效亮度 {np.percentile(lum[lum > 0], 1):.4g}")
    return _finish(args, _build_hdr(args, merged))


def cmd_check(args) -> int:
    failed = 0
    for path in args.paths:
        result = check_hdr_for_ue(path)
        _print_check(result)
        failed |= 0 if result.ok else 1
    return failed


def cmd_preview(args) -> int:
    equirect = read_hdr(args.input)
    os.makedirs(args.out_dir, exist_ok=True)
    tiles = []

    for ev in args.sweep:
        preview = resize_srgb(tonemap_aces(equirect, ev), args.width)
        path = os.path.join(args.out_dir, f"ev{ev:+g}.png")
        save_png(path, preview)
        tiles.append((f"EV {ev:+g}", preview))
        print(f"  {path}")

    if args.cube_faces:
        face_tiles = []
        for face in CUBE_FACES:
            face_img = extract_cube_face(equirect, face, args.face_size)
            face_tiles.append((face, tonemap_aces(face_img, args.face_ev)))
        image = montage(face_tiles, columns=3)
        path = os.path.join(args.out_dir, "cube_faces.png")
        image.save(path)
        print(f"  {path}")

    if args.montage and tiles:
        path = os.path.join(args.out_dir, "exposure_sweep.png")
        montage(tiles, columns=len(tiles)).save(path)
        print(f"  {path}")
    return 0


def cmd_demo(args) -> int:
    # 程序化天空直接按显示空间（sRGB 编码值）生成，太阳附近会自然削顶到 255。
    sky = make_demo_sky(args.width, args.height, args.seed, args.sun_azimuth, args.sun_elevation)
    save_png(args.out, sky)
    clipped = float((sky.max(axis=2) >= 1.0).mean() * 100)
    print(f"已写出 {args.out}  ({args.width}x{args.height})，{clipped:.3f}% 的像素削顶到白")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="自定义天空图 -> UE 可用的 Radiance HDR",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def add_common(p, default_expand: str = "knee") -> None:
        p.add_argument("--out", required=True, help="输出的 .hdr 路径")
        p.add_argument("--gamma", default="srgb", help="输入的传递函数：srgb（默认）或数字，如 2.2")
        p.add_argument("--projection", default="equirect", choices=PROJECTIONS,
                       help="源图投影方式，默认 equirect（2:1 经纬图）")
        p.add_argument("--size", help="输出尺寸，如 4096x2048 或只给宽度 4096；默认按源图推导")
        p.add_argument("--no-pot", action="store_true", help="不把输出宽度对齐到 2 的幂")
        p.add_argument("--rotate-yaw", type=float, default=0.0, help="绕天顶轴旋转多少度")
        p.add_argument("--expand", default=default_expand, choices=["knee", "none"],
                       help=f"高光扩展方式，默认 {default_expand}")
        p.add_argument("--knee", type=float, default=0.85, help="开始扩展的亮度阈值，默认 0.85")
        p.add_argument("--peak", type=float, default=16.0, help="完全削顶处的目标线性值，默认 16")
        p.add_argument("--expand-power", type=float, default=3.0, help="扩展曲线指数，默认 3")
        p.add_argument("--sun", default="none", help="太阳盘：none（默认）/ auto / '方位角,仰角'")
        p.add_argument("--sun-radius", type=float, default=1.5, help="太阳角半径（度），默认 1.5")
        p.add_argument("--sun-intensity", type=float, default=2000.0, help="太阳峰值线性值，默认 2000")
        p.add_argument("--sun-softness", type=float, default=0.35, help="太阳边缘羽化比例，默认 0.35")
        p.add_argument("--fisheye-fov", type=float, default=180.0, help="鱼眼视场角（度），默认 180")
        p.add_argument("--sky-fov", type=float, default=90.0,
                       help="skyonly 投影下源图覆盖的垂直角度，默认 90")
        p.add_argument("--ground-albedo", type=float, default=0.25, help="补地面的反射率，默认 0.25")
        p.add_argument("--ground-blend", type=float, default=20.0, help="地平线过渡角度，默认 20")
        p.add_argument("--output-ev", type=float, default=0.0, help="输出整体曝光补偿（档）")
        p.add_argument("--no-rle", action="store_true",
                       help="写非 RLE 扫描线（UE 读不了，仅用于排查问题）")
        p.add_argument("--comment", help="写进 HDR 头的注释")

    p_convert = sub.add_parser("convert", help="单张 LDR/HDR 天空图转 .hdr")
    p_convert.add_argument("input")
    add_common(p_convert)

    p_merge = sub.add_parser("merge", help="多张不同曝光的图合成 .hdr")
    p_merge.add_argument("inputs", nargs="+")
    p_merge.add_argument("--ev", type=float, nargs="+", required=True,
                         help="每张图的曝光值（档），顺序和输入一致")
    # 括号合并出来的已经是真实动态范围，默认不再做高光扩展。
    add_common(p_merge, default_expand="none")

    p_check = sub.add_parser("check", help="校验 .hdr 能否被 UE 导入")
    p_check.add_argument("paths", nargs="+")

    p_preview = sub.add_parser("preview", help="出色调映射预览图")
    p_preview.add_argument("input")
    p_preview.add_argument("--out-dir", default="previews")
    p_preview.add_argument("--sweep", type=float, nargs="*", default=[0.0, -3.0, -6.0, -9.0],
                           help="要渲染的曝光档位")
    p_preview.add_argument("--width", type=int, default=768, help="预览图宽度")
    p_preview.add_argument("--montage", action="store_true", help="把曝光扫描拼成一张对比图")
    p_preview.add_argument("--cube-faces", action="store_true", help="额外导出立方体六面图")
    p_preview.add_argument("--face-size", type=int, default=256)
    p_preview.add_argument("--face-ev", type=float, default=0.0)

    p_demo = sub.add_parser("demo", help="生成一张程序化天空 LDR 图，用于试跑")
    p_demo.add_argument("--out", required=True)
    p_demo.add_argument("--width", type=int, default=2048)
    p_demo.add_argument("--height", type=int, default=1024)
    p_demo.add_argument("--seed", type=int, default=7)
    p_demo.add_argument("--sun-azimuth", type=float, default=35.0)
    p_demo.add_argument("--sun-elevation", type=float, default=25.0)

    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    handler = {
        "convert": cmd_convert,
        "merge": cmd_merge,
        "check": cmd_check,
        "preview": cmd_preview,
        "demo": cmd_demo,
    }[args.command]
    return handler(args)


if __name__ == "__main__":
    sys.exit(main())
