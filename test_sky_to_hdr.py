"""sky_to_hdr 的离线测试：不需要 UE，也不发任何网络请求。

RLE 扫描线用测试文件里另写的一份解码器来验证，避免编码器和解码器
共用同一个错误假设；另外有一条用例拿 OpenCV 的 Radiance 解码器做交叉验证。
"""

from __future__ import annotations

import math
import subprocess
import sys

import numpy as np
import pytest

import sky_to_hdr as sky


# --------------------------------------------------------------------------
# 测试里独立实现的一份 RLE 解码器
# --------------------------------------------------------------------------
def decode_rle_channel(data: bytes, width: int, pos: int = 0) -> tuple[np.ndarray, int]:
    out = []
    while len(out) < width:
        code = data[pos]
        pos += 1
        assert code != 0, "0 不是合法的计数字节"
        if code > 128:
            out.extend([data[pos]] * (code - 128))
            pos += 1
        else:
            out.extend(data[pos : pos + code])
            pos += code
    assert len(out) == width, "解出来的长度必须刚好等于行宽"
    return np.array(out, dtype=np.uint8), pos


# --------------------------------------------------------------------------
# RGBE 编解码
# --------------------------------------------------------------------------
def test_rgbe_roundtrip_across_magnitudes():
    values = np.logspace(-4, 5, 128)
    rgb = np.stack([values, values * 0.5, values * 0.25], axis=-1)[None, :, :]

    back = sky.rgbe_to_float(sky.float_to_rgbe(rgb))

    peak = rgb.max(axis=-1)
    # 尾数是 8 bit 且最大通道落在 [128, 256)，所以量化步长不超过 峰值/128。
    assert np.all(np.abs(back - rgb) <= peak[..., None] / 128 + 1e-12)
    assert np.allclose(back.max(axis=-1), peak, rtol=1 / 128)


def test_rgbe_encodes_zero_and_denormals_as_zero():
    assert not sky.float_to_rgbe(np.zeros((3, 3, 3))).any()
    assert not sky.float_to_rgbe(np.full((1, 1, 3), 1e-40)).any()


def test_rgbe_sanitizes_nan_and_negative():
    rgb = np.array([[[np.nan, -5.0, np.inf]]])
    rgbe = sky.float_to_rgbe(rgb)
    back = sky.rgbe_to_float(rgbe)
    assert np.isfinite(back).all()
    assert (back >= 0).all()
    assert back[0, 0, 0] == 0.0 and back[0, 0, 1] == 0.0
    assert back[0, 0, 2] > 1e30


def test_rgbe_preserves_relative_channel_ratios():
    rgb = np.array([[[4.0, 2.0, 1.0]]])
    back = sky.rgbe_to_float(sky.float_to_rgbe(rgb))[0, 0]
    assert back[0] / back[1] == pytest.approx(2.0, rel=0.01)
    assert back[1] / back[2] == pytest.approx(2.0, rel=0.01)


def test_float_to_rgbe_rejects_bad_shape():
    with pytest.raises(ValueError):
        sky.float_to_rgbe(np.zeros((4, 4)))


