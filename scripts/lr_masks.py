# -*- coding: utf-8 -*-
"""把「明暗塑形派」的分区方案直接写进 Lightroom。

前置结论（实测）：
  1. applyDevelopSettings 只在照片已有 MaskGroupBasedCorrections 键时才接受写入，
     所以照片上至少要保留一个蒙版（哪怕零效果）作为入口。
  2. 局部参数键名是 LocalExposure2012 / LocalHighlights2012 / LocalClarity2012 …
     不是 Exposure2012，也不是 LightroomForge 文档里的 local_ 前缀。
  3. 量纲：LocalExposure2012 = EV / 4.5（实测 -1.0 ≈ -4.5EV）；
     其余参数 -100..100 一律 /100。
  4. 线性渐变：Zero 端是零值，Full 端是满值（这点最容易搞反）。
  5. 径向渐变：What = "Mask/CircularGradient"，配 Left/Top/Right/Bottom/
     Angle/Midpoint/Feather/Roundness/Flipped。
"""
from __future__ import annotations

import argparse
import io
import json
import uuid

import numpy as np

EV_TO_LOCAL = 1.0 / 4.5

# 以下路径由 CLI 传入，不再硬编码。模板取任意一张已有蒙版的照片 dump，
# 作用是拿到一套完整的 Local* 默认键，避免写进半套字段。
BRIDGE = None
PHOTO = None
TEMPLATE = None
EV_TO_LOCAL = 1.0 / 4.5


def g():
    return str(uuid.uuid4()).upper()


def _local_defaults(tpl):
    out = {}
    for k, v in tpl.items():
        if k.startswith("Local"):
            out[k] = v
    return out


def build_layer(tpl, name, mask, ref=(0.5, 0.5), **params):
    """构造一个蒙版组。params 用 LR 语义：ev / highlights / shadows / clarity / sat …"""
    grp = {
        "CorrectionActive": True,
        "CorrectionAmount": 1.0,
        "CorrectionID": g(),
        "CorrectionName": name,
        "CorrectionReferenceX": ref[0],
        "CorrectionReferenceY": ref[1],
        "CorrectionSyncID": g(),
        "What": "Correction",
    }
    grp.update(_local_defaults(tpl))
    grp["LocalCurveRefineSaturation"] = 100.0

    if "ev" in params:
        grp["LocalExposure2012"] = params["ev"] * EV_TO_LOCAL
    for key, field in (("highlights", "LocalHighlights2012"), ("shadows", "LocalShadows2012"),
                       ("blacks", "LocalBlacks2012"), ("whites", "LocalWhites2012"),
                       ("contrast", "LocalContrast2012"), ("clarity", "LocalClarity2012"),
                       ("texture", "LocalTexture"), ("dehaze", "LocalDehaze"),
                       ("sat", "LocalSaturation"), ("sharp", "LocalSharpness"),
                       ("temp", "LocalTemperature"), ("tint", "LocalTint")):
        if key in params:
            grp[field] = params[key] / 100.0

    m = {
        "MaskActive": True,
        "MaskValue": 1.0,
        "MaskInverted": bool(mask.get("invert", False)),
        "MaskBlendMode": 0.0,
        "MaskName": mask.get("mname", "蒙版"),
        "MaskID": g(),
        "MaskSyncID": g(),
    }
    if mask["kind"] == "linear":
        m["What"] = "Mask/Gradient"
        m["ZeroX"], m["ZeroY"] = mask["zero"]
        m["FullX"], m["FullY"] = mask["full"]
    else:
        m["What"] = "Mask/CircularGradient"
        m["Left"], m["Top"] = mask["lt"]
        m["Right"], m["Bottom"] = mask["rb"]
        m["Angle"] = mask.get("angle", 0.0)
        m["Midpoint"] = mask.get("mid", 50.0)
        m["Feather"] = mask.get("feather", 55.0)
        m["Roundness"] = mask.get("round", 0.0)
        m["Flipped"] = False
    grp["CorrectionMasks"] = {"1": m}
    return grp


