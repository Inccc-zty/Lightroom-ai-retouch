#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""原图 vs 定稿 对比图：一键生成（含"临时还原成未修原片"的全过程）。

为什么需要这个脚本
------------------
用户要求：**每交一张图，都要附一张「真正没修过的原图 vs 修后」的上下对比。**
"真正的原图"不能用用户自己 P 过的版本顶替，必须是 LR 里所有参数归位后的渲染。

实现思路（先备份 → 归零 → 导出 → 原样恢复 → 校验）
--------------------------------------------------
1. dump 全量 develop settings + 蒙版树，落盘备份；
2. 把全局滑杆 / HSL / 曲线 / 蒙版局部参数 / 裁切 全部归位到"未修"；
3. 导出 → 这就是"真正原图"；
4. 用备份把一切写回（含 12 类 Local* 与整棵蒙版树）；
5. **逐键比对**：恢复后 dump 与备份必须 0 差异，否则重试并大声报错；
6. 导出修后定稿，拼成上下对比图。

安全约束
--------
- 备份写在 --out 目录，恢复失败会打印备份路径，可手工 tree-set 回滚；
- 默认 --apply 才真的改照片；不加只做 dry-run；
- 归零列表写死在 RESET_GLOBALS 里，只碰这些键，不动镜头校正/降噪/配置文件。

用法
----
    python scripts/orig_compare.py --path "/path/to/photo.NEF" --out "./output" --apply
    python scripts/orig_compare.py --path "/path/to/photo.NEF" --out "./output"   # 只看要动什么
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

# 归零到"未修"的全局键（值即 LR 默认）
# ⚠ 2026-11-10 用户抓出的错误：原列表只归零了曝光族 + HSL + 蒙版，
# 漏掉了「分离色调」「颗粒」「暗角附属参数」——于是所谓"原图"里还带着
# 上一次调的暖调和颗粒，而且每版的暖调数值不同，导致**每张对比图的上半部分都不一样**。
# 凡是 applyDevelopSettings 能写的、且属于"调整"而非"相机默认"的键，都必须在这里。
RESET_GLOBALS = {
    # —— 曝光族 ——
    "Exposure2012": 0, "Contrast2012": 0, "Highlights2012": 0, "Shadows2012": 0,
    "Whites2012": 0, "Blacks2012": 0, "Texture": 0, "Clarity2012": 0,
    "Vibrance": 0, "Saturation": 0, "Dehaze": 0,
    # —— 暗角：Amount 归零还不够，附属参数一起回默认，避免换风格时残留 ——
    "PostCropVignetteAmount": 0,
    "PostCropVignetteMidpoint": 50, "PostCropVignetteFeather": 50,
    "PostCropVignetteRoundness": 0, "PostCropVignetteStyle": 1,
    "PostCropVignetteHighlightContrast": 0,
    # —— 分离色调（**曾经漏掉，是"原图不一致"的主因**）——
    "SplitToningHighlightHue": 0, "SplitToningHighlightSaturation": 0,
    "SplitToningShadowHue": 0, "SplitToningShadowSaturation": 0,
    "SplitToningBalance": 0,
    # —— 颗粒（**曾经漏掉**）——
    "GrainAmount": 0, "GrainSize": 0, "GrainFrequency": 0,
    # —— 细节默认值（LR 新建照片时的默认，不是 0）——
    "Sharpness": 40, "SharpenRadius": 1.0, "SharpenDetail": 25,
    "SharpenEdgeMasking": 0, "LuminanceSmoothing": 0,
    "LuminanceNoiseReductionDetail": 50, "LuminanceNoiseReductionContrast": 0,
    # —— 裁切（不碰构图，但保证对比图同尺寸）——
    "CropLeft": 0, "CropTop": 0, "CropRight": 1, "CropBottom": 1, "CropAngle": 0,
}
# 相机校准族（默认全 0）。写进去更彻底；若 SDK 拒收会自动忽略，不影响其他键。
CALIBRATION_KEYS = ["ShadowTint", "RedHue", "RedSaturation", "GreenHue", "GreenSaturation",
                    "BlueHue", "BlueSaturation"]
