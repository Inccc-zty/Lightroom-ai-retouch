# 蒙版数据结构

## 整体结构

蒙版存放在 `MaskGroupBasedCorrections` 下，每层一个编号，层内是参数表 + 蒙版表：

```json
{
  "MaskGroupBasedCorrections": {
    "1": {
      "CorrectionName": "15 主石顶光",
      "CorrectionActive": true,
      "CorrectionAmount": 1.0,
      "CorrectionID": "<uuid>",
      "CorrectionSyncID": "<uuid>",
      "CorrectionReferenceX": 0.44,
      "CorrectionReferenceY": 0.75,
      "What": "Correction",
      "LocalExposure2012": 0.0444,
      "LocalClarity2012": 0.12,
      "LocalTexture": 0.08,
      "CorrectionMasks": {
        "1": {
          "What": "Mask/CircularGradient",
          "MaskActive": true,
          "MaskValue": 1.0,
          "MaskInverted": false,
          "MaskBlendMode": 0.0,
          "MaskName": "径向渐变 1",
          "MaskID": "<uuid>",
          "MaskSyncID": "<uuid>",
          "Left": 0.27, "Top": 0.66, "Right": 0.60, "Bottom": 0.83,
          "Angle": 0.0, "Midpoint": 50.0, "Feather": 55.0,
          "Roundness": 0.0, "Flipped": false
        }
      }
    }
  }
}
```

## 三种蒙版类型

| What | 类型 | 几何字段 |
| --- | --- | --- |
| `Mask/Gradient` | 线性渐变 | `ZeroX/ZeroY`（零值端）、`FullX/FullY`（满值端） |
| `Mask/CircularGradient` | 径向渐变 | `Left/Top/Right/Bottom` 外接框 + `Angle/Midpoint/Feather/Roundness/Flipped` |
| `Mask/Image` | AI 主体/天空 | `MaskSubType` + `MaskVersion` + `MaskName` |

### 线性渐变的方向（最容易搞反）

`Zero` 端是**零值**，`Full` 端是**满值**。

```python
# 从画面上方往下压：上方满值、下方零值
"zero": [0.5, 0.82], "full": [0.5, 0.0]     # y=0 满，y=0.82 归零

# 从画面下方往上压：下方满值
"zero": [0.5, 0.5], "full": [0.5, 1.06]
```

方向搞反的后果是蒙版作用在相反的一侧，且因为渐变很柔和，肉眼不容易一眼看出。

### 径向渐变的羽化

`Feather` 默认 55，指的是从中心到边缘的过渡比例。**55 意味着提亮会摊得很开**，
想集中照亮一小块石头，要降到 25–30，否则提亮会糊到周围草地，
看起来像「整片区域被均匀提亮」，失去塑形效果。

`Roundness` 控制圆的扁率（0 = 正圆，100 = 极扁），`Angle` 是旋转角度。

## 局部参数量纲

**局部曝光要除 4.5，其余除 100。**

```python
LocalExposure2012 = ev / 4.5        # −1.0 EV → −0.2222
LocalClarity2012  = clarity / 100   # +12 → 0.12
LocalHighlights2012 = highlights / 100
```

`build_layer()` 已经处理好了，直接传 `ev=0.2, clarity=12` 即可。

## 完整的局部参数键

```
LocalExposure2012   LocalContrast2012    LocalHighlights2012
LocalShadows2012    LocalWhites2012      LocalBlacks2012
LocalClarity2012    LocalTexture         LocalDehaze
LocalSaturation     LocalTemperature     LocalTint
LocalSharpness      LocalBrightness      LocalHue
LocalLuminanceNoise LocalGrain           LocalMoire
LocalDefringe       LocalToningHue       LocalToningSaturation
LocalCurveRefineSaturation
```

`LocalExposure2012` 是唯一带 4.5 换算的。写成 `Exposure2012` 或 `LocalExposure`
会被静默丢弃，表现为「写了但没反应」。

