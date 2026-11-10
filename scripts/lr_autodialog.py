# -*- coding: utf-8 -*-
"""Lightroom 导出对话框自动代点

AI 天空蒙版的照片在导出时，LR 会弹出「推荐 AI 更新」对话框：
    以下照片使用了 AI 设置，建议您进行更新以获得正确的渲染效果。
    您可以立即更新，或使用现有设置导出。
    按钮：[更新受影响的照片] [在图库中显示] [导出] [取消]

这个框会阻塞插件的导出任务（心跳停止、inbox 积压），且不影响 LR 主窗口的
Responding 状态，所以从外面看不出是「卡住了」。

本脚本作为一个守护进程运行：轮询 LR 窗口树，发现该对话框就点「导出」。
行为等同于用户手点，不修改照片参数。

用法：
    python tools/lr_autodialog.py --watch 600        # 守护 600 秒
    python tools/lr_autodialog.py --once             # 只查一次
    python tools/lr_autodialog.py --once --choose 取消  # 指定点哪个按钮

安全约束：
- 只处理窗口标题明确匹配 TITLES 的对话框
- 只点击 TEXT_ALIASES 白名单里的按钮文字
- 默认点「导出」= 用现有设置导出，绝不点「更新受影响的照片」（会改照片外观）
"""
import argparse
import ctypes
import ctypes.wintypes as wt
import sys
import time

user32 = ctypes.WinDLL("user32", use_last_error=True)

EnumWindows = user32.EnumWindows
EnumChildWindows = user32.EnumChildWindows
GetWindowTextW = user32.GetWindowTextW
GetWindowTextLengthW = user32.GetWindowTextLengthW
GetClassNameW = user32.GetClassNameW
IsWindowVisible = user32.IsWindowVisible
GetWindowThreadProcessId = user32.GetWindowThreadProcessId
PostMessageW = user32.PostMessageW

WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)
BM_CLICK = 0x00F5

# 只有这些标题的对话框会被处理
TITLES = ("推荐 AI 更新", "Recommend AI Updates")

# 按钮白名单：别名 -> 实际可能出现的文字
TEXT_ALIASES = {
    "导出": ("导出", "Export"),
    "取消": ("取消", "Cancel"),
}

# 明确禁止点击的按钮（点了会改动照片外观）
FORBIDDEN = ("更新受影响的照片", "Update Affected Photos")


def _text(hwnd):
    n = GetWindowTextLengthW(hwnd)
    if n <= 0:
        return ""
    buf = ctypes.create_unicode_buffer(n + 2)
    GetWindowTextW(hwnd, buf, n + 2)
    return buf.value


def _class(hwnd):
    buf = ctypes.create_unicode_buffer(256)
    GetClassNameW(hwnd, buf, 256)
    return buf.value


def find_dialogs(pids=None):
    """返回 [(hwnd, title)]，只含可见且标题在白名单里的窗口。"""
    found = []

    def cb(hwnd, _):
        if not IsWindowVisible(hwnd):
            return True
        if pids is not None:
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
    """返回 [(hwnd, text)]，对话框里的所有 Button 子控件。"""
    out = []

    def cb(hwnd, _):
        if _class(hwnd) == "Button":
            out.append((hwnd, _text(hwnd)))
        return True

    EnumChildWindows(dlg, WNDENUMPROC(cb), 0)
    return out


def lightroom_pids():
    pids = set()
    # 用 tasklist 拿 PID，避免依赖 psutil
    import subprocess
    try:
        out = subprocess.run(
            ["tasklist", "/fi", "imagename eq lightroom.exe", "/fo", "csv", "/nh"],
            capture_output=True, text=True, timeout=10,
        ).stdout
        for line in out.splitlines():
            parts = [p.strip('"') for p in line.split('","')]
            if len(parts) >= 2 and parts[0].lower().startswith("lightroom"):
                pids.add(int(parts[1]))
    except Exception:
        pass
    return pids or None


def click_choice(choice="导出", pids=None, verbose=True):
    """找到对话框并点击指定按钮。返回 (是否点到, 说明)。"""
    dialogs = find_dialogs(pids)
    if not dialogs:
        return False, "没有发现对话框"

    wanted = TEXT_ALIASES.get(choice, (choice,))
    for dlg, title in dialogs:
        buttons = find_buttons(dlg)
        if verbose:
            print(f"  对话框 hwnd={dlg} 标题={title!r} 按钮: {[b[1] for b in buttons]}")
        for bh, btext in buttons:
            if btext in FORBIDDEN:
                continue
            if btext in wanted:
                ok = PostMessageW(bh, BM_CLICK, 0, 0)
                if verbose:
                    print(f"  点击 {btext!r} (hwnd={bh}) -> {ok}")
                return bool(ok), f"已点击 {btext}"
    return False, f"对话框里没找到按钮 {choice!r}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--watch", type=int, default=0, help="守护多少秒（0=不限）")
    ap.add_argument("--interval", type=float, default=1.0, help="轮询间隔秒")
    ap.add_argument("--once", action="store_true", help="只查一次")
    ap.add_argument("--choose", default="导出", help="点哪个按钮，默认导出")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    pids = lightroom_pids()
    if pids is None:
        print("Lightroom 未运行")
        return 1

    if args.once:
        ok, msg = click_choice(args.choose, pids, verbose=not args.quiet)
        print(msg)
        return 0 if ok else 2

    start = time.time()
    clicked = 0
    last_report = 0
    if not args.quiet:
        print("守护中，发现「推荐 AI 更新」就点「导出」...")
    while True:
        ok, msg = click_choice(args.choose, pids, verbose=not args.quiet)
        if ok:
            clicked += 1
            if not args.quiet:
                print(f"[{time.strftime('%H:%M:%S')}] 第 {clicked} 次代点：{msg}")
        elapsed = time.time() - start
        if args.watch and elapsed > args.watch:
            break
        if not args.quiet and elapsed - last_report >= 30:
            print(f"  ...已守护 {int(elapsed)}s，代点 {clicked} 次")
            last_report = elapsed
        time.sleep(args.interval)

    if not args.quiet:
        print(f"守护结束，共代点 {clicked} 次")
    return 0


if __name__ == "__main__":
    sys.exit(main())