HSL_KEYS = [f"{kind}Adjustment{color}"
            for kind in ("Hue", "Saturation", "Luminance")
            for color in ("Red", "Orange", "Yellow", "Green", "Aqua", "Blue",
                          "Purple", "Magenta")]
LOCAL_KEYS = ["LocalExposure2012", "LocalContrast2012", "LocalHighlights2012",
              "LocalShadows2012", "LocalWhites2012", "LocalBlacks2012",
              "LocalClarity2012", "LocalTexture", "LocalDehaze", "LocalSaturation",
              "LocalTemperature", "LocalTint", "LocalSharpness"]
SKIP = {"id", "op", "elapsed", "fields", "totalFields", "running", "version", "root", "time", "catalog"}


def dump_all(photo):
    return lr_bridge.send("develop_dump", [("path.1", "s", photo)], timeout=120)


def tree_of_masks(flat):
    """把 flatten 的 p1.MaskGroupBasedCorrections.N... 还原成嵌套 dict。

    注意：返回结构是 {"MaskGroupBasedCorrections": {"1": {...}, "2": {...}}}。
    路径要跳过 "p1" 和 "MaskGroupBasedCorrections" 两段——少跳一段会变成
    双层嵌套，LR 收到非法键会把整组蒙版清空（实测踩过，12 层全没）。
    """
    inner = {}
    for k, v in flat.items():
        if not k.startswith("p1.MaskGroupBasedCorrections."):
            continue
        seg = k.split(".")[2:]
        node = inner
        for s in seg[:-1]:
            node = node.setdefault(s, {})
        node[seg[-1]] = v
    return {"MaskGroupBasedCorrections": inner}


def curve_of(flat):
    pts = []
    for i in range(1, 25):
        x = flat.get(f"p1.ToneCurvePV2012.{i}")
        if x is None:
            break
        pts.append(x)
    return pts


def _reset_keys(backup):
    """本次会被归零的键 = 需要恢复的键。只碰这些，避免给 applyDevelopSettings 喂只读键。"""
    keys = list(RESET_GLOBALS.keys())
    for k in HSL_KEYS:
        if abs(float(backup.get("p1." + k, 0) or 0)) > 1e-9:
            keys.append(k)
    return keys


def restore(photo, backup):
    """把备份里**被归零过**的全局参数、曲线、蒙版树写回去。"""
    sets = []
    for key in _reset_keys(backup):
        v = backup.get("p1." + key)
        if v is None:
            continue
        sets.append(("set." + key, "f", float(v)))
    if sets:
        lr_bridge.send("develop_set", [("path.1", "s", photo)] + sets, timeout=180)

    pts = curve_of(backup)
    if pts:
        lr_bridge.send_tree("develop_set_tree",
                            {"ToneCurvePV2012": pts, "ToneCurveName2012": "Custom"},
                            [photo], timeout=120)
    tree = tree_of_masks(backup)
    if tree["MaskGroupBasedCorrections"]:
        lr_bridge.send_tree("develop_set_tree", tree, [photo], timeout=180)


