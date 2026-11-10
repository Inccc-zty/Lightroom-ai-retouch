#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""按层名修改已有蒙版层的参数并写回，带备份与回读校验。

比"重写整棵蒙版树"安全：只碰点名的层，其余原样回写。

patch 文件格式（按层名索引）::

    {
      "07 红花·回收溢出与质构": {"ev": -0.14, "clarity": 14, "highlights": -45},
      "02 前景·压暗":           {"geom": {"lt": [0.0, 0.66], "rb": [1.0, 1.02], "feather": 60}}
    }

- 键是**层名**（不区分大小写无意义，必须完全一致），不是层号
- `geom` 只改几何，保留原有的混合模式与反相状态
- 其余键是 LR 界面语义（ev / clarity / texture / sat / temp / tint /
  contrast / highlights / shadows / whites / blacks / dehaze / sharp）

用法::

    python scripts/set_layer.py --path "/path/to/photo.NEF" --patch patches.json
    python scripts/set_layer.py --path "/path/to/photo.NEF" --patch patches.json --apply
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import lr_bridge  # noqa: E402
from lr_masks import _geom_mask  # noqa: E402
from mask_tool import denest  # noqa: E402

EV = 4.5
FIELD = {
    "ev": "LocalExposure2012", "highlights": "LocalHighlights2012",
    "shadows": "LocalShadows2012", "whites": "LocalWhites2012",
    "blacks": "LocalBlacks2012", "contrast": "LocalContrast2012",
    "clarity": "LocalClarity2012", "texture": "LocalTexture",
    "dehaze": "LocalDehaze", "sat": "LocalSaturation",
    "temp": "LocalTemperature", "tint": "LocalTint", "sharp": "LocalSharpness",
}
GEOM_FIELDS = ("Left", "Top", "Right", "Bottom", "Feather", "Midpoint",
               "Roundness", "Angle", "ZeroX", "ZeroY", "FullX", "FullY")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--path", required=True)
    ap.add_argument("--patch", required=True)
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    layers = denest(lr_bridge.send(
        "develop_dump", [("path.1", "s", a.path), ("filter", "s", "MaskGroup")], timeout=60))
    patches = json.load(io.open(a.patch, encoding="utf-8"))
    names = {v.get("CorrectionName"): k for k, v in layers.items()}
    if not names:
        print("!! 这张照片没有任何蒙版层")
        return 1

    for name, p in patches.items():
        idx = names.get(name)
        if idx is None:
            print("!! 找不到层：%s（现有：%s）" % (name, " / ".join(n for n in names if n)))
            continue
        lay = layers[idx]
        for k, v in p.items():
            if k == "geom":
                for mk in lay.get("CorrectionMasks", {}).values():
                    if not isinstance(mk, dict):
                        continue
                    what = mk.get("What") or ""
                    if what.endswith("CircularGradient") or what.endswith("Gradient"):
                        kind = "radial" if what.endswith("CircularGradient") else "linear"
                        g = _geom_mask(dict(v, kind=kind))
                        for f in GEOM_FIELDS:
                            if f in g:
                                mk[f] = g[f]
            elif k in FIELD:
                lay[FIELD[k]] = v / EV if k == "ev" else v / 100.0
            else:
                raise SystemExit("未知参数 %s（可用：ev / geom / %s）"
                                 % (k, " / ".join(FIELD.keys() - {"ev"})))
        print("%-3s %-26s -> %s" % (idx, name, {k: v for k, v in p.items() if k != "geom"}))

    if not a.apply:
        print("[dry-run]")
        return 0

    bak = os.path.splitext(a.path)[0] + "_masks_backup.json"
    json.dump({"MaskGroupBasedCorrections": {k: layers[k] for k in sorted(layers, key=int)}},
              io.open(bak, "w", encoding="utf-8"), ensure_ascii=False)
    print("备份：%s" % bak)

    res = lr_bridge.send_tree("develop_set_tree", {"MaskGroupBasedCorrections": layers},
                              [a.path], timeout=180)
    print("写入：", res.get("ok"), res.get("applied"))
    after = denest(lr_bridge.send(
        "develop_dump", [("path.1", "s", a.path), ("filter", "s", "MaskGroup")], timeout=60))
    bad = []
    for name, p in patches.items():
        idx = names.get(name)
        if idx is None or idx not in after:
            bad.append((name, "missing"))
            continue
        for k, v in p.items():
            if k == "geom":
                continue
            want = v / EV if k == "ev" else v / 100.0
            got = after[idx].get(FIELD[k], 0.0) or 0.0
            if abs(float(want) - float(got)) > 1e-4:
                bad.append((name, k, want, got))
    print("回读校验：", bad or "全部一致")
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
