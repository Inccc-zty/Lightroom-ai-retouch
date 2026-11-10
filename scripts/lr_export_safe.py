#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""导出带 AI 蒙版的照片，自动处理「推荐 AI 更新」弹框。

封装三件事，避免每次都要想着手动解卡：

1. 导出前把 LR 首选项 `AIUpdateWarning_shouldUpdateAffectedPhotos` 置为 false
   （实时生效，不用重启 LR；一个会话有效，LR 重启后需要重跑）
2. 调 lr_bridge 导出
3. 超时/无文件时，自动调 lr_unstick 点掉对话框，然后重试一次

用法
----
    python lr_export_safe.py --path "<照片>" --dest out --long-edge 2400
    python lr_export_safe.py --path "<照片>" --dest out --long-edge 4000 --quality 0.92

不需要 --path 时也可以传多张。

为什么不用「导出前统一改一次」
--------------------------
LR 会在自己认为合适的时候把首选项写回磁盘（实测写完 2 分钟内就被覆盖回 true），
虽然内存里的值仍然生效，但重启后失效。所以每次导出都过一遍最保险，
成本只有一次文件读写（毫秒级）。
"""
from __future__ import annotations

import argparse
import glob
import os
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
BRIDGE = os.path.join(HERE, "lr_bridge.py")
UNSTICK = os.path.join(HERE, "lr_unstick.py")
KEY = b"AIUpdateWarning_shouldUpdateAffectedPhotos"


def prefs_files() -> list[str]:
    out = []
    appdata = os.environ.get("APPDATA")
    if appdata:
        base = os.path.join(appdata, "Adobe", "Lightroom", "Preferences")
        out += sorted(glob.glob(os.path.join(base, "*Preferences.agprefs")))
    home = os.path.expanduser("~")
    out += sorted(glob.glob(os.path.join(
        home, "Library", "Preferences", "Adobe", "Lightroom", "*Preferences.agprefs")))
    return [p for p in out if ".bak_" not in p and os.path.isfile(p)]


def silence_warning() -> int:
    """把警告开关置为 false。返回改动的文件数。"""
    n = 0
    for p in prefs_files():
        b = open(p, "rb").read()
        i = b.find(KEY)
        if i < 0:
            continue
        seg = b[i:i + len(KEY) + 20]
        if b"= false" in seg:
            n += 1
            continue
        if b"= true" not in seg:
            continue
        nb = b[:i] + seg.replace(b"= true", b"= false", 1) + b[i + len(KEY) + 20:]
        try:
            shutil.copy(p, p + ".bak_auto")
            open(p, "wb").write(nb)
            n += 1
        except Exception as e:
            print(f"  [warn] 写首选项失败 {p}: {e}", file=sys.stderr)
    return n


def run_bridge(args: list[str], timeout: int) -> tuple[bool, str]:
    try:
        proc = subprocess.run([sys.executable, BRIDGE] + args,
                              capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return False, "timeout"
    out = proc.stdout
    return ('"ok": true' in out and '"file.1"' in out), out


def main() -> int:
    ap = argparse.ArgumentParser(description="导出 AI 蒙版照片（自动跳过「推荐 AI 更新」弹框）")
    ap.add_argument("--path", action="append", required=True, help="照片路径，可多次指定")
    ap.add_argument("--dest", required=True, help="导出目录")
    ap.add_argument("--long-edge", type=int, default=2400)
    ap.add_argument("--quality", type=float, default=0.92)
    ap.add_argument("--format", default="JPEG")
    args = ap.parse_args()

    changed = silence_warning()
    print(f"[1/3] 警告开关已静音（{changed} 个首选项文件）")

    base = ["export", "--dest", args.dest, "--format", args.format,
            "--long-edge", str(args.long_edge), "--quality", str(args.quality)]
    for p in args.path:
        base += ["--path", p]

    print("[2/3] 导出中…")
    ok, out = run_bridge(base, timeout=180)
    if not ok:
        print("[3/3] 首次导出未完成，尝试点掉对话框后重试")
        subprocess.run([sys.executable, UNSTICK], capture_output=True, text=True, timeout=60)
        time.sleep(3)
        ok, out = run_bridge(base, timeout=180)

    if ok:
        for line in out.splitlines():
            if '"file.' in line:
                print("  " + line.strip())
        print("完成")
        return 0

    print(out.strip()[:800])
    print("导出失败。可手工跑：python lr_unstick.py --list")
    return 1


if __name__ == "__main__":
    sys.exit(main())