# ------------------------------------------------------------------ 方案
# 坐标归一化，原点左上。线性的 zero 是「零值端」、full 是「满值端」。
LAYERS = [
    dict(name="1 天空压暗", kind="linear", zero=(0.50, 0.48), full=(0.50, -0.10),
         ref=(0.5, 0.20), ev=-0.28, highlights=-34, dehaze=8),
    dict(name="2 天顶加深", kind="linear", zero=(0.50, 0.30), full=(0.50, -0.40),
         ref=(0.5, 0.05), ev=-0.16, highlights=-20, sat=12),
    dict(name="3 云区提亮", kind="radial", lt=(0.12, -0.06), rb=(0.95, 0.30),
         ref=(0.55, 0.12), ev=0.14, highlights=8),
    dict(name="4 谷口提亮", kind="radial", lt=(0.31, 0.29), rb=(0.63, 0.52),
         ref=(0.468, 0.40), ev=0.34, clarity=14, dehaze=6),
    dict(name="5 中景暗带", kind="radial", lt=(-0.05, 0.27), rb=(1.05, 0.72),
         ref=(0.5, 0.50), ev=0.24, shadows=20),
    dict(name="6 左坡压暗", kind="linear", zero=(0.60, 0.66), full=(-0.15, 0.02),
         ref=(0.15, 0.35), ev=-0.16),
    dict(name="7 右坡提亮", kind="linear", zero=(0.42, 0.58), full=(1.15, 0.00),
         ref=(0.80, 0.30), ev=0.16, clarity=10, sat=8, temp=6),
    dict(name="8 光向右上", kind="linear", zero=(-0.20, 1.00), full=(1.10, -0.15),
         ref=(0.75, 0.25), ev=-0.10),
    dict(name="9 土路引导", kind="radial", lt=(0.20, 0.44), rb=(0.82, 1.20),
         ref=(0.50, 0.80), ev=0.40, clarity=10, texture=8),
    dict(name="10 前景压暗", kind="linear", zero=(0.50, 0.58), full=(0.50, 1.25),
         ref=(0.5, 0.95), ev=-0.12),
    dict(name="11 人物点睛", kind="radial", lt=(0.510, 0.470), rb=(0.580, 0.525),
         ref=(0.545, 0.497), ev=0.45, clarity=25, sat=14, temp=8),
    dict(name="12 暗角", kind="radial", lt=(-0.16, -0.14), rb=(1.16, 1.00),
         ref=(0.50, 0.43), ev=-0.18, invert=True),
    dict(name="13 裸土压火", kind="radial", lt=(0.76, 0.20), rb=(1.14, 0.54),
         ref=(0.93, 0.34), ev=-0.14, sat=-12),
]


def build_from_specs(tpl, specs, start_index=1):
    """把规格列表转成 MaskGroupBasedCorrections 树。

    specs 每项形如：
        {"name": "15 主石顶光", "kind": "radial",
         "lt": [0.27, 0.66], "rb": [0.60, 0.83],
         "ref": [0.44, 0.75], "ev": 0.2, "clarity": 12}
    其余关键词参数按 lr_masks.build_layer 的语义透传（ev/highlights/shadows/
    blacks/whites/contrast/clarity/texture/dehaze/sat/sharp/temp/tint）。
    """
    tree = {"MaskGroupBasedCorrections": {}}
    for offset, raw in enumerate(specs):
        spec = dict(raw)
        mask = {"kind": spec.pop("kind")}
        for k in ("zero", "full", "lt", "rb", "invert", "angle", "mid", "feather", "round"):
            if k in spec:
                mask[k] = spec.pop(k)
        name = spec.pop("name")
        mask["mname"] = name.split(" ", 1)[1] if " " in name else name
        ref = spec.pop("ref", (0.5, 0.5))
        tree["MaskGroupBasedCorrections"][str(start_index + offset)] = build_layer(
            tpl, name, mask, ref, **spec)
    return tree



# ---------------------------------------------------------------- 布尔蒙版
# 实测（2026-11-09，ZTY_6191）：
#   MaskBlendMode = 0 → 添加    ✓
#   MaskBlendMode = 1 → 减去    ✓
#   MaskBlendMode = 2/3/4 → 无效，被 LR 强制归零
# 没有"相交"值，但 A ∩ B == A − (¬B)，用「减去 + 第二蒙版反相」算出来。

_BASE_MASKS = {
    "subject":    (1.0, "主体"),
    "sky":        (2.0, "Sky"),
    "background": (3.0, "背景"),
}


