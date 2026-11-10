#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""白平衡自动诊断：找中性参考区，量化色偏，给出修正量。

用法
----
    python auto_wb.py photo.jpg                      # 自动分块找候选中性区
    python auto_wb.py photo.jpg --ref 0.62,0.28,0.72,0.34
    python auto_wb.py photo.jpg --temp 5106 --tint 11

输出的三个数
------------
R-B           蓝黄轴。> +5 偏暖（该降色温），< -5 偏冷（该升色温）
G-(R+B)/2     绿品红轴。> +6 偏绿（该加 Tint），< -6 偏品红（该降 Tint）
饱和度        判断这个区能不能当参考（< 0.20 才可信）

为什么不能只看全图均值
----------------------
风景片天然有色偏（草地绿、天空蓝），全图均值必然偏。
必须找**真正的低饱和物体**：灰石、水泥路、非反射的白色表面。

三个一定会骗人的参考物
----------------------
1. 水面 / 玻璃 / 任何镜面 —— 反射天空就偏蓝，反射树叶就偏绿
2. 主体本身 —— 绿蛇、红叶、黄羽毛，饱和度就高，它的"中性像素"是它自己的高光
3. 天空 —— 本来就是蓝的
"""
import argparse
import os
import sys

try:
    from PIL import Image
    import numpy as np
except ImportError:
    sys.exit("需要 Pillow 与 numpy:  pip install pillow numpy")

# 经验斜率：R-B 每变化 1 需要 Temperature 变化多少 K
# 实测标定（Nikon NEF / Adobe 色彩引擎 / 5000K 附近）：57.5 K
K_PER_RB = 57.5
# 经验斜率：Tint 每 +1 让 G-(R+B)/2 大约下降多少
TINT_PER_G = 0.55


def load(path):
    im = Image.open(path).convert("RGB")
    return np.asarray(im).astype(np.float32), im.size


def stats(patch):
    R, G, B = patch[..., 0], patch[..., 1], patch[..., 2]
    mx = patch.max(axis=2)
    mn = patch.min(axis=2)
    sat = np.where(mx > 0, (mx - mn) / np.maximum(mx, 1e-6), 0.0)
    lum = 0.2126 * R + 0.7152 * G + 0.0722 * B
    return R, G, B, sat, lum


def probe(patch, sat_pct=30):
    """取该区域内饱和度最低的 sat_pct% 像素来统计（避开有色物体）。"""
    R, G, B, sat, lum = stats(patch)
    if sat.size == 0:
        return None
    thr = np.percentile(sat, sat_pct)
    m = sat <= thr
    if m.sum() < 50:
        return None
    r, g, b = float(R[m].mean()), float(G[m].mean()), float(B[m].mean())
    return {
        "n": int(m.sum()),
        "R": r, "G": g, "B": b,
        "rb": r - b,
        "gm": g - (r + b) / 2,
        "sat": float(sat[m].mean()),
        "lum": float(lum[m].mean()),
    }


def auto_scan(a, cols=6, rows=4, min_lum=45):
    """把画面切网格，逐块探测，按「饱和度低 + 亮度够」排序返回候选。"""
    H, W, _ = a.shape
    out = []
    for ry in range(rows):
        for rx in range(cols):
            x1, x2 = int(rx * W / cols), int((rx + 1) * W / cols)
            y1, y2 = int(ry * H / rows), int((ry + 1) * H / rows)
            p = probe(a[y1:y2, x1:x2])
            if p is None or p["lum"] < min_lum:
                continue
            p["box"] = (x1 / W, y1 / H, x2 / W, y2 / H)
            p["grid"] = (rx, ry)
            out.append(p)
    out.sort(key=lambda p: p["sat"])
    return out


def fmt_box(b):
    return "%.3f,%.3f,%.3f,%.3f" % b


# 场景光色先验：没有中性参考时的兜底
SCENE_PRIOR = {
    "sunny":    ("晴天正午直射", 5500, 6000, 5, 8),
    "overcast": ("阴天 / 开阔阴影", 6000, 6800, 5, 10),
    "forest":   ("林下散射（树冠过滤）", 5000, 5600, 8, 16),
    "sunset":   ("日出日落前后", 3200, 4500, 5, 15),
    "blue":     ("蓝调时刻", 7000, 10000, 0, 10),
    "tungsten": ("室内钨丝灯", 2800, 3200, 0, 8),
}


def reliable(p):
    """这个参考区能不能采信。饱和越低越可信。"""
    if p["sat"] < 0.15:
        return "high"
    if p["sat"] < 0.22:
        return "low"
    return "no"


def advice(p, temp, tint):
    lines = []
    d_rb = p["rb"]
    if abs(d_rb) >= 5:
        dk = -d_rb * K_PER_RB
        lines.append(
            "  R-B %+0.1f → %s %d K  →  建议 Temperature ≈ %d"
            % (d_rb, "偏暖，降" if d_rb > 0 else "偏冷，升", abs(dk), temp + dk)
        )
    else:
        lines.append("  R-B %+0.1f → 蓝黄轴已在可接受范围（±5）" % d_rb)

    d_gm = p["gm"]
    if abs(d_gm) >= 6:
        # G 偏低(d_gm<0) = 偏品红 → 要降 Tint；G 偏高 = 偏绿 → 要加 Tint
        dt = d_gm / TINT_PER_G
        lines.append(
            "  G-中 %+0.1f → %s %d  →  建议 Tint ≈ %d"
            % (d_gm, "偏绿，加" if d_gm > 0 else "偏品红，降", abs(dt), tint + dt)
        )
    else:
        lines.append("  G-中 %+0.1f → 绿品红轴已在可接受范围（±6）" % d_gm)
    return lines


def main():
    ap = argparse.ArgumentParser(description="白平衡自动诊断")
    ap.add_argument("image")
    ap.add_argument("--ref", help="参考区 x1,y1,x2,y2（归一化 0-1）")
    ap.add_argument("--temp", type=float, default=5106, help="当前色温，用于给绝对值建议")
    ap.add_argument("--tint", type=float, default=0, help="当前 Tint")
    ap.add_argument("--top", type=int, default=5, help="自动扫描时列出几个候选")
    ap.add_argument("--scene", choices=sorted(SCENE_PRIOR), help="按场景先验给值（无中性物时用）")
    args = ap.parse_args()

    if not os.path.isfile(args.image):
        sys.exit("找不到文件: %s" % args.image)

    a, (W, H) = load(args.image)
    print("图像 %dx%d  %s" % (W, H, os.path.basename(args.image)))

    if args.scene:
        nm, lo, hi, tlo, thi = SCENE_PRIOR[args.scene]
        print("\n场景先验：%s" % nm)
        print("  Temperature %d-%d K    Tint %d-%d" % (lo, hi, tlo, thi))
        print("  当前 %.0f K / Tint %.0f  →  %s" % (
            args.temp, args.tint,
            "在区间内" if lo <= args.temp <= hi and tlo <= args.tint <= thi
            else "不在区间内，考虑调整"))
        return

    if args.ref:
        try:
            x1, y1, x2, y2 = [float(v) for v in args.ref.split(",")]
        except ValueError:
            sys.exit("--ref 格式: x1,y1,x2,y2（0-1 小数）")
        patch = a[int(y1 * H):int(y2 * H), int(x1 * W):int(x2 * W)]
        p = probe(patch)
        if p is None:
            sys.exit("该区域样本不足")
        print("\n指定参考区 (%.3f,%.3f)-(%.3f,%.3f)" % (x1, y1, x2, y2))
        print("  R %6.1f  G %6.1f  B %6.1f   饱和度 %.3f  亮度 %.0f"
              % (p["R"], p["G"], p["B"], p["sat"], p["lum"]))
        print("  R-B %+6.1f    G-(R+B)/2 %+6.1f" % (p["rb"], p["gm"]))
        rel = reliable(p)
        if rel == "no":
            print("\n  ⚠ 饱和度 %.3f > 0.22，这不是中性物（有色物体/生物/植被）。" % p["sat"])
            print("  本区不给数值建议。换一个真正的灰/白表面，或用 --scene 走场景先验。")
        else:
            for line in advice(p, args.temp, args.tint):
                print(line)
            if rel == "low":
                print("\n  ⚠ 饱和度 %.3f 偏高，参考性弱，建议只取一半修正量。" % p["sat"])
        return

    # 自动扫描
    cands = auto_scan(a)
    if not cands:
        sys.exit("没找到可用的中性候选（画面可能整体偏暗或全是有色物体）")

    print("\n自动扫描：按饱和度从低到高，前 %d 个候选" % min(args.top, len(cands)))
    print("%-4s %-22s %-6s %-6s %-6s %-7s %-7s %s"
          % ("#", "区域", "R", "G", "B", "R-B", "G-中", "饱和"))
    for i, p in enumerate(cands[:args.top], 1):
        print("%-4d %-22s %-6.1f %-6.1f %-6.1f %-+7.1f %-+7.1f %.3f"
              % (i, fmt_box(p["box"]), p["R"], p["G"], p["B"], p["rb"], p["gm"], p["sat"]))
        if i == 1:
            best = p

    rel = reliable(best)
    print("\n最可信候选（#1，饱和最低）—— 可信度: %s" % rel)
    if rel == "no":
        print("  ⚠ 全图最低饱和也有 %.3f，说明**这张照片没有可靠的中性参考物**。" % best["sat"])
        print("  多为森林 / 草原 / 大量植被的场景。这种情况下不要用像素统计定白平衡，")
        print("  改用场景先验：")
        print("  " + "  ".join("%s %s %d-%dK Tint %d-%d" % (k, v[0], v[1], v[2], v[3], v[4])
                              for k, v in SCENE_PRIOR.items()))
        print("  然后用 --scene 参数按先验取值，并靠视觉微调。")
    else:
        for line in advice(best, args.temp, args.tint):
            print(line)
        if rel == "low":
            print("\n  ⚠ 饱和偏高，参考性弱，建议只取一半修正量。")

    print("\n⚠ 用之前先确认这个区是什么物体，三种情况结论作废：")
    print("   水面/玻璃/镜面反射、天空、主体本身（有色生物/植物）")
    print("   如果是，换一个区用 --ref 重测，或改用 --scene 场景先验。")


if __name__ == "__main__":
    main()
