#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""算径向蒙版的安全几何，或体检已有几何够不够。

**为什么需要这个**：星形主体（花瓣、叶尖、刺）的尖端常常落在椭圆的羽化带里，
肉眼看"框完全盖住了花"，实际力度只剩三成。实测一张山丹：
椭圆是包围盒外扩的，`EV −0.26` 却只把红通道溢出从 36% 压到 34%。

羽化模型（线性向内衰减，与 LR 的观感一致）::

    alpha(r) = clamp((1 - r) / (feather / 100), 0, 1)
    r = sqrt((dx/a)^2 + (dy/b)^2)      # 归一化椭圆半径，中心处 r=0，边缘 r=1

于是"所有尖端都不低于 alpha"等价于"最大 r ≤ 1 − feather/100 × alpha"。
feather 40、要求 alpha ≥ 0.9 时，尖端必须落在 r ≤ 0.64 以内——
这比凭眼睛估的 0.85 严格得多，而那 0.85 正是翻车的地方。

用法::

    # 1) 给一张主体掩膜，算安全几何
    python scripts/mask_fit.py --mask subj.png --feather 35

    # 2) 没有掩膜，只给包围盒（保守，按四个角算）
    python scripts/mask_fit.py --bbox 0.24 0.30 0.46 0.56 --feather 35

    # 3) 体检已有 spec：哪些层的尖端被羽化吃掉了
    python scripts/mask_fit.py --mask subj.png --spec layers.json

掩膜来自哪：BiRefNet（主体）、LR 导出的蒙版、或按色相阈值临时划一块。
`--mask` 读灰度 PNG/JPG，>127 视为主体。
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import numpy as np

try:
    from PIL import Image
except ImportError:  # pragma: no cover
    Image = None


def _alpha(r, feather, target=None):
    f = max(float(feather), 0.0) / 100.0
    if f <= 1e-6:
        return (r <= 1.0).astype(float)
    a = (1.0 - r) / f
    return np.clip(a, 0.0, 1.0)


def _points_from_mask(path):
    """返回 (归一化坐标数组 Nx2, bbox)。"""
    if Image is None:
        raise SystemExit("需要 Pillow：pip install pillow")
    m = np.asarray(Image.open(path).convert("L"))
    h, w = m.shape
    ys, xs = np.nonzero(m > 127)
    if len(xs) == 0:
        raise SystemExit("掩膜是空的（阈值 >127 没有像素）")
    pts = np.stack([xs / w, ys / h], axis=1)
    bbox = (xs.min() / w, ys.min() / h, xs.max() / w, ys.max() / h)
    return pts, bbox


def _points_from_bbox(b):
    x0, y0, x1, y1 = b
    return np.array([[x0, y0], [x1, y0], [x0, y1], [x1, y1]], dtype=float), tuple(b)


def fit(pts, bbox, feather, target=0.9):
    """求让所有点都达到 target alpha 的最小椭圆。"""
    x0, y0, x1, y1 = bbox
    cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
    hw, hh = max((x1 - x0) / 2.0, 1e-6), max((y1 - y0) / 2.0, 1e-6)
    k = hw / hh                      # 长宽比锁定成包围盒的比例
    u = pts[:, 0] - cx
    v = pts[:, 1] - cy
    s = np.sqrt(u * u + (k * v) ** 2)
    s_max = float(s.max())
    R = 1.0 - (max(feather, 0.0) / 100.0) * target
    R = max(R, 0.15)                 # 羽化 100 时退化成同心渐变，兜个底
    a = s_max / R
    b = a / k
    return dict(lt=(cx - a, cy - b), rb=(cx + a, cy + b),
                a=a, b=b, center=(cx, cy), r_max=s_max / a, R=R)


