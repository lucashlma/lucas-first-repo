#!/usr/bin/env python3
"""拿一张真实 HDRI 当基准真值，验证 sky_to_hdr 的整条重建管线。

这个脚本需要外部素材，所以不放进离线测试套件里，单独跑：

    curl -O https://dl.polyhaven.org/file/ph-assets/HDRIs/hdr/1k/kloofendal_43d_clear_1k.hdr
    python validate_against_real_hdri.py kloofendal_43d_clear_1k.hdr --out-dir out

做四件事：

1. 用本工具的解码器读这张第三方生产文件，并和 OpenCV 的 Radiance 解码器逐位比对；
2. 用 UE 导入兼容性检查过一遍——这类文件本来就是给 UE 用的，检查不该把它判死；
3. 本工具写出去再读回来，确认误差不超过 RGBE 的量化步长；
4. 把真值模拟成一张 8 bit 照片（乘曝光、sRGB 编码、削顶、量化），再跑一遍
   LDR -> HDR 重建，和真值做定量对比，并出一张曝光扫描对比图。

第 4 步是重点：能拿到真值，就能说清重建到底恢复了什么、没恢复什么。
"""

from __future__ import annotations

import argparse
import math
import os
import sys
import unicodedata

import numpy as np

import sky_to_hdr as sky

EV_SWEEP = (0.0, -4.0, -8.0, -12.0)


def angular_error(a: tuple[float, float], b: tuple[float, float]) -> float:
    dot = float(np.dot(sky.azel_to_direction(*a), sky.azel_to_direction(*b)))
    return math.degrees(math.acos(max(-1.0, min(1.0, dot))))


def describe(name: str, image: np.ndarray) -> dict:
    lum = image.astype(np.float64) @ sky.LUMA
    positive = lum[lum > 0]
    ambient = sky.solid_angle_weighted_mean(image)
    return {
        "名称": name,
        "峰值亮度": float(lum.max()),
        "动态范围档数": float(np.log2(lum.max() / np.percentile(positive, 5))),
        "环境光亮度": float(ambient @ sky.LUMA),
        "太阳方向": sky.detect_sun(image),
    }


def pad(text: str, width: int, align: str = "<") -> str:
    """按终端显示宽度补空格：中文是双宽字符，直接用 f-string 对不齐。"""
    display = sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in text)
    filler = " " * max(0, width - display)
    return text + filler if align == "<" else filler + text


