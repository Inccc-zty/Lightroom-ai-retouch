#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""根治 Lightroom 导出 AI 蒙版照片时的「推荐 AI 更新」弹框。

问题
----
照片上带 AI 蒙版（AI 天空 / AI 主体）时，每次导出 LR 都会弹：

    以下照片使用了 AI 设置，建议您进行更新以获得正确的渲染效果。
    [更新受影响的照片] [在图库中显示] [导出] [取消]

这个框阻塞插件循环：心跳停、inbox 积压、导出目录空，
但任务管理器里 LR 仍是「正常响应」。

不是偶发——**只要照片带 AI 蒙版且 LR 判定需要更新，就一定弹。**

根因与解法
----------
Lightroom 把「导出时是否提示 AI 更新」记在首选项里，键名：

    AIUpdateWarning_shouldUpdateAffectedPhotos

默认 `true`（每次都问）。改成 `false` 后，LR 直接跳过提示、用现有设置导出，
**实时生效，不需要重启 Lightroom。**

但 LR 会在自己认为合适的时候把首选项写回磁盘（实测约 2 分钟内被覆盖回 true）。
内存里的值仍然生效，**一个会话内有效；LR 重启后要重跑一次。**
要每次都稳，用 `lr_export_safe.py`——它在每次导出前自动过一遍。

首选项文件（Windows）：
    %APPDATA%\\Adobe\\Lightroom\\Preferences\\Lightroom Classic CC 7 Preferences.agprefs

格式是纯文本的 Lua 风格表，可以安全地做字符串替换。

副作用
------
LR 不再自动重算 AI 蒙版的位图。实测同一张照片在改前/改后导出，
平均像素差 1.3（最大 15），差异是均匀细碎噪点、无任何形状或边界——
即 AI 蒙版的识别效果完整保留，只是位图精度有极小差别，视觉不可见。

如果你依赖 LR 在版本升级后自动刷新蒙版，就不要改这个开关，
改用 `lr_unstick.py` 手动/守护解卡。

用法
----
    python fix_ai_dialog.py            # 关闭警告（备份后修改）
    python fix_ai_dialog.py --status   # 只看当前值
    python fix_ai_dialog.py --restore  # 从最近的备份恢复
    python fix_ai_dialog.py --on       # 改回 true（恢复弹框）
"""
from __future__ import annotations

import argparse
import glob
import os
import shutil
import sys
import time

KEY = b"AIUpdateWarning_shouldUpdateAffectedPhotos"


def prefs_paths() -> list[str]:
    """返回候选首选项文件路径，按存在性过滤。"""
    cands = []
    appdata = os.environ.get("APPDATA")
    if appdata:
        base = os.path.join(appdata, "Adobe", "Lightroom", "Preferences")
        cands += sorted(glob.glob(os.path.join(base, "*Preferences.agprefs")))
    home = os.path.expanduser("~")
    cands += sorted(glob.glob(os.path.join(
        home, "Library", "Preferences", "Adobe", "Lightroom", "*Preferences.agprefs")))
    # 过滤掉备份文件
    return [p for p in cands if ".bak_" not in p and os.path.isfile(p)]


def read_status(path: str):
    b = open(path, "rb").read()
    i = b.find(KEY)
    if i < 0:
        return None, b
    seg = b[i:i + len(KEY) + 20]
    if b"= true" in seg:
        return True, b
    if b"= false" in seg:
        return False, b
    return None, b


def set_value(path: str, value: bool) -> bool:
    cur, b = read_status(path)
    if cur is None:
        print(f"  未找到键 {KEY.decode()}，跳过：{path}")
        return False
    target = b"= true" if value else b"= false"
    other = b"= false" if value else b"= true"
    i = b.find(KEY)
    seg_end = i + len(KEY) + 20
    seg = b[i:seg_end]
    if target in seg:
        print(f"  已经是 {value}：{path}")
        return True
    new_seg = seg.replace(other, target, 1)
    nb = b[:i] + new_seg + b[seg_end:]
    bak = path + ".bak_" + time.strftime("%Y%m%d_%H%M%S")
    shutil.copy(path, bak)
    open(path, "wb").write(nb)
    print(f"  {value} 已写入 -> {path}")
    print(f"  备份 -> {bak}")
    return True


def restore(path: str) -> bool:
    baks = sorted(glob.glob(path + ".bak_*"))
    if not baks:
        print(f"  没有备份可恢复：{path}")
        return False
    latest = baks[-1]
    shutil.copy(latest, path)
    print(f"  已从 {os.path.basename(latest)} 恢复 -> {path}")
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description="关闭/恢复 Lightroom 的「推荐 AI 更新」导出弹框")
    ap.add_argument("--status", action="store_true", help="只显示当前值")
    ap.add_argument("--restore", action="store_true", help="从最近备份恢复")
    ap.add_argument("--on", action="store_true", help="改回 true（恢复弹框）")
    args = ap.parse_args()

    paths = prefs_paths()
    if not paths:
        print("没找到 Lightroom 首选项文件。")
        print("Windows 预期位置：%APPDATA%\\Adobe\\Lightroom\\Preferences\\*Preferences.agprefs")
        return 2

    print(f"找到 {len(paths)} 个首选项文件")
    rc = 0
    for p in paths:
        print(f"\n[{os.path.basename(p)}]")
        cur, _ = read_status(p)
        if cur is None:
            print("  没有 AIUpdateWarning 键（可能这张 LR 版本不弹此框，或还没弹过）")
            continue
        print(f"  当前值：{cur}")
        if args.status:
            continue
        if args.restore:
            restore(p)
        else:
            set_value(p, not args.on)

    if not args.status and not args.restore:
        print("\n改完即生效，不需要重启 Lightroom。")
        print("验证：直接导出带 AI 蒙版的照片，看是否还弹框。")
        print("如要恢复：python fix_ai_dialog.py --restore")
    return rc


if __name__ == "__main__":
    sys.exit(main())
