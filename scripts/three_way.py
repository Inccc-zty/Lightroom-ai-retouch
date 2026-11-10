#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""三图对比工作流：基准 → 全局（未加蒙版）→ 定稿。

为什么改成三图（用户 2026-11-10 提出）
------------------------------------
原来的「原图 ↔ 定稿」只有一张对比，看不出**贡献拆分**：
哪部分是全局参数做的、哪部分是蒙版做的，全混在一起。
更严重的是：原图是每轮临时归零导出的，一旦归零列表有遗漏，
**每轮的原图都不一样**，对比图就成了不可信的证据。

新流程把三件事钉死：

1. **基准图在任务开始前生成一次**，全程复用，不再重算 → 永远同一张；
2. **全局图在第 7 步结束后（写第一个蒙版之前）导出** → 单独证明全局做了什么；
3. **定稿图**在最后导出 → 与全局图对比即可看出蒙版的全部贡献。

用法
----
    # ① 任务开始前（会备份现有参数，然后归零）
    python scripts/three_way.py baseline --path "/path/photo.NEF" --out "./工作目录"

    # ② 九步全局做完、还没写蒙版时
    python scripts/three_way.py global --path "/path/photo.NEF" --out "./工作目录"

    # ③ 全部完成
    python scripts/three_way.py final --path "/path/photo.NEF" --out "./工作目录"

    # ④ 拼图（桌面版 + 手机版）
    python scripts/three_way.py compose --out "./工作目录"
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
from orig_compare import RESET_GLOBALS, CALIBRATION_KEYS, HSL_KEYS, LOCAL_KEYS, tree_of_masks, restore  # noqa: E402

BASE = "00_基准_全归零.jpg"
GLOB = "01_全局_未加蒙版.jpg"
FINAL = "02_定稿.jpg"
OUT = "三图对比.jpg"
OUT_TEL = "三图对比_手机版.jpg"


def export(photo, dest_dir, long_edge=3000, quality=0.95):
    os.makedirs(dest_dir, exist_ok=True)
    r = lr_bridge.send("export", [("path.1", "s", photo), ("dest", "s", dest_dir),
                                  ("format", "s", "JPEG"), ("quality", "f", quality),
                                  ("longEdge", "i", long_edge), ("reimport", "i", 0)],
                       timeout=900)
    f = r.get("file.1")
    return f


def cmd_baseline(a):
    photo, out = a.path, a.out
    os.makedirs(out, exist_ok=True)
    flat = lr_bridge.send("develop_dump", [("path.1", "s", photo)], timeout=180)
    bk = os.path.join(out, "_backup_before_task.json")
    json.dump(flat, io.open(bk, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    n = sum(1 for k in flat if k.endswith(".CorrectionName"))
    print("[备份] %s（%d 键，%d 层蒙版）" % (bk, len(flat), n))

    sets = [("set." + k, "f", float(v)) for k, v in RESET_GLOBALS.items()]
    for k in CALIBRATION_KEYS:
        sets.append(("set." + k, "f", 0.0))
    for k in HSL_KEYS:
        if abs(float(flat.get("p1." + k, 0) or 0)) > 1e-9:
            sets.append(("set." + k, "f", 0.0))
    lr_bridge.send("develop_set", [("path.1", "s", photo)] + sets, timeout=240)

    tree = tree_of_masks(flat)
    if tree["MaskGroupBasedCorrections"]:
        for lay in tree["MaskGroupBasedCorrections"].values():
            for lk in LOCAL_KEYS:
                if lk in lay:
                    lay[lk] = 0.0
        lr_bridge.send_tree("develop_set_tree", tree, [photo], timeout=240)
    lr_bridge.send_tree("develop_set_tree",
                        {"ToneCurvePV2012": [0, 0, 255, 255], "ToneCurveName2012": "Linear"},
                        [photo], timeout=120)

    # 校验：所有归零项都为默认
    chk = lr_bridge.send("develop_dump", [("path.1", "s", photo)], timeout=180)
    bad = []
    for k, v in RESET_GLOBALS.items():
        nv = chk.get("p1." + k)
        if nv is not None and abs(float(nv) - float(v)) > 1e-6:
            bad.append((k, v, nv))
    print("[校验] 未归零项：%s" % (bad if bad else "无"))

    tmp = os.path.join(out, "_tmp_base")
    f = export(photo, tmp, a.long_edge)
    if f:
        os.replace(f, os.path.join(out, BASE))
        print("[基准] %s" % os.path.join(out, BASE))
    print("→ 现在可以开始九步。**这张基准图全程复用，不再重算。**")


def cmd_snap(a, name, label):
    out = a.out
    os.makedirs(out, exist_ok=True)
    tmp = os.path.join(out, "_tmp_" + label)
    f = export(a.path, tmp, a.long_edge)
    if f:
        os.replace(f, os.path.join(out, name))
        print("[%s] %s" % (label, os.path.join(out, name)))


def cmd_compose(a):
    from PIL import Image, ImageDraw, ImageFont
    out = a.out
    items = [(BASE, "① 基准（任务前 · 全部参数归零）"),
             (GLOB, "② 全局调整完成（尚未加蒙版）"),
             (FINAL, "③ 定稿（全局 + 蒙版光影）")]
    paths = [(os.path.join(out, n), t) for n, t in items]
    missing = [p for p, _ in paths if not os.path.exists(p)]
    if missing:
        print("缺少：%s" % missing)
        return 1

    try:
        fnt = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 30)
    except Exception:
        fnt = ImageFont.load_default()

    for W, suffix in ((1500, ""), (1100, "_手机版")):
        ims = []
        for p, t in paths:
            im = Image.open(p).convert("RGB")
            im = im.resize((W, int(W * im.height / im.width)), Image.LANCZOS)
            ims.append((im, t))
        BAR, GAP = 52, 8
        H = sum(i.height for i, _ in ims) + BAR * len(ims) + GAP * (len(ims) - 1)
        cv = Image.new("RGB", (W, H), (250, 250, 250))
        d = ImageDraw.Draw(cv)
        y = 0
        for im, t in ims:
            d.rectangle([0, y, W, y + BAR], fill=(240, 240, 240))
            d.text((14, y + 11), t, fill=(25, 25, 25), font=fnt)
            y += BAR
            cv.paste(im, (0, y))
            y += im.height + GAP
        o = os.path.join(out, OUT if not suffix else OUT_TEL)
        cv.save(o, quality=88, optimize=True)
        print("[拼图] %s  %s  %.1f MB" % (o, cv.size, os.path.getsize(o) / 1048576))
    return 0


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("baseline", "global", "final"):
        s = sub.add_parser(name)
        s.add_argument("--path", required=True)
        s.add_argument("--out", required=True)
        s.add_argument("--long-edge", type=int, default=3000)
    c = sub.add_parser("compose")
    c.add_argument("--out", required=True)
    a = ap.parse_args()

    if a.cmd == "baseline":
        return cmd_baseline(a) or 0
    if a.cmd == "global":
        return cmd_snap(a, GLOB, "全局") or 0
    if a.cmd == "final":
        return cmd_snap(a, FINAL, "定稿") or 0
    return cmd_compose(a)


if __name__ == "__main__":
    sys.exit(main())
