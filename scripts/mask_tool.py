#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""追加蒙版层（AI 主体 / 反相背景 / 布尔相交），带备份与回读校验。

spec 是一个 JSON 数组，每项：

    name   层名（建议带序号，如 "07 红花·回收溢出"）
    ai     "subject" | "sky" | null      AI 蒙版打底
    invert true/false                    反相（背景用 true）
    geom   null 或 {"kind": "radial" | "linear", ...}
    op     intersect | subtract | add    （ai 与 geom 同时存在时生效）
    ev / clarity / texture / sat / temp / tint / contrast / highlights /
    shadows / whites / blacks / dehaze    LR 语义，直接填界面上的数字

radial 几何：{"kind":"radial", "lt":[x0,y0], "rb":[x1,y1], "feather":40, "mid":50}
            坐标是 0–1 归一化，允许超出画面（负数、>1 都行）
linear 几何：{"kind":"linear", "zero":[x,y], "full":[x,y]}
            zero 点是强度为 0 的位置，full 点是强度为 1 的位置

**写 radial 之前先跑 mask_fit.py**：星形主体（花瓣、叶尖）的尖端很容易落进
羽化带，实际力度只剩三成。详见 references/pitfalls.md 第 42 条。

用法::

    # 先看要写什么（dry-run）
    python scripts/mask_tool.py --path "/path/to/photo.NEF" --spec layers.json
    # 确认无误再写
    python scripts/mask_tool.py --path "/path/to/photo.NEF" --spec layers.json --apply
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from lr_masks import build_layer, _ai_mask, _geom_mask  # noqa: E402
import lr_bridge  # noqa: E402

EV_TO_LOCAL = 1.0 / 4.5

PARAM_FIELDS = (
    ("highlights", "LocalHighlights2012"), ("shadows", "LocalShadows2012"),
    ("whites", "LocalWhites2012"), ("blacks", "LocalBlacks2012"),
    ("contrast", "LocalContrast2012"), ("clarity", "LocalClarity2012"),
    ("texture", "LocalTexture"), ("dehaze", "LocalDehaze"),
    ("sat", "LocalSaturation"), ("temp", "LocalTemperature"),
    ("tint", "LocalTint"), ("sharp", "LocalSharpness"),
)


def denest(flat):
    """把 dump 出来的扁平键（p1.MaskGroupBasedCorrections.3.LocalExposure2012）
    还原成 {层号: {字段: 值}} 的嵌套结构。"""
    layers = {}
    for k, v in flat.items():
        if not k.startswith("p1."):
            continue
        seg = k[3:].split(".")
        if seg[0] != "MaskGroupBasedCorrections":
            continue
        node = layers
        cur = node
        for s in seg[1:]:
            if s not in cur:
                cur[s] = {}
            cur = cur[s]
        cur["__value"] = v
    return {i: _unwrap(node) for i, node in layers.items()}


def _unwrap(node):
    if isinstance(node, dict) and "__value" in node and len(node) == 1:
        return node["__value"]
    return {k: _unwrap(v) for k, v in node.items()}


def build(ai, invert, geom, op):
    """按 (AI 蒙版, 几何) 组合出 CorrectionMasks 字典。

    布尔相交靠 A ∩ B = A − ¬B：第二蒙版 MaskBlendMode=1 + MaskInverted=true。
    LR 的 MaskBlendMode 只有 0（添加）和 1（减去）有效，2/3/4 会被归零。
    """
    masks = {}
    idx = 1
    if ai:
        m = _ai_mask(ai, 1)
        m["MaskInverted"] = bool(invert)
        m["MaskBlendMode"] = 0.0
        masks[str(idx)] = m
        idx += 1
    if geom:
        g = _geom_mask(geom)
        if ai:
            if op == "intersect":
                g["MaskBlendMode"] = 1.0
                g["MaskInverted"] = True
            elif op == "subtract":
                g["MaskBlendMode"] = 1.0
                g["MaskInverted"] = False
            else:  # add
                g["MaskBlendMode"] = 0.0
                g["MaskInverted"] = bool(geom.get("invert", False))
        else:
            g["MaskBlendMode"] = 0.0
            g["MaskInverted"] = bool(geom.get("invert", False))
        masks[str(idx)] = g
    return masks