def print_table(rows: list[dict], truth: dict) -> None:
    columns = [("", 28), ("峰值亮度", 12), ("动态范围", 10), ("环境光", 10),
               ("环境光误差", 12), ("太阳偏差", 10)]
    print("  " + "".join(pad(name, width, ">") for name, width in columns))
    print("  " + "-" * sum(width for _, width in columns))
    for row in rows:
        ambient_error = (row["环境光亮度"] - truth["环境光亮度"]) / truth["环境光亮度"] * 100
        cells = [
            pad(row["名称"], 28),
            pad(f"{row['峰值亮度']:,.0f}", 12, ">"),
            pad(f"{row['动态范围档数']:.1f} 档", 10, ">"),
            pad(f"{row['环境光亮度']:.4f}", 10, ">"),
            pad(f"{ambient_error:+.1f}%", 12, ">"),
            pad(f"{angular_error(row['太阳方向'], truth['太阳方向']):.2f} 度", 10, ">"),
        ]
        print("  " + "".join(cells))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("hdri", help="真实的 .hdr 文件")
    parser.add_argument("--out-dir", default="out")
    parser.add_argument("--knee", type=float, default=0.85)
    parser.add_argument("--peak", type=float, default=16.0)
    parser.add_argument("--sun-intensity", type=float, default=2000.0)
    parser.add_argument("--sun-radius", type=float, default=1.5)
    parser.add_argument("--headroom-percentile", type=float, default=99.7,
                        help="模拟拍摄时把这个分位的亮度顶到削顶边缘，也就是「按高光曝光」")
    parser.add_argument("--tile-width", type=int, default=384)
    args = parser.parse_args(argv)
    os.makedirs(args.out_dir, exist_ok=True)

    print(f"\n=== 1. 解码这张第三方生产文件: {args.hdri} ===")
    truth = sky.read_hdr(args.hdri)
    print(f"  {truth.shape[1]}x{truth.shape[0]}，峰值亮度 {float((truth @ sky.LUMA).max()):,.0f}")
    try:
        import cv2

        theirs = cv2.imread(args.hdri, cv2.IMREAD_ANYDEPTH | cv2.IMREAD_COLOR)
        assert theirs is not None, "OpenCV 没读出来"
        identical = np.array_equal(truth, theirs[:, :, ::-1].astype(np.float32))
        print(f"  与 OpenCV 的 Radiance 解码器逐位一致: {identical}")
        assert identical, "解码结果和 OpenCV 不一致"
    except ImportError:
        print("  跳过 OpenCV 交叉验证（没装 opencv）")

    print("\n=== 2. UE 导入兼容性检查 ===")
    result = sky.check_hdr_for_ue(args.hdri)
    print(f"  结论: {'通过' if result.ok else '失败'}")
    print(f"  错误: {result.errors or '无'}")
    print(f"  警告: {result.warnings or '无'}")
    assert result.ok, "检查器把一个真实可用的 HDRI 判死了，说明检查过严"

    print("\n=== 3. 写出去再读回来 ===")
    roundtrip_path = os.path.join(args.out_dir, "roundtrip.hdr")
    sky.write_hdr(roundtrip_path, truth)
    back = sky.read_hdr(roundtrip_path)
    step = truth.max(axis=-1, keepdims=True) / 128.0 + 1e-6
    worst = float((np.abs(back - truth) / step).max())
    print(f"  最大误差 / RGBE 量化步长 = {worst:.4f}（应 <= 1）")
    print(f"  文件大小 {os.path.getsize(args.hdri) / 1e6:.2f} MB -> "
          f"{os.path.getsize(roundtrip_path) / 1e6:.2f} MB")
    assert worst <= 1.0, "往返误差超过量化步长"
    assert sky.check_hdr_for_ue(roundtrip_path).ok

    print("\n=== 4. 模拟 8 bit 拍摄，再跑一遍重建 ===")
    # 按高光曝光：把 99.7 分位顶到削顶边缘，模拟一张正常拍摄的天空照片
    # （只有日面和它周围一圈过曝）。
    exposure = 1.0 / float(np.percentile(truth @ sky.LUMA, args.headroom_percentile))
    reference = truth * exposure
    display = np.clip(sky.linear_to_srgb(reference), 0.0, 1.0)
    photo = sky.srgb_to_linear(np.round(display * 255.0) / 255.0)
    clipped = float((reference.max(axis=2) > 1.0).mean() * 100)
    print(f"  曝光 x{exposure:.4g}，{clipped:.2f}% 的像素削顶")
    sky.save_png(os.path.join(args.out_dir, "simulated_photo.png"), display)

    expanded = sky.expand_highlights(photo, knee=args.knee, peak=args.peak)
    azimuth, elevation = sky.detect_sun(photo)
    truth_azimuth, truth_elevation = sky.detect_sun(reference)
    print(f"  真值里的太阳:      方位角 {truth_azimuth:.1f} 度，仰角 {truth_elevation:.1f} 度")
    print(f"  8 bit 照片里定位到: 方位角 {azimuth:.1f} 度，仰角 {elevation:.1f} 度"
          f"（偏差 {angular_error((azimuth, elevation), (truth_azimuth, truth_elevation)):.2f} 度）")
    rebuilt = sky.add_sun(expanded, azimuth, elevation, radius_deg=args.sun_radius,
                          intensity=args.sun_intensity)

    truth_stats = describe("真值 HDRI", reference)
    rows = [
        truth_stats,
        describe("模拟 8 bit 照片", photo),
        describe("重建：只做高光扩展", expanded),
        describe("重建：高光扩展 + 太阳盘", rebuilt),
    ]
    print()
    print_table(rows, truth_stats)

    print("\n=== 5. 出曝光扫描对比图 ===")
    images = (reference, photo, expanded, rebuilt)
    tiles = []
    for row, image in zip(rows, images):
        for ev in EV_SWEEP:
            preview = sky.resize_srgb(sky.tonemap_aces(image, ev), args.tile_width)
            tiles.append((f"{row['名称']}  EV {ev:+g}", preview))
    montage_path = os.path.join(args.out_dir, "ground_truth_comparison.png")
    sky.montage(
        tiles, columns=len(EV_SWEEP),
        title=f"以真实 HDRI 为基准的曝光扫描对比（{os.path.basename(args.hdri)}）："
              "真值 / 模拟 8 bit 照片 / 逐步重建",
    ).save(montage_path)
    print(f"  {montage_path}")

    faces = [
        (face, sky.tonemap_aces(sky.extract_cube_face(rebuilt, face, 256), -1.0))
        for face in sky.CUBE_FACES
    ]
    faces_path = os.path.join(args.out_dir, "cube_faces.png")
    sky.montage(faces, columns=3, title="重建结果的立方体六面：+Z 是天顶，-Z 是地面").save(faces_path)
    print(f"  {faces_path}")

    print("\n全部通过。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
