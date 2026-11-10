# 桥接安装与协议

## 为什么用文件队列而不是 MCP / Computer Use

| 方案 | 精确度 | 可靠性 | 结论 |
| --- | --- | --- | --- |
| Computer Use（模拟鼠标） | 拖滑块拖不准，蒙版坐标做不到 | 被弹窗、焦点、分辨率干扰 | 只能做粗活 |
| MCP over HTTP | 好 | 需要常驻服务和端口 | 可用但依赖多 |
| **文件队列（本方案）** | **能写小数点后 6 位、能写 17 层蒙版** | **只依赖文件系统** | **选它** |

Lightroom 插件跑在 LR 自己的 Lua 解释器里，权限等同于用户在界面上操作，
所以 SDK 能做的它都能做，且没有 UI 自动化的一切不确定性。

## 目录结构

```
<ROOT>/                     ROOT 默认 ~/lr_bridge，可用环境变量 LR_BRIDGE_ROOT 覆盖
├── inbox/                  客户端写命令：<id>.cmd
├── outbox/                 插件写结果：<id>.res
└── heartbeat               插件心跳：时间戳|版本|运行中
```

**两端 ROOT 必须一致。** Python 端解析顺序：`LR_BRIDGE_ROOT` > `O:\lr_bridge`（历史路径）
> `~/lr_bridge`。Lua 端（`BridgeCore.lua`）用同一套规则。

## 安装

1. 把 `assets/plugin/AIBridge.lrplugin` 整个目录复制到：
   - Windows: `%APPDATA%\Adobe\Lightroom\Modules\`
   - macOS: `~/Library/Application Support/Adobe/Lightroom/Modules/`
2. 打开 Lightroom → 文件 → 增效工具管理器 → 添加 → 选中该目录 → 启用
3. 启动后会在 ROOT 下建目录并写心跳
4. 验证：`python scripts/lr_bridge.py ping`

改完 Lua 代码需要重新加载插件：增效工具管理器里取消勾选再勾选，**不需要重启 Lightroom**。

## 协议

### 命令格式

一行一个字段，`key|type|value`，按顺序排列：

```
op|s|develop_set
path.1|s|D:\pics\a.NEF
set.Exposure2012|f|0.35
set.Contrast2012|f|8
```

类型：`s` 字符串 / `f` 浮点 / `i` 整数 / `b` 布尔。
值里的 `\` `|` 换行需要转义成 `\\` `\|` `\n`。

### 响应格式

同样格式，首部必带 `id` 和 `op`，尾部必带 `ok` 和 `elapsed`。
失败时 `ok|b|false` + `err|s|<原因>`。

### 支持的 op

| op | 作用 | 关键参数 |
| --- | --- | --- |
| `ping` | 探活，返回 catalog 路径 | — |
| `status` | 心跳与队列状态 | — |
| `selection` | 当前选中的照片信息 | `path.N`（可选） |
| `develop_get` | 读指定参数 | `path.N`、`key.N` |
| `develop_dump` | 读全部参数（约 1000 字段） | `path.N`、`filter` |
| `develop_set` | 写全局参数 | `path.N`、`set.Key` |
| `develop_set_tree` | 写嵌套结构（蒙版） | `path.N`、`set.<a.b.c>` |
| `export` | 导出 | `dest`、`format`、`longEdge`、`quality` |
| `import` | 导入 | `path.N` |
| `select` | 按路径选中 | `path.N` |
| `meta_set` | 评分/色标 | `rating`、`label` |
| `probe_api` | 探测 SDK 方法可用性 | — |

## 轮询机制

插件每 0.4 秒扫一次 inbox，每次最多处理 6 条，处理完删除命令文件。
心跳每 3 秒写一次。客户端默认超时 8 秒。

**写入后不要立刻导出。** `develop_set` 返回 `ok` 只代表 LR 收到了设置，
渲染管线可能还没刷新。等 2–3 秒再 export，否则会导到中间状态
（这是「导出的图和界面上看到的不一样」的常见原因）。

## 故障排查

### ping 超时 / 没有 outbox 文件

1. 看 ROOT 下有没有 `heartbeat`，时间戳是否是最近 3 秒
2. 没有心跳 → 插件没跑起来：增效工具管理器里是否启用、LR 是否在 Library/Develop 模块
3. 有心跳但没响应 → 检查 inbox 里是否堆积 `.cmd` 文件，堆积说明轮询线程被阻塞

### 心跳停了，但任务管理器显示 Lightroom「正常响应」

**这是最坑的一种。** 导出带 AI 蒙版的照片时，LR 会弹「推荐 AI 更新」模态框，
整个 Lua 环境被阻塞，心跳停、inbox 积压，但进程状态仍然是 Responding。
从外部看不出来，只会表现为「桥接突然卡死」。

**第一反应：去点「导出」按钮。** 不是怀疑桥接坏了，不是重启 Lightroom。

```bash
python scripts/lr_unstick.py          # 自动找「推荐 AI 更新」框并点「导出」
python scripts/lr_unstick.py --list   # 只看不点
```

手工办法：枚举 LR 的可见窗口，找 `TITLE=[推荐 AI 更新]`，点它子窗口里
文字为 `导出` 的 Button（`SendMessage(hwnd, 0x00F5, 0, 0)`）。

**绝不能点「更新受影响的照片」**——那会重算所有 AI 蒙版，几十分钟起步，且改变照片外观。

**根治**：把首选项里的警告开关关掉，导出就不会弹。

```bash
python scripts/lr_export_safe.py --path "<照片>" --dest out --long-edge 2400
# 或单独关：python scripts/fix_ai_dialog.py
```

原理与实测细节见 `mask-selection.md`。一句话：改
`AIUpdateWarning_shouldUpdateAffectedPhotos = false`，实时生效、不用重启，
但 LR 会在约 2 分钟后把文件写回 true（内存仍生效），**重启后要重跑**，
所以包装器每次导出都过一遍。

解卡后验证三件事：心跳恢复、inbox 清空、导出目录出现文件。
**如果 inbox 里积压着会覆盖数据的命令（整棵蒙版树），先删掉那条再解卡。**

### 中文路径

`cv2.imread` 在 Windows 上打不开中文路径，用 `PIL` 或 `np.fromfile + cv2.imdecode`。
另外 K 盘可能禁用 8.3 短名，不要依赖短路径绕过。

### 文件被占用 / 删除失败

Lua 沙箱里 `os.remove` 不可用，必须用 `LrFileUtils.delete`。
本方案的插件已经这么处理了。

### 写入成功但读回没变

两点排查：
1. 键名错了。局部参数是 `LocalExposure2012`，不是 `Exposure2012`，也不是 `local_exposure`
2. 值是只读字段。`CameraProfile` 可写，但相机配置文件的**安装状态**不可写

写一个「当前值」再读回，如果读回变了说明通道通；没变说明字段被丢弃。