## AI 天空蒙版

```json
{
  "What": "Mask/Image",
  "MaskSubType": 2,
  "MaskVersion": 1,
  "MaskName": "Sky 1"
}
```

不需要 `MaskDigest`，Lightroom 自己算位图。

边界紧贴树冠，比线性渐变干净一个量级——山脊不会被误压。48MP 照片也能正常处理。

**误判记录**：曾把「导出卡死」归因为「45MP 照片 AI 天空吃爆内存」，实际真凶是
导出时弹出的「推荐 AI 更新」模态框。进程状态仍显示正常响应，从外部看不出来。
详见 `pitfalls.md`。

## 不能做的两件事

### 1. 亮度/颜色范围蒙版

`RangeMaskType`、`RangeMaskMin/Max` 等字段**写不进去**，被静默丢弃。
想做「只压暗暗部」这类操作，只能用几何蒙版近似，或改用全局的阴影/黑色色阶。

### 2. 蒙版层内布尔运算（写入层面）

一个 correction 可以挂多个 `CorrectionMasks`，但写入 `CorrectionMasks.2` 之后，
`MaskBlendMode` 会被 Lightroom 强制归零，第二个蒙版不参与运算。

**结论：一个层只能有一个生效蒙版。**

想实现「A 减 B」，只能用 UI 层 API。SDK 里有这条路：

```
selectTool("masking") → selectMask(id) → addToCurrentMask / subtractFromCurrentMask
→ intersectWithCurrentMask → 轮询 getAllMasks()
```

但这些是**在 Lightroom 界面里操作**，需要用户在 Develop 模块下，且过程不可控，
不适合批处理。设计蒙版方案时，优先考虑「用多个层 + 几何错位」代替布尔运算。

## 层号必须连续，从 1 开始

`MaskGroupBasedCorrections` 的键是 `"1"` `"2"` `"3"`…，**不允许跳号**。

实测：一棵树用 1,2,4,5,…,15（缺 3），`tree-set` 返回 `"ok": false`，整表被拒，
照片上还是旧蒙版。排查半天以为是结构问题，实际只是缺一个 3。
重排成 1..14 后立刻写入成功。

**增删层之后必须重排编号再写。写入后必须检查返回的 `ok`，
看到 `false` 就是整表没进去，不要接着导出。**


## 追加新建层的正确做法

**不要只传新层。** `MaskGroupBasedCorrections` 是整表替换语义，只传新层会把旧层全删掉。

**零层照片可以直接写入。** 早期结论「LR 不接受从零写入、必须先手动加一个蒙版」是误判，
实测一张 0 层蒙版的照片（Z03_9666）直接 `tree-set` 写入 45 个字段全部生效。
当时失败的真实原因是层内缺 `Local*` 默认键，补一套全零的即可（`mask_append.py`
里的 `DEFAULT_TPL`）。

正确流程（`mask_append.py` 已实现）：

1. `dump` 读全部字段
2. 反解出嵌套的现有层（为零则用内置零模板）
3. 在现有层基础上追加新层
4. 整表写回
5. 立即回读，逐字段比对新层是否到齐、旧层是否漂移

回读时要忽略 `MaskID` / `MaskSyncID` / `CorrectionID` / `CorrectionSyncID` /
`CorrectionReferenceX` / `CorrectionReferenceY`，这些 Lightroom 会自己重排。

## 蒙版设计原则

1. **一层管一件事**。不要在同一个层里既提亮又加饱和又降色温，出问题无法归因
2. **层名写清楚**。`15 主石顶光` 比 `蒙版 15` 有用得多，回读和排错全靠它
3. **几何留余量**。径向框比目标稍大一点，靠 `Feather` 收边，硬边会露接缝
4. **相邻层不要重叠太多**，否则效果叠加失控。重叠区要算总 EV：
   `−0.11 + (−0.09) = −0.20 EV`，不是各算各的
