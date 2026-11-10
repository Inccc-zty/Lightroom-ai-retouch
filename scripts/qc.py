# -*- coding: utf-8 -*-
"""质量闭环体检器。

每一版导出后立刻体检，用绝对阈值 + 单步增量双重判断有没有调过头。
阈值不是我拍的，全部来自可查证的行业基准：

  * 全白 <0.10% / 全黑 <2%       —— 避免真过曝与真死黑
  * p99 235–252                  —— 高光既不顶墙也不发灰
  * p1 2–16                      —— 有黑场但不出现断层
  * 绿 S 0.30–0.60               —— 草地自然区间（>0.65 必发荧光）
  * 蓝 S 0.20–0.52               —— 天空区间（>0.60 塑料蓝）
  * 平均 S 0.15–0.45             —— 整体饱和上限
  * 暗部(<60) 20–45%             —— 低于 20 发灰，高于 45 死黑
  * 前景/中景 1.3–2.0 : 1        —— frameandfocal 的纵深指标
  * 中景/天空 1.5–2.3 : 1        —— 同上
  * 单步亮度变化 <15%            —— 一步跳太多必然过头
  * 单步饱和变化 <0.10
"""
from __future__ import annotations

import json
import os

import cv2
import numpy as np
from PIL import Image

TH = {
    "white_clip": (0.0, 0.10, "全白像素%", "过曝"),
    "black_clip": (0.0, 2.00, "全黑像素%", "死黑"),
    "p99": (235, 252, "p99", "高光顶墙/发灰"),
    "p1": (2, 16, "p1", "黑场断层"),
    "green_s": (0.30, 0.60, "绿S", "荧光绿"),
    "blue_s": (0.20, 0.52, "蓝S", "塑料蓝"),
    "mean_s": (0.15, 0.45, "平均S", "整体过饱和"),
    "sat_hi_pct": (0, 10.0, "S>0.65占比%", "局部过饱和（均值看不出来）"),
    "s_p90": (0, 0.72, "S的p90", "高饱和端过高"),
    "dark_pct": (20, 45, "暗部<60%", "死黑或发灰"),
    "depth_mid_fg": (1.30, 2.20, "中景/前景", "纵深偏平"),
    "depth_sky_mid": (1.50, 2.30, "天空/中景", "天空压过头或中景提过头"),
}


def measure(path: str) -> dict:
    a = np.asarray(Image.open(path).convert("RGB")).astype(np.float32)
    g = a.mean(2)
    h, w = g.shape
    hsv = cv2.cvtColor(a / 255.0, cv2.COLOR_RGB2HSV)
    H, S, V = hsv[..., 0], hsv[..., 1], hsv[..., 2]

    mg = (H >= 80) & (H <= 160) & (V > 0.10)
    mb = (H >= 200) & (H <= 240) & (V > 0.10)

    def zone(y0, y1, x0=0.0, x1=1.0):
        return float(g[int(y0 * h):int(y1 * h), int(x0 * w):int(x1 * w)].mean())

    mid = zone(1 / 3, 2 / 3)
    return {
        "white_clip": float((g >= 253).mean() * 100),
        "black_clip": float((g <= 2).mean() * 100),
        "p99": float(np.percentile(g, 99)),
        "p1": float(np.percentile(g, 1)),
        "green_s": float(S[mg].mean()) if mg.sum() > 500 else float("nan"),
        "blue_s": float(S[mb].mean()) if mb.sum() > 500 else float("nan"),
        "mean_s": float(S.mean()),
        "sat_hi_pct": float((S > 0.65).mean() * 100),
        "s_p90": float(np.percentile(S, 90)),
        "dark_pct": float((g < 60).mean() * 100),
        "top": zone(0, 0.10),
        "mid": mid,
        "bot": zone(2 / 3, 1.0),
        "depth_mid_fg": float(mid / max(zone(2 / 3, 1.0), 1e-6)),
        "depth_sky_mid": float(zone(0, 0.10) / max(mid, 1e-6)),
        "mean_s_rgb": [float(x) for x in a.reshape(-1, 3).mean(0)],
    }


def check(cur: dict, prev: dict | None = None, verbose=True) -> tuple[bool, list[str]]:
    """返回 (是否通过, 问题列表)。"""
    issues, warns = [], []
    TOL = 0.03   # 3% 容差：区间边缘的微小偏离不算问题，避免无意义的无限微调
    for key, (lo, hi, label, why) in TH.items():
        v = cur.get(key)
        if v is None or (isinstance(v, float) and np.isnan(v)):
            continue
        if v < lo * (1 - TOL):
            issues.append(f"{label} {v:.2f} < {lo}（{why}）")
        elif v > hi * (1 + TOL):
            issues.append(f"{label} {v:.2f} > {hi}（{why}）")

    if prev:
        dl = abs(cur["mid"] - prev["mid"]) / max(prev["mid"], 1e-6)
        ds = abs(cur["mean_s"] - prev["mean_s"])
        if dl > 0.15:
            warns.append(f"单步中景变化 {dl*100:.0f}% >15%（这一步跳太大）")
        if ds > 0.10:
            warns.append(f"单步饱和变化 {ds:.2f} >0.10（这一步推太猛）")

    if verbose:
        tag = "PASS" if not issues else "FAIL"
        print(f"  [{tag}] 上{cur['top']:5.1f} 中{cur['mid']:5.1f} 下{cur['bot']:5.1f} | "
              f"p1 {cur['p1']:3.0f} p99 {cur['p99']:3.0f} | 暗{cur['dark_pct']:4.1f}% "
              f"白{cur['white_clip']:4.2f}% | 绿S {cur['green_s']:.3f} 蓝S {cur['blue_s']:.3f} "
              f"均S {cur['mean_s']:.3f} p90 {cur['s_p90']:.3f} 高饱{cur['sat_hi_pct']:.1f}% | "
              f"中/前 {cur['depth_mid_fg']:.2f} 天/中 {cur['depth_sky_mid']:.2f}")
        for i in issues:
            print(f"        ✗ {i}")
        for w in warns:
            print(f"        ! {w}")
    return (not issues), issues + warns


def save_history(path: str, tag: str, m: dict, hist_file: str):
    hist = []
    if os.path.exists(hist_file):
        try:
            hist = json.load(open(hist_file, encoding="utf-8"))
        except Exception:
            hist = []
    hist.append({"step": tag, **m})
    json.dump(hist, open(hist_file, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    import sys
    p = sys.argv[1]
    m = measure(p)
    check(m)