def make_layer(name, tpl, spec):
    grp = build_layer(tpl, name, {"kind": "radial", "lt": (0, 0), "rb": (1, 1)}, (0.5, 0.5))
    # 模板继承会把上一层的 clarity/sat/temp 带过来（实测踩过），先全部归零
    for k in list(grp):
        if k.startswith("Local"):
            grp[k] = 0.0
    grp["LocalCurveRefineSaturation"] = 100.0
    grp["CorrectionMasks"] = build(
        spec.get("ai"), spec.get("invert", False), spec.get("geom"), spec.get("op", "intersect")
    )
    if "ev" in spec:
        grp["LocalExposure2012"] = spec["ev"] * EV_TO_LOCAL
    for key, field in PARAM_FIELDS:
        if key in spec:
            grp[field] = spec[key] / 100.0
    return grp


DEFAULT_TPL = {
    "LocalExposure2012": 0.0, "LocalContrast2012": 0.0, "LocalHighlights2012": 0.0,
    "LocalShadows2012": 0.0, "LocalWhites2012": 0.0, "LocalBlacks2012": 0.0,
    "LocalClarity2012": 0.0, "LocalTexture": 0.0, "LocalDehaze": 0.0,
    "LocalSaturation": 0.0, "LocalTemperature": 0.0, "LocalTint": 0.0,
    "LocalSharpness": 0.0, "LocalBrightness": 0.0, "LocalHue": 0.0,
    "LocalLuminanceNoise": 0.0, "LocalGrain": 0.0, "LocalMoire": 0.0,
    "LocalDefringe": 0.0, "LocalToningHue": 0.0, "LocalToningSaturation": 0.0,
    "LocalCurveRefineSaturation": 100.0,
}


def dump_layers(photo):
    flat = lr_bridge.send(
        "develop_dump", [("path.1", "s", photo), ("filter", "s", "MaskGroup")], timeout=60
    )
    return denest(flat)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--path", required=True, help="照片完整路径（必填，不许靠当前选中）")
    ap.add_argument("--spec", required=True, help="层定义 JSON")
    ap.add_argument("--apply", action="store_true", help="不加只做 dry-run")
    args = ap.parse_args()

    photo = args.path
    layers = dump_layers(photo)
    start = max((int(k) for k in layers), default=0) + 1
    specs = json.load(io.open(args.spec, encoding="utf-8"))
    tpl = layers[str(start - 1)] if start > 1 else DEFAULT_TPL

    new = {}
    for i, spec in enumerate(specs):
        idx = str(start + i)
        new[idx] = make_layer(spec["name"], tpl, spec)
        print("  %-3s %-26s EV=%+.2f" % (idx, spec["name"], new[idx].get("LocalExposure2012", 0) * 4.5))

    merged = dict(layers)
    merged.update(new)
    merged = {k: merged[k] for k in sorted(merged, key=int)}

    if not args.apply:
        print("[dry-run] 共 %d 层（新增 %d）" % (len(merged), len(new)))
        return 0

    bak = os.path.splitext(photo)[0] + "_masks_backup.json"
    json.dump({"MaskGroupBasedCorrections": {k: layers[k] for k in sorted(layers, key=int)}},
              io.open(bak, "w", encoding="utf-8"), ensure_ascii=False)
    tree_file = os.path.splitext(photo)[0] + "_masks_tree.json"
    json.dump({"MaskGroupBasedCorrections": merged}, io.open(tree_file, "w", encoding="utf-8"),
              ensure_ascii=False)
    print("备份：%s" % bak)

    res = lr_bridge.send_tree("develop_set_tree", {"MaskGroupBasedCorrections": merged},
                              [photo], timeout=180)
    if not res.get("ok"):
        print("写入失败：%s" % res.get("err"))
        return 1

    after = dump_layers(photo)
    print("回读 %d 层" % len(after))
    bad = []
    for k, lay in new.items():
        got = after.get(k, {})
        for f in ("LocalExposure2012", "LocalClarity2012", "LocalTexture", "LocalSaturation"):
            want = lay.get(f, 0.0)
            have = got.get(f, 0.0) or 0.0
            if abs(float(want) - float(have)) > 1e-4:
                bad.append((k, f, want, have))
    print("字段校验：%s" % (bad or "全部一致"))
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
