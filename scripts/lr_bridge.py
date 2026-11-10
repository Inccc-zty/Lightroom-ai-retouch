#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Lightroom Classic 桥接客户端。

与 AIBridge.lrplugin 通过统一根目录下的文件队列通信：
  写 inbox\\<id>.cmd  ->  插件执行  ->  读 outbox\\<id>.res

用法示例：
  python lr_bridge.py ping
  python lr_bridge.py status
  python lr_bridge.py selection
  python lr_bridge.py develop-get
  python lr_bridge.py develop-set --set Exposure2012=0.35 --set Contrast2012=8
  python lr_bridge.py export --dest "./out" --format JPEG --long-edge 2048
  python lr_bridge.py import --path "/path/to/a.dng"
  python lr_bridge.py select --path "/path/to/a.dng"
  python lr_bridge.py meta --rating 5 --label Red
"""

from __future__ import annotations

import json
import os
import sys
import time
import uuid

def _resolve_root() -> str:
    """桥接根目录。解析顺序（与插件端 BridgeCore.lua 完全一致）：

    1. 环境变量 ``LR_BRIDGE_ROOT``
    2. ``~/lr_bridge``（推荐，跨平台默认）
    3. ``O:\\lr_bridge``（兼容早期安装，仅当该目录已存在）

    两端必须指向同一目录，否则命令会写进一个没人读的队列。
    换机器时最省事的做法是设环境变量 ``LR_BRIDGE_ROOT``。
    """
    env = os.environ.get("LR_BRIDGE_ROOT")
    if env:
        return env
    preferred = os.path.join(os.path.expanduser("~"), "lr_bridge")
    if os.path.isdir(preferred):
        return preferred
    legacy = r"O:\lr_bridge"
    if os.path.isdir(legacy):
        return legacy
    return preferred


ROOT = _resolve_root()
INBOX = os.path.join(ROOT, "inbox")
OUTBOX = os.path.join(ROOT, "outbox")


# ---------------------------------------------------------------- 协议编解码

def _esc(s: str) -> str:
    return (str(s).replace("\\", "\\\\").replace("|", "\\|")
            .replace("\r", "\\r").replace("\n", "\\n"))


def _unesc(s: str) -> str:
    out, i, n = [], 0, len(s)
    while i < n:
        c = s[i]
        if c == "\\" and i + 1 < n:
            d = s[i + 1]
            if d in ("n", "r", "t", "\\", "|"):
                out.append({"n": "\n", "r": "\r", "t": "\t"}.get(d, d))
            else:
                out.append(c + d)
            i += 2
        else:
            out.append(c)
            i += 1
    return "".join(out)


def _split3(line: str):
    fields, cur, i, n = [], [], 0, len(line)
    while i < n:
        c = line[i]
        if c == "\\" and i + 1 < n:
            cur.append(line[i:i + 2])
            i += 2
        elif c == "|":
            fields.append("".join(cur))
            cur = []
            i += 1
        else:
            cur.append(c)
            i += 1
    fields.append("".join(cur))
    return fields


def _coerce(typ: str, raw: str):
    if typ == "i":
        try:
            return int(raw)
        except ValueError:
            return 0
    if typ == "f":
        try:
            return float(raw)
        except ValueError:
            return 0.0
    if typ == "b":
        return raw in ("1", "true")
    if typ == "a":
        return [float(x) for x in raw.split(",") if x.strip()]
    return raw


def _parse_result(text: str) -> dict:
    out = {}
    for line in text.split("\n"):
        line = line.rstrip("\r")
        if not line:
            continue
        f = _split3(line)
        if len(f) < 3:
            continue
        out[_unesc(f[0])] = _coerce(f[1], _unesc(f[2]))
    return out


# ---------------------------------------------------------------- 传输

def _ensure_dirs():
    os.makedirs(INBOX, exist_ok=True)
    os.makedirs(OUTBOX, exist_ok=True)


def heartbeat_age() -> float | None:
    """返回心跳文件年龄（秒），无心跳返回 None。"""
    p = os.path.join(ROOT, "heartbeat.txt")
    if not os.path.exists(p):
        return None
    return time.time() - os.path.getmtime(p)


def send(op: str, fields: list[tuple[str, str, object]] | None = None,
         timeout: float = 30.0, wait: bool = True) -> dict:
    """发送一条命令并等待结果。

    fields: [(key, type, value)]，例如 [("set.Exposure2012", "f", 0.35)]
    """
    _ensure_dirs()
    cid = f"{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"

    lines = [f"op|s|{_esc(op)}", f"id|s|{_esc(cid)}"]
    for key, typ, val in (fields or []):
        if typ == "a":
            val = ",".join(f"{float(v):.6g}" for v in val)
        elif typ == "b":
            val = "1" if val else "0"
        elif typ == "f":
            val = f"{float(val):.6g}"
        elif typ == "i":
            val = str(int(val))
        lines.append(f"{_esc(key)}|{typ}|{_esc(val)}")

    tmp = os.path.join(INBOX, cid + ".tmp")
    cmd = os.path.join(INBOX, cid + ".cmd")
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")
    os.replace(tmp, cmd)

    if not wait:
        return {"id": cid, "sent": True}

    res_path = os.path.join(OUTBOX, cid + ".res")
    deadline = time.time() + timeout
    while time.time() < deadline:
        if os.path.exists(res_path):
            with open(res_path, "r", encoding="utf-8", errors="replace") as f:
                data = _parse_result(f.read())
            try:
                os.remove(res_path)
            except OSError:
                pass
            return data
        time.sleep(0.12)

    age = heartbeat_age()
    if age is None:
        hint = "Lightroom 似乎没在运行，或插件没被加载（检查 文件 > 增效工具额外功能 菜单）"
    elif age > 15:
        hint = f"心跳已停 {age:.0f} 秒，插件循环可能已中断"
    else:
        hint = "插件在线但没在 0.12s 内处理完，可加大 --timeout"
    raise TimeoutError(f"等待 {timeout}s 无结果。{hint}")


# ---------------------------------------------------------------- CLI

def _flatten_tree(obj, prefix: str, out: list) -> None:
    """把嵌套 dict/list 展平成 (点号路径, 类型, 值)，供插件端还原成 Lua 表。"""
    if isinstance(obj, dict):
        for k, v in obj.items():
            _flatten_tree(v, f"{prefix}.{k}" if prefix else str(k), out)
    elif isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj, 1):
            _flatten_tree(v, f"{prefix}.{i}", out)
    elif isinstance(obj, bool):
        out.append((prefix, "b", obj))
    elif isinstance(obj, (int, float)):
        out.append((prefix, "f", float(obj)))
    elif obj is None:
        return
    else:
        out.append((prefix, "s", str(obj)))


def send_tree(op: str, tree: dict, paths: list[str] | None = None,
              timeout: float = 120.0) -> dict:
    """按嵌套结构发送（用于蒙版这类深层表）。"""
    fields: list[tuple[str, str, object]] = []
    for i, p in enumerate(paths or [], 1):
        fields.append((f"path.{i}", "s", p))
    flat: list[tuple[str, str, object]] = []
    _flatten_tree(tree, "", flat)
    for k, t, v in flat:
        fields.append((f"set.{k}", t, v))
    return send(op, fields, timeout=timeout)


def _kv_args(pairs: list[str]) -> list[tuple[str, str, object]]:
    out = []
    for item in pairs:
        if "=" not in item:
            raise SystemExit(f"参数格式应为 key=value：{item}")
        k, v = item.split("=", 1)
        try:
            out.append((k, "f", float(v)))
        except ValueError:
            out.append((k, "s", v))
    return out


def _multi_paths(paths: list[str]) -> list[tuple[str, str, object]]:
    return [(f"path.{i + 1}", "s", p) for i, p in enumerate(paths)]


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2

    op = argv[1]
    args = argv[2:]

    if op == "tree-set":
        jf = args[args.index("--json") + 1] if "--json" in args else None
        if not jf:
            raise SystemExit("需要 --json <树结构文件>")
        with open(jf, encoding="utf-8") as f:
            tree = json.load(f)
        paths = [a for i, a in enumerate(args) if i > 0 and args[i - 1] == "--path"]
        try:
            data = send_tree("develop_set_tree", tree, paths, timeout=120)
        except TimeoutError as exc:
            print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
            return 1
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0 if data.get("ok") else 1

    def opt(name, default=None):
        if name in args:
            i = args.index(name)
            if i + 1 < len(args):
                return args[i + 1]
        return default

    def opt_all(name):
        out = []
        i = 0
        while i < len(args):
            if args[i] == name and i + 1 < len(args):
                out.append(args[i + 1])
                i += 2
            else:
                i += 1
        return out

    fields: list[tuple[str, str, object]] = []
    timeout = float(opt("--timeout", "30"))

    if op == "ping":
        fields = []
        timeout = float(opt("--timeout", "8"))
    elif op == "status":
        fields = []
        timeout = float(opt("--timeout", "15"))
    elif op == "selection":
        fields = _multi_paths(opt_all("--path"))
    elif op == "develop-get":
        fields = _multi_paths(opt_all("--path"))
        op = "develop_get"
    elif op == "develop-set":
        fields = _multi_paths(opt_all("--path"))
        fields += [("set." + k, t, v) for k, t, v in _kv_args(opt_all("--set"))]
        op = "develop_set"
    elif op == "export":
        dest = opt("--dest")
        if not dest:
            raise SystemExit("需要 --dest <目录>")
        fields = _multi_paths(opt_all("--path")) + [
            ("dest", "s", dest),
            ("format", "s", opt("--format", "JPEG")),
            ("quality", "f", float(opt("--quality", "0.9"))),
            ("longEdge", "i", int(opt("--long-edge", "0"))),
            ("reimport", "i", 1 if "--reimport" in args else 0),
        ]
        timeout = float(opt("--timeout", "600"))
    elif op == "import":
        paths = opt_all("--path")
        if not paths:
            raise SystemExit("需要 --path")
        fields = _multi_paths(paths)
        timeout = float(opt("--timeout", "300"))
    elif op == "select":
        fields = _multi_paths(opt_all("--path"))
        if not fields:
            raise SystemExit("需要 --path")
    elif op == "meta":
        fields = _multi_paths(opt_all("--path"))
        if opt("--rating") is not None:
            fields.append(("rating", "i", int(opt("--rating"))))
        if opt("--label") is not None:
            fields.append(("label", "s", opt("--label")))
        op = "meta_set"
    elif op == "reveal":
        fields = [("module", "s", opt("--module", "develop"))]
    elif op == "mask-probe":
        fields = []
        timeout = float(opt("--timeout", "20"))
        op = "mask_probe"
    elif op == "mask-ai":
        fields = _multi_paths(opt_all("--path"))
        fields.append(("maskSubtype", "s", opt("--subtype", "sky")))
        fields.append(("settle", "f", float(opt("--settle", "2.5"))))
        fields += [("local." + k, t, v) for k, t, v in _kv_args(opt_all("--local"))]
        timeout = float(opt("--timeout", "180"))
        op = "mask_ai"
    elif op == "mask-list":
        fields = _multi_paths(opt_all("--path"))
        timeout = float(opt("--timeout", "60"))
        op = "mask_list"
    elif op == "mask-boolean":
        fields = _multi_paths(opt_all("--path")) + [
            ("op", "s", opt("--bool", "intersect")),
            ("maskType", "s", opt("--type", "rangeMask")),
            ("maskSubtype", "s", opt("--sub", "")),
            ("maskId", "s", opt("--mask", "")),
        ]
        timeout = float(opt("--timeout", "120"))
        op = "mask_boolean"
    elif op == "mask-set":
        fields = _multi_paths(opt_all("--path")) + [("maskId", "s", opt("--mask", ""))]
        fields += [("local." + k, t, v) for k, t, v in _kv_args(opt_all("--local"))]
        timeout = float(opt("--timeout", "60"))
        op = "mask_set"
    elif op == "mask-delete":
        fields = _multi_paths(opt_all("--path")) + [("maskId", "s", opt("--mask", ""))]
        timeout = float(opt("--timeout", "60"))
        op = "mask_delete"
    elif op == "mask-reset":
        fields = _multi_paths(opt_all("--path"))
        timeout = float(opt("--timeout", "60"))
        op = "mask_reset"
    elif op == "mask-geo":
        fields = _multi_paths(opt_all("--path")) + [
            ("kind", "s", opt("--kind", "radialGradient"))]
        fields += [("local." + k, t, v) for k, t, v in _kv_args(opt_all("--local"))]
        timeout = float(opt("--timeout", "120"))
        op = "mask_geo"
    elif op == "diag":
        fields = []
    elif op == "probe":
        op = "probe_api"
    elif op == "paste-test":
        fields = _multi_paths(opt_all("--path"))
        fields += [("set." + k, t, v) for k, t, v in _kv_args(opt_all("--set"))]
        op = "paste_test"
    elif op == "dump":
        fields = _multi_paths(opt_all("--path")) + [("filter", "s", opt("--filter", ""))]
        timeout = float(opt("--timeout", "60"))
        op = "develop_dump"
    else:
        raise SystemExit(f"未知命令：{op}\n{__doc__}")

    try:
        data = send(op, fields, timeout=timeout)
    except TimeoutError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 1

    print(json.dumps(data, ensure_ascii=False, indent=2))
    return 0 if data.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