def audit(layer, pts, target=0.8):
    """给一层的几何，算主体点上的 alpha 分布。

    只对"整片覆盖主体"的层有意义。只画眼睛、只画下颌这类局部层，
    主体点在它们外面本来就该是 0，硬算会得出一堆假警报——
    所以先看这层能不能容纳 85% 以上的主体点，不能就返回 None。
    """
    g = layer.get("geom") or {}
    if g.get("kind") != "radial":
        return None
    if layer.get("ai"):
        # 有 AI 蒙版打底时，形状由 AI 决定，径向只是裁剪框；
        # 边缘软一点无害，不属于第 42 条那个问题。
        return dict(skip=True, inside=0.0, feather=g.get("feather", 0), reason="AI 打底")
    lt, rb, fe = g.get("lt"), g.get("rb"), g.get("feather", 0)
    if not lt or not rb:
        return None
    cx, cy = (lt[0] + rb[0]) / 2.0, (lt[1] + rb[1]) / 2.0
    a = max((rb[0] - lt[0]) / 2.0, 1e-6)
    b = max((rb[1] - lt[1]) / 2.0, 1e-6)
    u = (pts[:, 0] - cx) / a
    v = (pts[:, 1] - cy) / b
    r = np.sqrt(u * u + v * v)
    inside = float((r <= 1.0).mean())
    if inside < 0.85:
        return dict(skip=True, inside=inside, feather=fe)
    al = _alpha(r, fe)
    return dict(skip=False, r_max=float(r.max()), alpha_min=float(al.min()),
                alpha_mean=float(al.mean()), weak=float((al < target).mean()),
                feather=fe, inside=inside)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mask", help="主体掩膜（灰度图，>127 为主体）")
    ap.add_argument("--bbox", nargs=4, type=float, metavar=("X0", "Y0", "X1", "Y1"),
                    help="主体包围盒，归一化坐标")
    ap.add_argument("--feather", type=float, default=40.0, help="打算用的羽化值（默认 40）")
    ap.add_argument("--alpha", type=float, default=0.9, help="尖端至少要达到的力度（默认 0.9）")
    ap.add_argument("--tolerance", type=float, default=0.05,
                    help="体检时可接受的偏弱像素占比（默认 0.05，即 5%%）")
    ap.add_argument("--spec", help="体检模式：已有的层定义 JSON")
    a = ap.parse_args()

    if a.mask:
        pts, bbox = _points_from_mask(a.mask)
        src = "掩膜 %s" % os.path.basename(a.mask)
    elif a.bbox:
        pts, bbox = _points_from_bbox(a.bbox)
        src = "包围盒"
    else:
        raise SystemExit("需要 --mask 或 --bbox 之一")

    print("主体来源：%s" % src)
    print("包围盒   x %.3f–%.3f   y %.3f–%.3f   （宽 %.3f 高 %.3f）"
          % (bbox[0], bbox[2], bbox[1], bbox[3], bbox[2] - bbox[0], bbox[3] - bbox[1]))

    f = fit(pts, bbox, a.feather, a.alpha)
    hw = max((bbox[2] - bbox[0]) / 2.0, 1e-6)
    scale = f["a"] / hw
    print("羽化 %g、要求尖端 alpha≥%.2f  →  尖端必须落在 r ≤ %.2f（凭眼睛估会以为是 0.85）"
          % (a.feather, a.alpha, f["R"]))
    print()
    print("安全几何：")
    print('  "geom": {"kind": "radial", "lt": [%.3f, %.3f], "rb": [%.3f, %.3f], '
          '"feather": %g}' % (f["lt"][0], f["lt"][1], f["rb"][0], f["rb"][1], a.feather))
    print("  椭圆长轴 ≈ 包围盒的 %.2f 倍" % scale)
    if scale > 1.8:
        print("  ⚠ 这个倍数压到画面上会很明显。三个选择：把 feather 降到 %d 左右、"
              % max(int(a.feather * 0.5), 8))
        print("    把 --alpha 放宽到 0.7（尖端略弱但通常看不出），或者改用「主体 ∩ 几何」的布尔层。")
        print("    实心团块（兽身、石头）的包围盒四角本来就是极端值，模型偏保守；")
        print("    星形（花、叶、刺）没有这个问题，报出来的倍数就是真实需要的。")

    if a.spec:
        print("\n=== 体检 %s ===" % os.path.basename(a.spec))
        specs = json.load(open(a.spec, encoding="utf-8"))
        bad = skipped = checked = warn = 0
        for sp in specs:
            res = audit(sp, pts)
            if res is None:
                continue
            if res.get("skip"):
                skipped += 1
                why = res.get("reason") or "只覆盖主体 %.0f%%，是局部层（眼睛/下颌/受光面这类）" % (res["inside"] * 100)
                print("  跳过 %-26s %s，不适用" % (sp.get("name", "?"), why))
                continue
            weak = res["weak"]
            if weak <= a.tolerance * 0.4:
                verdict = "OK  "
            elif weak <= a.tolerance:
                verdict = "临界"
            else:
                verdict = "不够"
            bad += 0 if verdict == "OK  " else (1 if verdict == "不够" else 0)
            warn += 1 if verdict == "临界" else 0
            checked += 1
            print("  %s %-26s feather%-4g r_max %.2f  alpha 最低 %.2f 均值 %.2f  偏弱 %.1f%%"
                  % (verdict, sp.get("name", "?"), res["feather"],
                     res["r_max"], res["alpha_min"], res["alpha_mean"], weak * 100))
        if bad:
            print("\n有 %d 层尖端落在羽化带里：按上面的安全几何放大 lt/rb，"
                  "或把 feather 降到 %d 左右。" % (bad, max(int(a.feather * 0.6), 8)))
        elif checked == 0:
            print("\n这份 spec 里没有「纯几何」的径向层，没有需要体检的对象。")
        else:
            tail = "，%d 层临界（可用，但尖端已经掉到七成力度）" % warn if warn else ""
            skip_tail = "；另有 %d 个局部层未参与" % skipped if skipped else ""
            print("\n%d 个几何层体检完毕%s%s。" % (checked, tail, skip_tail))
    return 0


if __name__ == "__main__":
    sys.exit(main())
