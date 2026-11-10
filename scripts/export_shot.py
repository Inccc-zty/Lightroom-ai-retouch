#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""导出带 AI 蒙版的照片，自动处理「推荐 AI 更新」弹框。

为什么需要它
------------
LR 导出任何带 AI 蒙版的照片都会弹「推荐 AI 更新」模态框，把插件循环堵死。
改首选项 `AIUpdateWarning_shouldUpdateAffectedPhotos = false` **不可靠**：
LR 会把它写回 true，而且内存里的值也不一定跟着变。实测改了 3 分钟后又弹。

**唯一稳定有效的是点「导出」按钮。** 本脚本就是把这个动作自动化：
起一个导出子进程，同时轮询输出目录，发现没出图就去点框，最多重试 N 次。

用法
----
    python export_shot.py --path "<照片>" --dest out --long-edge 2400
    python export_shot.py --path "<照片>" --dest out --long-edge 4000 --quality 0.92
    python export_shot.py --path "<照片>" --dest out --no-unstick    # 只导出不点框

退出码：0 成功，1 超时/失败
"""
import argparse
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
BRIDGE = os.path.join(HERE, "lr_bridge.py")
UNSTICK = os.path.join(HERE, "lr_unstick.py")

PREF = os.path.expanduser(
    r"~\AppData\Roaming\Adobe\Lightroom\Preferences\Lightroom Classic CC 7 Preferences.agprefs"
)


def mute_warning():
    """尽量把首选项置 false。不可靠，只当第一道防线。"""
    try:
        if not os.path.isfile(PREF):
            return
        b = open(PREF, "rb").read()
        old = b"AIUpdateWarning_shouldUpdateAffectedPhotos = true"
        if old in b:
            open(PREF, "wb").write(
                b.replace(old, b"AIUpdateWarning_shouldUpdateAffectedPhotos = false")
            )
            print("  [首选项] 已置 false（不保证生效）")
    except Exception as e:
        print("  [首选项] 跳过: %s" % e)


def find_output(dest, stem):
    """输出目录里是否有以 stem 开头的 jpg（LR 可能加 -2 后缀）。"""
    if not os.path.isdir(dest):
        return None
    for f in os.listdir(dest):
        if f.lower().startswith(stem.lower()) and f.lower().endswith((".jpg", ".jpeg")):
            p = os.path.join(dest, f)
            if os.path.getsize(p) > 1024:
                return p
    return None


def main():
    ap = argparse.ArgumentParser(description="带弹框自动处理的导出")
    ap.add_argument("--path", required=True, help="照片绝对路径")
    ap.add_argument("--dest", required=True, help="输出目录")
    ap.add_argument("--long-edge", type=int, default=2400)
    ap.add_argument("--quality", type=float, default=0.92)
    ap.add_argument("--timeout", type=int, default=180, help="总超时秒数")
    ap.add_argument("--no-unstick", action="store_true", help="不自动点框")
    ap.add_argument("--mute", action="store_true", help="先尝试改首选项（不可靠）")
    args = ap.parse_args()

    if not os.path.isfile(BRIDGE):
        sys.exit("找不到 lr_bridge.py: %s" % BRIDGE)

    os.makedirs(args.dest, exist_ok=True)
    stem = os.path.splitext(os.path.basename(args.path))[0]

    if args.mute:
        mute_warning()

    cmd = [
        sys.executable, BRIDGE, "export",
        "--path", args.path,
        "--dest", args.dest,
        "--format", "JPEG",
        "--long-edge", str(args.long_edge),
        "--quality", str(args.quality),
    ]
    print("[导出] %s -> %s (%dpx)" % (stem, args.dest, args.long_edge))
    t0 = time.time()
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)

    last_unstick = 0.0
    unstick_count = 0
    out = None
    while time.time() - t0 < args.timeout:
        out = find_output(args.dest, stem)
        if out:
            break
        if proc.poll() is not None:
            # 命令结束了但没文件：可能失败
            time.sleep(1)
            out = find_output(args.dest, stem)
            break
        # 超过 8 秒还没出图，怀疑弹框
        if not args.no_unstick and time.time() - t0 > 8 and time.time() - last_unstick > 12:
            unstick_count += 1
            print("  [弹框] 第 %d 次尝试点「导出」..." % unstick_count)
            try:
                subprocess.run([sys.executable, UNSTICK], timeout=40,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception as e:
                print("    点框失败: %s" % e)
            last_unstick = time.time()
        time.sleep(2)

    # 收尾
    try:
        proc.wait(timeout=5)
    except Exception:
        proc.kill()

    elapsed = time.time() - t0
    out = find_output(args.dest, stem)
    if out:
        size = os.path.getsize(out) / 1024.0 / 1024.0
        print("[完成] %.1fs  %.1fMB  %s" % (elapsed, size, out))
        return 0
    print("[失败] %.1fs 内没有产出文件（弹框 %d 次）" % (elapsed, unstick_count))
    print("  排查：1) 心跳是否停  2) inbox 是否积压  3) LR 是否有别的模态框")
    return 1


if __name__ == "__main__":
    sys.exit(main())