def verify(photo, backup):
    """只校验被归零过的字段 + 曲线 + 蒙版局部参数。"""
    now = dump_all(photo)
    watch = ["p1." + k for k in _reset_keys(backup)]
    watch += [k for k in backup if k.startswith("p1.ToneCurvePV2012.")]
    watch += [k for k in backup if k.startswith("p1.MaskGroupBasedCorrections.")
              and any(k.endswith("." + lk) for lk in LOCAL_KEYS)]
    diff = []
    for k in watch:
        v, nv = backup.get(k), now.get(k)
        if isinstance(v, (int, float)) and isinstance(nv, (int, float)):
            if abs(float(v) - float(nv)) > 1e-6:
                diff.append((k, v, nv))
        elif v != nv:
            diff.append((k, v, nv))
    return diff


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--path", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--long-edge", type=int, default=4000)
    ap.add_argument("--width", type=int, default=1800, help="对比图宽度")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    photo = a.path
    name = os.path.splitext(os.path.basename(photo))[0]
    os.makedirs(a.out, exist_ok=True)

    print("[1/6] 备份当前调整")
    backup = dump_all(photo)
    json.dump(backup, io.open(os.path.join(a.out, f"{name}_backup_full.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    nlayer = sum(1 for k in backup if k.endswith(".CorrectionName"))
    print("      全局 %d 键，蒙版 %d 层" % (len(backup), nlayer))

    print("[2/6] 归零到未修状态")
    sets = [("set." + k, "f", float(v)) for k, v in RESET_GLOBALS.items()]
    for k in HSL_KEYS:
        cur = backup.get("p1." + k, 0) or 0
        if abs(float(cur)) > 1e-9:
            sets.append(("set." + k, "f", 0.0))
    if not a.apply:
        print("      [dry-run] 将写入 %d 个全局键；蒙版 %d 层局部参数归零" % (len(sets), nlayer))
        print("      加 --apply 执行")
        return 0
    lr_bridge.send("develop_set", [("path.1", "s", photo)] + sets, timeout=180)

    if nlayer:
        tree = tree_of_masks(backup)
        for lay in tree["MaskGroupBasedCorrections"].values():
            for k in LOCAL_KEYS:
                if k in lay:
                    lay[k] = 0.0
        lr_bridge.send_tree("develop_set_tree", tree, [photo], timeout=180)
        # 安全闸：归零不许弄丢层，丢了立刻回滚并中止
        chk = dump_all(photo)
        n2 = sum(1 for k in chk if k.endswith(".CorrectionName"))
        if n2 != nlayer:
            print("      !!!! 归零后层数 %d != %d，立即回滚" % (n2, nlayer))
            restore(photo, backup)
            return 1
    lr_bridge.send_tree("develop_set_tree",
                        {"ToneCurvePV2012": [0, 0, 255, 255], "ToneCurveName2012": "Linear"},
                        [photo], timeout=120)

    print("[3/6] 导出未修原图")
    orig_dir = os.path.join(a.out, f"{name}_orig")
    r = lr_bridge.send("export", [("path.1", "s", photo), ("dest", "s", orig_dir),
                                  ("format", "s", "JPEG"), ("quality", "f", 0.95),
                                  ("longEdge", "i", a.long_edge), ("reimport", "i", 0)], timeout=600)
    orig = r.get("file.1")
    print("      ", orig)

    print("[4/6] 恢复原调整")
    restore(photo, backup)
    diff = verify(photo, backup)
    if diff:
        print("      !! 首次恢复有 %d 处差异，重试一次" % len(diff))
        restore(photo, backup)
        diff = verify(photo, backup)
    if diff:
        print("      !!!! 恢复失败 %d 处，备份在 %s，请手工 tree-set 回滚" %
              (len(diff), os.path.join(a.out, f"{name}_backup_full.json")))
        for d in diff[:10]:
            print("        ", d)
        return 1
    print("      校验通过：与备份 0 差异")

    print("[5/6] 导出修后定稿")
    final_dir = os.path.join(a.out, f"{name}_final")
    r = lr_bridge.send("export", [("path.1", "s", photo), ("dest", "s", final_dir),
                                  ("format", "s", "JPEG"), ("quality", "f", 0.95),
                                  ("longEdge", "i", a.long_edge), ("reimport", "i", 0)], timeout=600)
    final = r.get("file.1")
    print("      ", final)

    print("[6/6] 拼上下对比")
    from PIL import Image
    A = Image.open(orig).convert("RGB")
    B = Image.open(final).convert("RGB")
    W = a.width
    A = A.resize((W, int(W * A.height / A.width)), Image.LANCZOS)
    B = B.resize((W, int(W * B.height / B.width)), Image.LANCZOS)
    GAP = 8
    cv = Image.new("RGB", (W, A.height + GAP + B.height), (255, 255, 255))
    cv.paste(A, (0, 0))
    cv.paste(B, (0, A.height + GAP))
    out = os.path.join(a.out, f"{name}_原图对比.jpg")
    cv.save(out, quality=95)
    print("      完成：%s  %s" % (out, cv.size))
    return 0


if __name__ == "__main__":
    sys.exit(main())