def _ai_mask(base, idx=1):
    """AI 蒙版节点。base: 'subject'|'sky'|'background'|1|2|3"""
    if isinstance(base, str):
        sub, nm = _BASE_MASKS[base]
    else:
        sub = float(base)
        nm = {1.0: "主体", 2.0: "Sky", 3.0: "背景"}.get(sub, "AI")
    return {
        "What": "Mask/Image",
        "MaskSubType": sub,
        "MaskVersion": 1.0,
        "MaskName": "%s %d" % (nm, idx),
        "MaskActive": True,
        "MaskValue": 1.0,
        "MaskInverted": False,
        "MaskBlendMode": 0.0,
        "MaskID": g(),
        "MaskSyncID": g(),
    }


def _geom_mask(geom):
    """几何蒙版节点（径向 / 线性）。"""
    m = {
        "MaskActive": True,
        "MaskValue": 1.0,
        "MaskInverted": False,
        "MaskBlendMode": 0.0,
        "MaskName": geom.get("mname", "蒙版"),
        "MaskID": g(),
        "MaskSyncID": g(),
    }
    if geom["kind"] == "linear":
        m["What"] = "Mask/Gradient"
        m["ZeroX"], m["ZeroY"] = geom["zero"]
        m["FullX"], m["FullY"] = geom["full"]
    elif geom["kind"] == "radial":
        m["What"] = "Mask/CircularGradient"
        m["Left"], m["Top"] = geom["lt"]
        m["Right"], m["Bottom"] = geom["rb"]
        m["Angle"] = geom.get("angle", 0.0)
        m["Midpoint"] = geom.get("mid", 50.0)
        m["Feather"] = geom.get("feather", 55.0)
        m["Roundness"] = geom.get("round", 0.0)
        m["Flipped"] = False
    else:
        raise ValueError("geom['kind'] 只支持 radial / linear")
    return m


def build_bool_layer(tpl, name, base, geom, ref=(0.5, 0.5), op="intersect", **params):
    """布尔蒙版层：AI 蒙版 与 几何蒙版 做运算。

    base : 'subject' | 'sky' | 'background' | 1 | 2 | 3   哪张 AI 蒙版打底
    geom : dict，kind='radial'/'linear' 及几何参数；None = 纯 AI 蒙版（不运算）
    op   : 'intersect'  A ∩ B   只作用于两者重叠处（框只限范围，AI 定边界）
           'subtract'   A − B   作用于 A，排除 B
           'add'        A + B   两份叠加

    >>> build_bool_layer(tpl, "蛇头提亮", "subject",
    ...                  {"kind":"radial","lt":(0.448,0.428),"rb":(0.552,0.522),"feather":45},
    ...                  ev=0.12, clarity=12)
    """
    grp = build_layer(tpl, name, geom or {"kind": "radial", "lt": (0, 0), "rb": (1, 1)}, ref, **params)
    masks = {"1": _ai_mask(base, 1)}
    if geom is not None:
        gm = _geom_mask(geom)
        if op == "intersect":
            gm["MaskBlendMode"] = 1.0
            gm["MaskInverted"] = True      # A − ¬B == A ∩ B
        elif op == "subtract":
            gm["MaskBlendMode"] = 1.0
            gm["MaskInverted"] = False     # A − B
        elif op == "add":
            gm["MaskBlendMode"] = 0.0
            gm["MaskInverted"] = bool(geom.get("invert", False))
        else:
            raise ValueError("op 只支持 intersect / subtract / add")
        masks["2"] = gm
    grp["CorrectionMasks"] = masks
    return grp


def main():
    """演示：用 LAYERS 里的示例方案构造一整棵树。实际追加请用 mask_append.py。"""
    ap = argparse.ArgumentParser(description="构造 Lightroom 蒙版层（库 + 演示）")
    ap.add_argument("--template", required=True,
                    help="任一张已有蒙版照片的 dump json，用来取 Local* 默认键")
    ap.add_argument("--out", default="masks_tree.json")
    args = ap.parse_args()

    tpl = json.load(io.open(args.template, encoding="utf-8"))["MaskGroupBasedCorrections"]["1"]
    tree = build_from_specs(tpl, LAYERS, 1)
    json.dump(tree, io.open(args.out, "w", encoding="utf-8"), ensure_ascii=False)
    for i, spec in enumerate(LAYERS, 1):
        print("  %2d %s" % (i, spec["name"]))
    print("-> %s" % args.out)
    return tree


if __name__ == "__main__":
    main()
