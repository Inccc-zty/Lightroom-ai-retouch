#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Lightroom 卡在「推荐 AI 更新」对话框时，一键点「导出」。

什么时候用
----------
带了 AI 蒙版（AI 天空 / AI 主体）的照片，导出时 LR 会弹：

    以下照片使用了 AI 设置，建议您进行更新以获得正确的渲染效果。
    [更新受影响的照片] [在图库中显示] [导出] [取消]

这个框会阻塞插件的 Lua 循环，症状是：

- 桥接心跳停止（heartbeat.txt 时间戳不再更新）
- inbox 里命令文件越积越多
- 导出目录是空的
- **但任务管理器里 Lightroom 仍然显示「正常响应」**

从外面完全看不出是卡住了。**第一反应不是怀疑桥接坏了，是来点这个按钮。**

用法
----
    python lr_unstick.py                # 找对话框并点「导出」
    python lr_unstick.py --list         # 只列出窗口，不点
    python lr_unstick.py --choose 取消   # 点别的按钮

安全
----
- 只处理标题命中 `TITLES` 的窗口
- 只点击文字命中 `SAFE_BUTTONS` 的按钮
- **绝不点「更新受影响的照片」**——那会重算所有 AI 蒙版，几十分钟起步，
  而且会改掉照片外观
"""
from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes as wt
import sys
import time

user32 = ctypes.WinDLL("user32", use_last_error=True)

EnumWindows = user32.EnumWindows
EnumChildWindows = user32.EnumChildWindows
GetWindowTextW = user32.GetWindowTextW
GetClassNameW = user32.GetClassNameW
IsWindowVisible = user32.IsWindowVisible
GetWindowThreadProcessId = user32.GetWindowThreadProcessId
SendMessageW = user32.SendMessageW

WNDENUMPROC = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
BM_CLICK = 0x00F5

# 对话框标题（中英文都覆盖，LR 语言不同标题不同）
TITLES = ("推荐 AI 更新", "Recommend AI Updates", "Recommended AI Updates")

# 允许点击的按钮文字
SAFE_BUTTONS = {
    "导出": "export",
    "Export": "export",
    "取消": "cancel",
    "Cancel": "cancel",
    "在图库中显示": "show",
    "Show in Library": "show",
}

# 绝对禁止的按钮
FORBIDDEN = ("更新受影响的照片", "Update Affected Photos", "更新", "Update")


def _text(hwnd) -> str:
    buf = ctypes.create_unicode_buffer(512)
    GetWindowTextW(hwnd, buf, 512)
    return buf.value.strip()


def _class(hwnd) -> str:
    buf = ctypes.create_unicode_buffer(256)
    GetClassNameW(hwnd, buf, 256)
    return buf.value


def lr_pids() -> set[int]:
    """找 Lightroom 进程号。找不到就返回空集合（表示不过滤）。"""
    pids = set()
    try:
        import subprocess
        out = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq lightroom.exe", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, timeout=10).stdout
        for line in out.splitlines():
            parts = [p.strip('"') for p in line.split('","')]
            if len(parts) >= 2 and parts[1].isdigit():
                pids.add(int(parts[1]))
    except Exception:
        pass
    return pids


def find_dialogs(pids=None):
    found = []

    def cb(hwnd, _):
        if not IsWindowVisible(hwnd):
            return True
        if pids:
            pid = wt.DWORD()
            GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value not in pids:
                return True
        t = _text(hwnd)
        if t in TITLES:
            found.append((hwnd, t))
        return True

    EnumWindows(WNDENUMPROC(cb), 0)
    return found


def find_buttons(dlg):
    out = []

    def cb(hwnd, _):
        if _class(hwnd) == "Button":
            out.append((hwnd, _text(hwnd)))
        return True

    EnumChildWindows(dlg, WNDENUMPROC(cb), 0)
    return out


def click(dlg, want="export"):
    buttons = find_buttons(dlg)
    if not buttons:
        print("  对话框里没找到按钮，可能需要手动点")
        return False
    print("  按钮：" + " | ".join(f"[{t or '(无字)'}]" for _, t in buttons))
    for hwnd, text in buttons:
        if text in FORBIDDEN:
            continue
        if SAFE_BUTTONS.get(text) == want:
            SendMessageW(hwnd, BM_CLICK, 0, 0)
            print(f"  已点「{text}」")
            return True
    print(f"  没找到目标按钮（want={want}），可用：" +
          ", ".join(t for _, t in buttons if t))
    return False


def main() -> int:
    ap = argparse.ArgumentParser(description="解开 Lightroom 的「推荐 AI 更新」对话框")
    ap.add_argument("--list", action="store_true", help="只列出窗口，不点击")
    ap.add_argument("--choose", default="导出", help="要点的按钮文字，默认「导出」")
    ap.add_argument("--wait", type=int, default=0, help="等待对话框出现的秒数")
    args = ap.parse_args()

    pids = lr_pids()
    print(f"Lightroom 进程：{pids or '未找到（不过滤）'}")

    deadline = time.time() + args.wait
    while True:
        dialogs = find_dialogs(pids)
        if dialogs:
            break
        if time.time() >= deadline:
            print("没有发现「推荐 AI 更新」对话框。")
            if args.list:
                print("--- 所有可见的 Lightroom 窗口 ---")
                def cb(hwnd, _):
                    if not IsWindowVisible(hwnd):
                        return True
                    if pids:
                        pid = wt.DWORD()
                        GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                        if pid.value not in pids:
                            return True
                    t = _text(hwnd)
                    if t:
                        print(f"  HWND={hwnd} CLASS={_class(hwnd)} TITLE=[{t}]")
                    return True
                EnumWindows(WNDENUMPROC(cb), 0)
            return 1
        time.sleep(0.5)

    want = SAFE_BUTTONS.get(args.choose, "export")
    ok = False
    for hwnd, title in dialogs:
        print(f"发现对话框：HWND={hwnd} TITLE=[{title}]")
        if args.list:
            for h, t in find_buttons(hwnd):
                print(f"    Button HWND={h} TEXT=[{t}]")
            continue
        ok = click(hwnd, want) or ok
    return 0 if ok or args.list else 1


if __name__ == "__main__":
    sys.exit(main())