# --------------------------------------------------------------------------
# RLE 扫描线编码
# --------------------------------------------------------------------------
@pytest.mark.parametrize("width", [8, 9, 127, 128, 129, 255, 256, 1000])
@pytest.mark.parametrize("kind", ["constant", "alternating", "random", "runs_of_four", "long_run"])
def test_rle_channel_roundtrip(width: int, kind: str):
    rng = np.random.default_rng(width)
    if kind == "constant":
        values = np.full(width, 77, dtype=np.uint8)
    elif kind == "alternating":
        values = np.tile(np.array([3, 250], dtype=np.uint8), width // 2 + 1)[:width]
    elif kind == "random":
        values = rng.integers(0, 256, width, dtype=np.uint8)
    elif kind == "runs_of_four":
        values = np.repeat(rng.integers(0, 256, width // 4 + 1, dtype=np.uint8), 4)[:width]
    else:  # 单个重复段超过 127，必须被拆成多条重复码
        values = np.full(width, 12, dtype=np.uint8)
        values[: min(width, 3)] = np.arange(min(width, 3))

    encoded = bytes(sky._encode_channel(values))
    decoded, consumed = decode_rle_channel(encoded, width)

    assert consumed == len(encoded), "编码后不应有多余字节"
    assert np.array_equal(decoded, values)


def test_rle_actually_compresses_flat_rows():
    values = np.full(4096, 200, dtype=np.uint8)
    assert len(sky._encode_channel(values)) < 128


def test_scanline_header_carries_width():
    row = np.zeros((300, 4), dtype=np.uint8)
    encoded = bytes(sky._encode_scanline(row))
    assert encoded[0] == 2 and encoded[1] == 2
    assert (encoded[2] << 8) | encoded[3] == 300


# --------------------------------------------------------------------------
# 文件读写
# --------------------------------------------------------------------------
def make_test_image(height: int, width: int, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    base = rng.random((height, width, 3)).astype(np.float32) * 2.0
    base[height // 2, width // 2] = [900.0, 850.0, 800.0]  # 制造一个高动态范围的亮点
    return base


@pytest.mark.parametrize("size", [(5, 9), (64, 128), (3, 1000), (17, 33)])
def test_write_read_roundtrip(tmp_path, size):
    height, width = size
    image = make_test_image(height, width)
    path = tmp_path / "test.hdr"

    sky.write_hdr(str(path), image)
    back = sky.read_hdr(str(path))

    assert back.shape == image.shape
    peak = image.max(axis=-1)
    assert np.all(np.abs(back - image) <= peak[..., None] / 128 + 1e-6)


def test_written_header_matches_ue_expectations(tmp_path):
    path = tmp_path / "header.hdr"
    sky.write_hdr(str(path), make_test_image(16, 32))
    raw = path.read_bytes()

    assert raw.startswith(b"#?RADIANCE\n")
    header, _, rest = raw.partition(b"\n\n")
    assert b"FORMAT=32-bit_rle_rgbe" in header
    assert rest.startswith(b"-Y 16 +X 32\n")
    assert header.decode("ascii").isascii()

    pixels = rest[len(b"-Y 16 +X 32\n") :]
    assert pixels[0] == 2 and pixels[1] == 2  # 首行就是新版 RLE


def test_every_scanline_is_new_style_rle(tmp_path):
    path = tmp_path / "rle.hdr"
    sky.write_hdr(str(path), make_test_image(24, 40))
    result = sky.check_hdr_for_ue(str(path))
    assert result.ok, result.errors


def test_write_hdr_rejects_bad_shape(tmp_path):
    with pytest.raises(ValueError):
        sky.write_hdr(str(tmp_path / "bad.hdr"), np.zeros((4, 4)))


def test_reader_rejects_truncated_file(tmp_path):
    path = tmp_path / "cut.hdr"
    sky.write_hdr(str(path), make_test_image(32, 64))
    raw = path.read_bytes()
    path.write_bytes(raw[: len(raw) // 2])
    with pytest.raises(ValueError):
        sky.read_hdr(str(path))


# --------------------------------------------------------------------------
# UE 导入兼容性检查
# --------------------------------------------------------------------------
def test_checker_accepts_pot_2to1_output(tmp_path):
    path = tmp_path / "good.hdr"
    image = make_test_image(64, 128)
    sky.write_hdr(str(path), image)

    result = sky.check_hdr_for_ue(str(path))

    assert result.ok
    assert (result.width, result.height) == (128, 64)
    assert not result.warnings, result.warnings
    assert result.stats["动态范围档数"] > 8


def test_checker_rejects_non_rle_output(tmp_path):
    path = tmp_path / "flat.hdr"
    sky.write_hdr(str(path), make_test_image(16, 32), rle=False)

    result = sky.check_hdr_for_ue(str(path))

    assert not result.ok
    assert any("RLE" in message for message in result.errors)
    # 自己的解码器仍然读得回来，只是 UE 读不了。
    assert sky.read_hdr(str(path)).shape == (16, 32, 3)


def test_checker_rejects_wrong_magic(tmp_path):
    path = tmp_path / "magic.hdr"
    sky.write_hdr(str(path), make_test_image(16, 32))
    path.write_bytes(b"#?NOPE\n" + path.read_bytes().split(b"\n", 1)[1])

    result = sky.check_hdr_for_ue(str(path))
    assert not result.ok
    assert any("Radiance" in message for message in result.errors)


def test_checker_rejects_wrong_format_line(tmp_path):
    path = tmp_path / "format.hdr"
    sky.write_hdr(str(path), make_test_image(16, 32))
    path.write_bytes(path.read_bytes().replace(b"FORMAT=32-bit_rle_rgbe", b"FORMAT=32-bit_rle_xyze"))

    result = sky.check_hdr_for_ue(str(path))
    assert not result.ok
    assert any("FORMAT" in message for message in result.errors)


def test_checker_rejects_flipped_resolution_line(tmp_path):
    path = tmp_path / "res.hdr"
    sky.write_hdr(str(path), make_test_image(16, 32))
    path.write_bytes(path.read_bytes().replace(b"-Y 16 +X 32", b"+X 32 -Y 16"))

    result = sky.check_hdr_for_ue(str(path))
    assert not result.ok


def test_checker_warns_on_non_pot_and_wrong_aspect(tmp_path):
    path = tmp_path / "odd.hdr"
    sky.write_hdr(str(path), make_test_image(60, 100))

    result = sky.check_hdr_for_ue(str(path))

    assert result.ok  # 能导入，只是不理想
    assert any("2:1" in message for message in result.warnings)
    assert any("2 的幂" in message for message in result.warnings)


def test_checker_warns_when_content_is_still_ldr(tmp_path):
    path = tmp_path / "ldr.hdr"
    sky.write_hdr(str(path), np.full((16, 32, 3), 0.5, dtype=np.float32))

    result = sky.check_hdr_for_ue(str(path))

    assert result.ok
    assert any("LDR" in message for message in result.warnings)


def test_opencv_decodes_our_file_identically(tmp_path):
    cv2 = pytest.importorskip("cv2", reason="用 OpenCV 的 Radiance 解码器做交叉验证")
    path = tmp_path / "cross.hdr"
    image = make_test_image(48, 96, seed=3)
    sky.write_hdr(str(path), image)

    theirs = cv2.imread(str(path), cv2.IMREAD_ANYDEPTH | cv2.IMREAD_COLOR)
    assert theirs is not None, "OpenCV 没能解析这个文件"
    theirs = theirs[:, :, ::-1]  # BGR -> RGB

    assert np.array_equal(sky.read_hdr(str(path)), theirs.astype(np.float32))


# --------------------------------------------------------------------------
# 传递函数
# --------------------------------------------------------------------------
def test_luminance_matches_a_direct_dot_product():
    image = make_test_image(300, 71, seed=8)  # 行数跨过多个分块
    assert np.allclose(sky.luminance(image), image @ sky.LUMA.astype(np.float32), atol=1e-6)


def test_luminance_rejects_bad_shape():
    with pytest.raises(ValueError):
        sky.luminance(np.zeros((4, 4)))


def test_sanitize_linear_cleans_in_place():
    image = np.zeros((300, 4, 3), dtype=np.float32)
    image[0] = [np.nan, -3.0, np.inf]
    image[299] = [1.5, -0.0, 2.0]

    returned = sky.sanitize_linear(image)

    assert returned is image, "应该就地修改，不另开拷贝"
    assert np.isfinite(image).all()
    assert (image >= 0).all()
    assert image[0, 0, 0] == 0.0 and image[0, 0, 1] == 0.0
    assert image[0, 0, 2] > 1e30
    assert image[299, 0].tolist() == [1.5, 0.0, 2.0]


def test_srgb_transfer_known_points():
    assert sky.srgb_to_linear(np.array([0.0]))[0] == pytest.approx(0.0)
    assert sky.srgb_to_linear(np.array([1.0]))[0] == pytest.approx(1.0, abs=1e-6)
    assert sky.srgb_to_linear(np.array([0.5]))[0] == pytest.approx(0.21404, abs=1e-4)
    assert sky.srgb_to_linear(np.array([0.04]))[0] == pytest.approx(0.04 / 12.92, abs=1e-6)


def test_srgb_transfer_roundtrip():
    x = np.linspace(0.0, 1.0, 257, dtype=np.float32)
    assert np.allclose(sky.linear_to_srgb(sky.srgb_to_linear(x)), x, atol=1e-5)


# --------------------------------------------------------------------------
# 高光扩展
# --------------------------------------------------------------------------
def test_expand_highlights_leaves_midtones_alone():
    image = np.full((4, 4, 3), 0.3, dtype=np.float32)
    assert np.allclose(sky.expand_highlights(image, knee=0.75), image)


def test_expand_highlights_reaches_peak_at_white():
    white = np.ones((1, 1, 3), dtype=np.float32)
    out = sky.expand_highlights(white, knee=0.75, peak=48.0)
    assert out[0, 0].tolist() == pytest.approx([48.0, 48.0, 48.0], rel=1e-5)


def test_expand_highlights_is_monotonic_and_continuous():
    ramp = np.linspace(0.0, 1.0, 512, dtype=np.float32)
    image = np.repeat(ramp[None, :, None], 3, axis=2)
    out = sky.expand_highlights(image, knee=0.75, peak=48.0)[0, :, 0]

    assert np.all(np.diff(out) >= -1e-6), "扩展后必须仍然单调"
    # knee 处导数为 0，所以不会出现台阶。
    knee_index = int(0.75 * 512)
    step = np.diff(out)
    assert step[knee_index] == pytest.approx(step[knee_index - 1], abs=1e-3)


def test_expand_highlights_preserves_hue():
    color = np.array([[[0.9, 0.6, 0.3]]], dtype=np.float32)
    out = sky.expand_highlights(color, knee=0.5, peak=20.0)[0, 0]
    ratio = out / color[0, 0]
    assert ratio[0] == pytest.approx(ratio[1], rel=1e-5)
    assert ratio[1] == pytest.approx(ratio[2], rel=1e-5)


@pytest.mark.parametrize(
    "kwargs", [{"knee": 1.0}, {"knee": -0.1}, {"peak": 0.5}, {"power": 0.0}]
)
def test_expand_highlights_validates_arguments(kwargs):
    with pytest.raises(ValueError):
        sky.expand_highlights(np.ones((2, 2, 3), dtype=np.float32), **kwargs)


# --------------------------------------------------------------------------
# 方向与投影
# --------------------------------------------------------------------------
def test_equirect_directions_are_unit_length():
    dirs = sky.equirect_directions(64, 32)
    assert np.allclose(np.linalg.norm(dirs, axis=-1), 1.0, atol=1e-12)


def test_equirect_directions_convention():
    dirs = sky.equirect_directions(8, 4)
    # 第一行靠天顶，最后一行靠天底。
    assert dirs[0, :, 2].min() == pytest.approx(math.cos(math.pi / 8), abs=1e-12)
    assert dirs[-1, :, 2].max() == pytest.approx(math.cos(7 * math.pi / 8), abs=1e-12)
    # 正中间两列夹着 +X，方位角向 +Y 方向增大。
    assert dirs[1, 3, 0] > 0 and dirs[1, 3, 1] < 0
    assert dirs[1, 4, 0] > 0 and dirs[1, 4, 1] > 0
    assert sky.direction_to_azel(dirs[1, 4])[0] == pytest.approx(22.5)


def test_azel_direction_roundtrip():
    for azimuth, elevation in [(0, 0), (35, 25), (-120, 70), (179, -40)]:
        back = sky.direction_to_azel(sky.azel_to_direction(azimuth, elevation))
        assert back[0] == pytest.approx(azimuth, abs=1e-9)
        assert back[1] == pytest.approx(elevation, abs=1e-9)


def test_equirect_identity_is_bit_exact():
    image = make_test_image(32, 64)
    out, valid = sky.reproject_to_equirect(image, 64, 32, "equirect")
    assert np.array_equal(out, image)
    assert valid.all()


def test_yaw_rotation_shifts_columns():
    image = make_test_image(4, 8, seed=11)
    out, _ = sky.reproject_to_equirect(image, 8, 4, "equirect", yaw_deg=90.0)
    assert np.allclose(out, np.roll(image, 2, axis=1), atol=1e-6)


def test_fisheye_landmarks():
    dirs = np.array(
        [[0.0, 0.0, 1.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, -1.0]]
    )
    u, v, valid = sky.directions_to_source_uv(dirs, "fisheye180")

    assert (u[0], v[0]) == pytest.approx((0.5, 0.5))  # 天顶落在图心
    assert (u[1], v[1]) == pytest.approx((1.0, 0.5))  # 世界 +X 落在图像右边缘
    assert (u[2], v[2]) == pytest.approx((0.5, 0.0))  # 世界 +Y 落在图像上边缘
    assert valid.tolist() == [True, True, True, False]  # 下半球没有覆盖


def test_mirrorball_landmarks():
    dirs = np.array([[-1.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 0.0, 1.0], [0.0, 0.0, -1.0]])
    u, v, _ = sky.directions_to_source_uv(dirs, "mirrorball")

    # 相机看向 +X：球心反射的是相机背后（-X），球边缘是相机正前方（+X）。
    assert (u[0], v[0]) == pytest.approx((0.5, 0.5))
    assert math.hypot(u[1] - 0.5, v[1] - 0.5) == pytest.approx(0.5, abs=1e-6)
    # 世界 +Z（天顶）落在球的上半部，天底在下半部，半径都是 sqrt(1/2)/2。
    assert v[2] < 0.5 and v[3] > 0.5
    assert math.hypot(u[2] - 0.5, v[2] - 0.5) == pytest.approx(0.5 * math.sqrt(0.5), abs=1e-6)


def test_mirrorball_keeps_camera_right_on_the_image_right():
    # 相机看向 +X 时相机右手边是世界 +Y，它必须落在球面图的右半边。
    u, v, _ = sky.directions_to_source_uv(np.array([[0.0, 1.0, 0.0]]), "mirrorball")
    assert u[0] > 0.5
    assert v[0] == pytest.approx(0.5, abs=1e-9)


def test_mirrorball_radius_is_continuous_near_the_edge():
    # 正前方是个几何奇点，边缘附近的半径必须平滑地趋近 1，不能塌回球心。
    angles = np.radians([180.0, 170.0, 120.0, 60.0, 10.0, 1.0, 0.0])
    dirs = np.stack([np.cos(angles), np.zeros_like(angles), np.sin(angles)], axis=-1)
    u, v, _ = sky.directions_to_source_uv(dirs, "mirrorball")

    radii = np.hypot(u - 0.5, v - 0.5) * 2.0
    assert np.all(np.diff(radii) > 0), "从球心到球边缘半径应单调增大"
    assert radii[0] == pytest.approx(0.0, abs=1e-9)
    assert radii[-1] == pytest.approx(1.0, abs=1e-9)


def forward_project(projection: str, u: np.ndarray, v: np.ndarray) -> np.ndarray:
    """测试里独立实现的正向映射：源图 uv -> 世界方向。

    和 sky_to_hdr 里的反向映射是两套推导，用来交叉验证。
    """
    if projection == "equirect":
        theta = v * math.pi
        phi = (u - 0.5) * 2 * math.pi
        return np.stack(
            [np.sin(theta) * np.cos(phi), np.sin(theta) * np.sin(phi), np.cos(theta)], axis=-1
        )

    if projection == "fisheye180":
        px, py = 2 * u - 1, 1 - 2 * v
        theta = np.hypot(px, py) * (math.pi / 2)
        angle = np.arctan2(py, px)
        return np.stack(
            [np.sin(theta) * np.cos(angle), np.sin(theta) * np.sin(angle), np.cos(theta)], axis=-1
        )

    if projection == "mirrorball":
        # 球面图坐标 (nx, ny) 就是朝向相机那一侧的法线的 xy；相机沿 +z_c 入射，
        # 所以该点法线是 (nx, ny, -s)，反射方向 R = V - 2(V·n)n。
        nx, ny = 2 * u - 1, 1 - 2 * v
        s = np.sqrt(np.clip(1 - nx**2 - ny**2, 0.0, 1.0))
        # 相机空间 (右, 上, 前) 对应世界 (+Y, +Z, +X)。
        return np.stack([1 - 2 * s**2, 2 * s * nx, 2 * s * ny], axis=-1)

    raise AssertionError(projection)


@pytest.mark.parametrize("projection", ["equirect", "fisheye180", "mirrorball"])
def test_projection_inverse_matches_an_independent_forward_map(projection):
    # 躲开各投影的奇点：经纬图的极点、鱼眼的边缘、镜面球的边缘。
    axis = np.linspace(0.18, 0.82, 17)
    u, v = np.meshgrid(axis, axis)
    dirs = forward_project(projection, u, v)

    back_u, back_v, valid = sky.directions_to_source_uv(dirs, projection)

    assert valid.all()
    assert np.allclose(back_u, u, atol=1e-9)
    assert np.allclose(back_v, v, atol=1e-9)


def test_mirrorball_image_round_trips_back_to_equirect():
    """把经纬图渲染成镜面球照片，再让工具还原，应该回到原样。"""
    height, width = 64, 128
    dirs = sky.equirect_directions(width, height)
    pattern = (0.5 + 0.5 * dirs).astype(np.float32)  # 平滑的方向编码图案

    size = 512
    axis = (np.arange(size) + 0.5) / size * 2 - 1
    ball_u, ball_v = np.meshgrid((axis + 1) / 2, (axis + 1) / 2)
    ball_dirs = forward_project("mirrorball", ball_u, ball_v)
    u, v, _ = sky.directions_to_source_uv(ball_dirs, "equirect")
    ball = sky.sample_bilinear(pattern, u, v, wrap_x=True)

    restored, valid = sky.reproject_to_equirect(ball, width, height, "mirrorball")

    # 球边缘映射的是相机正前方（世界 +X），那里压缩到无穷、采样不可信，排除掉。
    away_from_edge = (dirs @ np.array([1.0, 0.0, 0.0])) < math.cos(math.radians(40))
    assert valid.all()
    assert np.abs(restored - pattern)[away_from_edge].max() < 0.02


def test_unknown_projection_raises():
    with pytest.raises(ValueError):
        sky.directions_to_source_uv(np.zeros((1, 3)), "cylindrical")


def test_skyonly_covers_upper_hemisphere_only():
    image = make_test_image(32, 64, seed=5)
    out, valid = sky.reproject_to_equirect(image, 64, 32, "skyonly", sky_fov_deg=90.0)

    assert valid[:16].all()
    assert not valid[17:].any()
    assert out[20:].max() == 0.0  # 补地面之前下半球是空的


def test_fill_ground_only_touches_uncovered_rows():
    image = np.ones((32, 64, 3), dtype=np.float32) * 0.6
    valid = np.zeros((32, 64), dtype=bool)
    valid[:16] = True
    image[16:] = 0.0

    filled = sky.fill_ground(image, valid, albedo=0.25, blend_deg=20.0)

    assert np.array_equal(filled[:16], image[:16])
    assert filled[-1].max() == pytest.approx(0.6 * 0.25, rel=1e-5)
    assert filled[16:].min() > 0.0  # 下半球不再是黑洞


def test_cube_faces_line_up_with_equirect():
    image = np.zeros((64, 128, 3), dtype=np.float32)
    image[:32] = 1.0  # 上半球全白，下半球全黑

    up = sky.extract_cube_face(image, "+Z(天顶)", size=32)
    down = sky.extract_cube_face(image, "-Z(天底)", size=32)
    side = sky.extract_cube_face(image, "+X", size=32)

    assert up.min() == pytest.approx(1.0)
    assert down.max() == pytest.approx(0.0)
    # 侧面的地平线落在正中间，紧贴边界的那一行会因为双线性插值混色。
    assert side[:15].min() > 0.99
    assert side[17:].max() < 0.01


def test_solid_angle_weighted_mean_of_constant_image():
    image = np.full((64, 128, 3), 0.42, dtype=np.float32)
    assert sky.solid_angle_weighted_mean(image) == pytest.approx([0.42] * 3, rel=1e-6)


def test_solid_angle_weighting_downweights_poles():
    image = np.zeros((64, 128, 3), dtype=np.float32)
    image[0] = 1.0  # 只有紧贴天顶的一行是亮的
    mean = sky.solid_angle_weighted_mean(image)
    naive = image.mean(axis=(0, 1))
    assert mean[0] < naive[0]


# --------------------------------------------------------------------------
# 太阳
# --------------------------------------------------------------------------
def make_disc_sky(height=256, width=512, azimuth=-70.0, elevation=40.0,
                  radius_deg=2.0, sky_value=0.3, disc_value=1.0) -> np.ndarray:
    dirs = sky.equirect_directions(width, height)
    cos_angle = dirs @ sky.azel_to_direction(azimuth, elevation)
    disc = cos_angle >= math.cos(math.radians(radius_deg))
    image = np.full((height, width, 3), sky_value, dtype=np.float32)
    image[disc] = disc_value
    return image


def test_add_sun_lands_in_the_requested_direction():
    height, width = 512, 1024
    image = np.zeros((height, width, 3), dtype=np.float32)

    out = sky.add_sun(image, azimuth_deg=-70.0, elevation_deg=40.0,
                      radius_deg=3.0, intensity=1000.0, color=(1.0, 1.0, 1.0))

    # 日面中心是平顶的，所以用亮度重心而不是 argmax 来定位。
    azimuth, elevation = sky.detect_sun(out)
    assert azimuth == pytest.approx(-70.0, abs=0.5)
    assert elevation == pytest.approx(40.0, abs=0.5)
    assert (out @ sky.LUMA).max() == pytest.approx(1000.0, rel=0.01)
    assert out[out.sum(axis=2) == 0].size > 0, "日面之外不应被改动"


def test_add_sun_energy_matches_its_solid_angle():
    height, width = 512, 1024
    radius_deg, intensity, softness = 3.0, 1000.0, 0.35
    image = np.zeros((height, width, 3), dtype=np.float32)

    out = sky.add_sun(image, 0.0, 30.0, radius_deg=radius_deg, intensity=intensity,
                      color=(1.0, 1.0, 1.0), softness=softness)

    theta = (np.arange(height) + 0.5) / height * math.pi
    pixel_solid_angle = np.sin(theta)[:, None] * (math.pi / height) * (2 * math.pi / width)
    energy = float(((out @ sky.LUMA) * pixel_solid_angle).sum())

    outer = 2 * math.pi * (1 - math.cos(math.radians(radius_deg)))
    inner = 2 * math.pi * (1 - math.cos(math.radians(radius_deg * (1 - softness))))
    # 中心区域权重为 1，边缘羽化，所以总能量落在内外圆立体角之间。
    assert inner * intensity <= energy <= outer * intensity


def test_add_sun_rejects_bad_radius():
    with pytest.raises(ValueError):
        sky.add_sun(np.zeros((8, 16, 3), dtype=np.float32), 0.0, 0.0, radius_deg=0.0)


def test_detect_sun_finds_a_compact_disc():
    image = make_disc_sky(azimuth=-70.0, elevation=40.0, radius_deg=2.0)
    azimuth, elevation = sky.detect_sun(image)
    assert azimuth == pytest.approx(-70.0, abs=1.0)
    assert elevation == pytest.approx(40.0, abs=1.0)


def test_detect_sun_ignores_a_bright_horizon_band():
    image = make_disc_sky(azimuth=120.0, elevation=55.0, radius_deg=2.0)
    image[120:136] = 0.95  # 一条很亮但没到削顶的地平线亮带
    azimuth, elevation = sky.detect_sun(image)
    assert azimuth == pytest.approx(120.0, abs=2.0)
    assert elevation == pytest.approx(55.0, abs=2.0)


def test_detect_sun_finds_the_centre_of_a_clipped_halo():
    """真实 8 bit 天空照片里日面周围是一大片削顶的光晕，要找到它的中心。"""
    height, width = 256, 512
    dirs = sky.equirect_directions(width, height)
    toward_sun = np.clip(dirs @ sky.azel_to_direction(-40.0, 30.0), 0.0, 1.0)
    image = np.clip(0.25 + 6.0 * toward_sun**60, 0.0, 1.0).astype(np.float32)
    image = np.repeat(image[..., None], 3, axis=2)
    image[120:136] = 0.9  # 同时来一条很亮的地平线带干扰

    assert (image.max(axis=2) >= 1.0).mean() > 0.002, "先确认真的存在一片削顶区"

    azimuth, elevation = sky.detect_sun(image)
    assert azimuth == pytest.approx(-40.0, abs=2.0)
    assert elevation == pytest.approx(30.0, abs=2.0)


def test_sun_disc_restores_energy_lost_to_clipping():
    """8 bit 图削掉的能量主要是日面那一块，注入太阳盘应该把它补回来。"""
    height, width = 256, 512
    dirs = sky.equirect_directions(width, height)
    toward_sun = np.clip(dirs @ sky.azel_to_direction(20.0, 35.0), 0.0, 1.0)
    truth = (0.3 + 3000.0 * toward_sun**8000)[..., None] * np.ones(3, dtype=np.float32)
    truth = truth.astype(np.float32)

    photo = np.clip(truth, 0.0, 1.0)  # 拍成 8 bit：日面被削平到 1.0
    azimuth, elevation = sky.detect_sun(photo)
    rebuilt = sky.add_sun(sky.expand_highlights(photo), azimuth, elevation)

    energy = lambda image: float(sky.solid_angle_weighted_mean(image) @ sky.LUMA)
    truth_energy = energy(truth)
    assert energy(photo) / truth_energy < 0.7, "先确认削顶确实丢掉了大部分能量"
    assert 0.7 < energy(rebuilt) / truth_energy < 1.4
    assert abs(energy(rebuilt) - truth_energy) < abs(energy(photo) - truth_energy)


def test_directional_light_rotation_points_away_from_the_sun():
    pitch, yaw = sky.directional_light_rotation(35.0, 25.0)
    assert pitch == pytest.approx(-25.0)
    assert yaw == pytest.approx(-145.0)  # 35 + 180 折回 [-180, 180)

    # 平行光朝向应该正好是太阳方向的反向。
    light_dir = sky.azel_to_direction(yaw, pitch)
    assert light_dir == pytest.approx(-sky.azel_to_direction(35.0, 25.0), abs=1e-12)


def test_detect_sun_on_flat_image_does_not_crash():
    azimuth, elevation = sky.detect_sun(np.zeros((32, 64, 3), dtype=np.float32))
    assert math.isfinite(azimuth) and math.isfinite(elevation)


# --------------------------------------------------------------------------
# 多曝光合并
# --------------------------------------------------------------------------
def simulate_capture(truth: np.ndarray, ev: float) -> np.ndarray:
    """模拟一次 8 bit 曝光：乘曝光、编码成 sRGB、削顶、量化，再解回线性。"""
    display = sky.linear_to_srgb(truth * (2.0**ev))
    quantized = np.round(np.clip(display, 0.0, 1.0) * 255.0) / 255.0
    return sky.srgb_to_linear(quantized)


def test_merge_exposures_recovers_ground_truth():
    rng = np.random.default_rng(4)
    truth = np.exp(rng.uniform(math.log(0.05), math.log(20.0), (32, 64, 1))) * np.ones(3)
    truth = truth.astype(np.float32)
    evs = [-6.0, -3.0, 0.0]

    merged = sky.merge_exposures([simulate_capture(truth, ev) for ev in evs], evs)

    error = np.abs(merged - truth) / truth
    assert error.max() < 0.10
    assert np.median(error) < 0.02


def test_merge_exposures_beats_any_single_frame():
    rng = np.random.default_rng(9)
    truth = np.exp(rng.uniform(math.log(0.05), math.log(20.0), (32, 64, 1))) * np.ones(3)
    truth = truth.astype(np.float32)
    evs = [-6.0, -3.0, 0.0]
    captures = [simulate_capture(truth, ev) for ev in evs]

    merged_error = np.abs(sky.merge_exposures(captures, evs) - truth).mean()
    for capture, ev in zip(captures, evs):
        single_error = np.abs(capture / (2.0**ev) - truth).mean()
        assert merged_error < single_error


def test_merge_needs_a_dark_enough_frame_to_capture_the_sun():
    """括号里最暗那张也要能装下日面，否则日面照样削顶。"""
    height, width = 64, 128
    dirs = sky.equirect_directions(width, height)
    toward_sun = np.clip(dirs @ sky.azel_to_direction(0.0, 30.0), 0.0, 1.0)
    truth = ((0.3 + 4000.0 * toward_sun**2000)[..., None] * np.ones(3)).astype(np.float32)

    too_bright = [-6.0, -3.0, 0.0]  # 最暗一张只到 1/64，日面还是过曝
    dark_enough = [-14.0, -7.0, 0.0]  # 最暗一张到 1/16384，装得下 4000

    shallow = sky.merge_exposures([simulate_capture(truth, ev) for ev in too_bright], too_bright)
    deep = sky.merge_exposures([simulate_capture(truth, ev) for ev in dark_enough], dark_enough)

    truth_peak = float(sky.luminance(truth).max())
    assert float(sky.luminance(shallow).max()) < truth_peak * 0.2
    assert float(sky.luminance(deep).max()) == pytest.approx(truth_peak, rel=0.05)


def test_merge_exposures_validates_inputs():
    image = np.ones((4, 4, 3), dtype=np.float32)
    with pytest.raises(ValueError):
        sky.merge_exposures([image, image], [0.0])
    with pytest.raises(ValueError):
        sky.merge_exposures([], [])
    with pytest.raises(ValueError):
        sky.merge_exposures([image, np.ones((8, 8, 3), dtype=np.float32)], [0.0, 1.0])


# --------------------------------------------------------------------------
# 尺寸推导
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    "src,expected",
    [((1024, 2048), (2048, 1024)), ((1500, 3000), (4096, 2048)), ((256, 512), (512, 256))],
)
def test_resolve_output_size_snaps_to_power_of_two(src, expected):
    assert sky.resolve_output_size(src, "equirect", None, pot=True) == expected


def test_resolve_output_size_honours_explicit_size():
    assert sky.resolve_output_size((100, 200), "equirect", "4096x2048", pot=True) == (4096, 2048)
    assert sky.resolve_output_size((100, 200), "equirect", "1024", pot=True) == (1024, 512)


def test_resolve_output_size_rejects_zero():
    with pytest.raises(ValueError):
        sky.resolve_output_size((100, 200), "equirect", "0x0", pot=True)


# --------------------------------------------------------------------------
# 命令行
# --------------------------------------------------------------------------
def run_cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "sky_to_hdr.py", *args], capture_output=True, text=True, check=False
    )


def test_demo_sky_clips_around_the_sun(tmp_path):
    sky_ldr = sky.make_demo_sky(512, 256, sun_azimuth=35.0, sun_elevation=25.0)
    assert sky_ldr.min() >= 0.0 and sky_ldr.max() <= 1.0
    clipped = (sky_ldr.max(axis=2) >= 1.0).mean()
    assert 0.001 < clipped < 0.10, "日面要削顶，但不能糊掉整张图"


def test_cli_demo_convert_check_pipeline(tmp_path):
    png = tmp_path / "sky.png"
    hdr = tmp_path / "sky.hdr"

    assert run_cli("demo", "--out", str(png), "--width", "512", "--height", "256").returncode == 0
    converted = run_cli(
        "convert", str(png), "--out", str(hdr), "--size", "512x256",
        "--sun", "35,25", "--sun-intensity", "5000",
    )
    assert converted.returncode == 0, converted.stderr
    assert "可以导入 UE" in converted.stdout

    result = sky.check_hdr_for_ue(str(hdr))
    assert result.ok, result.errors
    assert result.stats["最大亮度"] > 1000
    assert result.stats["动态范围档数"] > 12

    checked = run_cli("check", str(hdr))
    assert checked.returncode == 0


def test_cli_check_fails_on_unreadable_file(tmp_path):
    broken = tmp_path / "broken.hdr"
    broken.write_bytes(b"not an hdr at all")
    assert run_cli("check", str(broken)).returncode == 1


def test_cli_convert_from_fisheye_source(tmp_path):
    from PIL import Image

    rng = np.random.default_rng(2)
    disc = (rng.random((256, 256, 3)) * 255).astype(np.uint8)
    png = tmp_path / "fisheye.png"
    Image.fromarray(disc).save(png)
    hdr = tmp_path / "fisheye.hdr"

    result = run_cli("convert", str(png), "--projection", "fisheye180", "--out", str(hdr))

    assert result.returncode == 0, result.stderr
    assert "覆盖了球面的" in result.stdout
    check = sky.check_hdr_for_ue(str(hdr))
    assert check.ok, check.errors
    # 下半球是补出来的地面色，不能是黑的。
    filled = sky.read_hdr(str(hdr))
    assert filled[-1].min() > 0.0


def test_cli_merge_pipeline(tmp_path):
    from PIL import Image

    truth = sky.make_demo_sky(256, 128) * 8.0
    paths = []
    evs = [-4.0, 0.0]
    for index, ev in enumerate(evs):
        display = np.clip(sky.linear_to_srgb(truth * (2.0**ev)), 0, 1)
        path = tmp_path / f"bracket{index}.png"
        Image.fromarray((display * 255).astype(np.uint8)).save(path)
        paths.append(str(path))

    hdr = tmp_path / "merged.hdr"
    result = run_cli("merge", *paths, "--ev", "-4", "0", "--out", str(hdr), "--size", "256x128")

    assert result.returncode == 0, result.stderr
    merged = sky.read_hdr(str(hdr))
    # 合并结果应该覆盖到最亮曝光削掉的那一段。
    assert merged.max() > 4.0


def test_cli_preview_writes_images(tmp_path):
    hdr = tmp_path / "sky.hdr"
    sky.write_hdr(str(hdr), make_test_image(64, 128))
    out_dir = tmp_path / "prev"

    result = run_cli(
        "preview", str(hdr), "--out-dir", str(out_dir), "--sweep", "0", "-4",
        "--montage", "--cube-faces", "--width", "128", "--face-size", "64",
    )

    assert result.returncode == 0, result.stderr
    for name in ("ev+0.png", "ev-4.png", "exposure_sweep.png", "cube_faces.png"):
        assert (out_dir / name).is_file()


def test_montage_labels_stay_inside_their_tile():
    from PIL import ImageDraw

    tiles = [
        ("短", np.zeros((32, 64, 3), dtype=np.float32)),
        ("很长很长的中英混排标签 with ASCII 也要能塞进去不许溢出", np.zeros((32, 64, 3), dtype=np.float32)),
    ]
    image = sky.montage(tiles, columns=2, title="标题同样不能超出画布宽度" * 4)

    draw = ImageDraw.Draw(image)
    for label, _ in tiles:
        text, fonts = sky.fit_mixed_text(draw, label, 64 - 8)
        assert sky.measure_mixed_text(draw, text, fonts) <= 64 - 8


def test_tonemap_output_is_in_display_range():
    image = make_test_image(16, 32)
    mapped = sky.tonemap_aces(image, ev=-2.0)
    assert mapped.min() >= 0.0 and mapped.max() <= 1.0
