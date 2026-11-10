#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""向 Lightroom 照片追加蒙版层（不破坏已有层）。

设计原则
--------
1. **默认 dry-run**，只打印将要写入的内容，加 --apply 才真正落盘。
2. **显式 --path**。永远不依赖当前选中——用户在 LR 里点一下鼠标，
   「当前选中」就变了，写入会落到别的照片上。这个坑踩过。
3. 写入前把现有完整 develop settings 备份到 --backup，写入后立即回读并
   逐字段比对，确认新层到齐、老层没丢。

用法
----
    # 1. 先看要写什么
    python mask_append.py --path "/path/to/a.NEF" --spec layers.json

    # 2. 确认无误再写
    python mask_append.py --path "/path/to/a.NEF" --spec layers.json --apply

    # 3. 回滚
    python lr_bridge.py tree-set --path "/path/to/a.NEF" --json backup.json

layers.json 格式
----------------
    [
      {"name": "15 主石顶光", "kind": "radial",
       "lt": [0.27, 0.66], "rb": [0.60, 0.83],
       "ref": [0.44, 0.75], "ev": 0.20, "clarity": 12, "texture": 8},
      {"name": "16 前景底压", "kind": "linear",
       "zero": [0.50, 0.82], "full": [0.50, 1.08],
       "ref": [0.50, 0.95], "ev": -0.11, "sat": -6}
    ]

坐标一律 0–1 归一化，原点左上。ev 是真实 EV，工具内部会除 4.5 转成
LocalExposure2012；其余参数按 LR 语义 -100..100 传。
"""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from lr_masks import build_from_specs  # noqa: E402

BRIDGE = os.path.join(HERE, "lr_bridge.py")
SKIP_KEYS = {"id", "op", "elapsed", "fields", "totalFields"}

# 零层照片也能直接写入 MaskGroupBasedCorrections（实测 Z03_9666，45 字段全部生效）。
# 缺的是 Local* 默认键，补一套全零的即可。
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


def run_bridge(args: list[str], timeout: int = 120) -> dict:
    proc = subprocess.run([sys.executable, BRIDGE] + args,
                          capture_output=True, text=True, timeout=timeout)
    out = proc.stdout.strip()
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        raise RuntimeError("桥接返回无法解析：\n%s\n%s" % (out[:500], proc.stderr[:500]))


def denest(flat: dict) -> dict[str, dict]:
    """把扁平 p1.MaskGroupBasedCorrections.i.k 还原成嵌套表。"""
    tree: dict[str, dict] = {}
    for k, v in flat.items():
        m = re.match(r"p1\.MaskGroupBasedCorrections\.(\d+)\.(.+)", k)
        if not m:
            continue
        parts = m.group(2).split(".")
        node = tree.setdefault(m.group(1), {})
        for p in parts[:-1]:
            node = node.setdefault(p, {})
        node[parts[-1]] = v
    return tree


def flatten(node: dict, prefix: str = "") -> dict:
    out = {}
    for k, v in node.items():
        key = f"{prefix}{k}"
        if isinstance(v, dict):
            out.update(flatten(v, key + "."))
        else:
            out[key] = v
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="向 Lightroom 照片追加蒙版层")
    ap.add_argument("--path", required=True, help="目标照片绝对路径（必须在 LR 目录里）")
    ap.add_argument("--spec", required=True, help="层定义 json 文件")
    ap.add_argument("--apply", action="store_true", help="真正写入（默认只预览）")
    ap.add_argument("--backup", default="", help="写入前备份路径，默认自动生成")
    ap.add_argument("--start-index", type=int, default=0,
                    help="起始层号，默认接在现有最大层号之后")
    args = ap.parse_args()

    photo = args.path
    if not os.path.isfile(photo):
        print("找不到照片：%s" % photo)
        return 2

    # 1. 读现状
    live = run_bridge(["dump", "--path", photo])
    if not live.get("ok"):
        print("读取失败：%s" % live.get("err"))
        return 1
    layers = denest(live)
    max_idx = max((int(k) for k in layers), default=0)
    print("现有 %d 层，最大层号 %d" % (len(layers), max_idx))

    start = args.start_index or (max_idx + 1)
    specs = json.load(io.open(args.spec, encoding="utf-8"))

    # 2. 构造
    if not layers:
        print("这张照片还没有蒙版层，使用内置零模板直接创建（实测可行）")
        tpl = DEFAULT_TPL
    else:
        tpl = layers[str(max_idx)]
    new_tree = build_from_specs(tpl, specs, start)

    merged = {k: layers[k] for k in layers}
    merged.update(new_tree["MaskGroupBasedCorrections"])
    merged = {k: merged[k] for k in sorted(merged, key=int)}
    print("写入后共 %d 层，新增 %d 层：" % (len(merged), len(new_tree["MaskGroupBasedCorrections"])))
    for k in sorted(new_tree["MaskGroupBasedCorrections"], key=int):
        spec = new_tree["MaskGroupBasedCorrections"][k]
        ev = spec.get("LocalExposure2012", 0) * 4.5
        print("  %-3s %-18s EV=%+.2f" % (k, spec.get("CorrectionName"), ev))

    if not args.apply:
        print("\n[dry-run] 未写入。加 --apply 执行。")
        return 0

    # 3. 备份
    backup = args.backup or (os.path.splitext(photo)[0] + "_masks_before.json")
    json.dump({"MaskGroupBasedCorrections": {k: layers[k] for k in sorted(layers, key=int)}},
              io.open(backup, "w", encoding="utf-8"), ensure_ascii=False)
    print("已备份现有层 -> %s" % backup)

    # 4. 写
    tree_file = os.path.splitext(backup)[0] + "_tree.json"
    json.dump({"MaskGroupBasedCorrections": merged}, io.open(tree_file, "w", encoding="utf-8"),
              ensure_ascii=False)
    res = run_bridge(["tree-set", "--path", photo, "--json", tree_file], timeout=180)
    if not res.get("ok"):
        print("写入失败：%s" % res.get("err"))
        return 1
    print("写入 %s 个字段" % res.get("applied"))

    # 5. 回读验证
    after = run_bridge(["dump", "--path", photo])
    if not after.get("ok"):
        print("回读失败，请手工核对")
        return 1
    after_layers = denest(after)
    missing = [k for k in merged if k not in after_layers]
    # 已有层逐字段比对（忽略 ID 类字段）
    drift = []
    for k in layers:
        a, b = flatten(layers[k]), flatten(after_layers.get(k, {}))
        for field in a:
            if field.endswith(("MaskID", "MaskSyncID", "CorrectionID", "CorrectionSyncID",
                               "CorrectionReferenceX", "CorrectionReferenceY")):
                continue
            va, vb = a[field], b.get(field)
            if isinstance(va, float) and isinstance(vb, float):
                if abs(va - vb) > 1e-6:
                    drift.append((k, field, va, vb))
            elif va != vb:
                drift.append((k, field, va, vb))

    print("\n回读：%d 层" % len(after_layers))
    print("缺失层：%s" % (missing or "无"))
    print("已有层漂移：%s" % (drift or "无"))
    return 0 if not missing and not drift else 1


if __name__ == "__main__":
    raise SystemExit(main())
