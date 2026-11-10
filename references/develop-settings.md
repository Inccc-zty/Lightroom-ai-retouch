# 全局参数：键名、量纲、可写性

## 量纲（最容易错，先看这条）

| 类别 | 规则 | 示例 |
| --- | --- | --- |
| 曝光类（全局） | 直接用 EV，1:1 | `Exposure2012 = -0.20` 就是 −0.20 EV |
| 曝光类（局部蒙版） | **`LocalExposure2012 = EV ÷ 4.5`** | −1.0 EV 写成 `-0.2222` |
| 其余滑块 | −100..100 原值，1:1 | `Highlights2012 = -56` |
| 局部其余滑块 | −100..100 **÷ 100** | 局部高光 −34 写成 `-0.34` |

**这个 4.5 倍差是最大的数字陷阱。** 报数给用户或写文档时，
务必写清是 `LocalExposure2012` 的原始值还是换算后的 EV：

```python
local_value = ev / 4.5      # 写入时
ev = local_value * 4.5      # 读出来换算时
```

曾经把 `LocalExposure2012 = -0.0178` 直接当 "−0.018 EV" 汇报，
实际是 −0.08 EV，差了 4.5 倍，导致「改动太小所以看不出」这个错误结论。

## 基本面板

| 键名 | 范围 | 说明 |
| --- | --- | --- |
| `Exposure2012` | −5..+5 | EV，1:1 |
| `Contrast2012` | −100..100 | 小于 10 基本等于没加对比 |
| `Highlights2012` | −100..100 | 负值压高光 |
| `Shadows2012` | −100..100 | **正值抬暗部，会把剪影填平** |
| `Whites2012` | −100..100 | 白场 |
| `Blacks2012` | −100..100 | 黑场，接近 0 = 没有真正的黑 |
| `Texture` | −100..100 | 中频细节，比清晰度克制 |
| `Clarity2012` | −100..100 | 中间调对比，加多了发脏 |
| `Dehaze` | −100..100 | 正值加对比去雾，负值加雾 |
| `Vibrance` | −100..100 | 智能饱和，保护肤色 |
| `Saturation` | −100..100 | 全局饱和 |
| `Temperature` | 2000..50000 | 色温（K），不是偏移量 |
| `Tint` | −100..100 | 绿-品红 |

**⚠ 带不带 `2012` 没有规律，写错就静默失效（不报错、`ok: true`）。**
已经踩过的：

| 错误写法 | 正确写法 | 症状 |
| --- | --- | --- |
| `Vibrance2012` | `Vibrance` | 自然饱和度怎么改都没反应 |
| `Saturation2012` | `Saturation` | 同上 |
| `Texture2012` | `Texture` | 同上 |
| `SharpenMask` | `SharpenEdgeMasking` | 锐化蒙版永远是 0 |
| `Sharpness` | `Sharpness`（本来就没有 2012，别加） | — |

规律：**面板上叫「曝光/对比/高光/阴影/白色/黑色/清晰度」的带 2012；
叫「纹理/自然饱和度/饱和度/去雾/锐化」的不带。** 记不住就写完立刻 dump 回读。

## 色调曲线

| 键名 | 说明 |
| --- | --- |
| `ToneCurvePV2012` | 主通道点曲线，格式 `{输入1, 输出1, 输入2, 输出2, ...}`，0–255 |
| `ToneCurvePV2012Red/Green/Blue` | RGB 三条分通道曲线 |
| `ToneCurveName2012` | 预设名，自定时为 `Custom` |

**注意**：dump 里可能出现 `ToneCurveName2012 = Custom` 但 `ToneCurvePV2012` 为空。
这说明曲线实际没写进去，只是名字被设成了 Custom。判断「有没有拉曲线」要看
`ToneCurvePV2012` 是否有值，不能看名字。

## HSL 八通道

键名格式 `HueAdjustmentRed` / `SaturationAdjustmentRed` / `LuminanceAdjustmentRed`，
颜色名：`Red` `Orange` `Yellow` `Green` `Aqua` `Blue` `Purple` `Magenta`，范围 −100..100。

配色分级常用：橙管肤色与暖光、蓝管天空、绿管植被。

## 色彩分级

| 键名 | 说明 |
| --- | --- |
| `SplitToningShadowHue` / `SplitToningShadowSaturation` | 阴影色相/饱和（LR 12+ 仍可用） |
| `SplitToningHighlightHue` / `SplitToningHighlightSaturation` | 高光色相/饱和 |
| `SplitToningBalance` | 平衡 |
| `ColorGradeShadowLum` / `MidtoneLum` / `HighlightLum` | 三段明度 |

`ColorGrade*` 系列字段在旧版本可能不生效，`SplitToning*` 兼容性更好。

## 相机配置文件 CameraProfile（可写，实测）

这是长期被误判为「只读」的一项。实际情况：

**可以写。** 通过 `photo:applyDevelopSettings({CameraProfile="<名称>"})`，
桥接层是 `develop-set --path <照片> --set CameraProfile=<名称>`。

### 值格式

用**纯名称**，不要带 `Group: ` 前缀：

```
Camera Flat          Camera Standard      Camera Neutral
Camera Vivid         Camera Portrait      Camera Landscape
Camera Monochrome    Adobe Standard       Adobe Color
Adobe Landscape      Adobe Portrait       Adobe Vivid
```

带前缀（`Group: Camera Flat`）也能写进去，Lightroom 会规范化成纯名称，
**两种写法渲染完全等价**（实测导出像素最大差 4、平均差 0.0003、差异像素 0.036%，
属于 JPEG 编码抖动级别）。

### 实测验证记录

在未修过的 NEF 上依次验证：

| 写入值 | 读回值 | 渲染变化 |
| --- | --- | --- |
| `Camera Flat` | `Camera Flat` | 生效 |
| `Group: Camera Neutral` | `Camera Neutral` | 生效 |
| `Adobe Landscape` | `Adobe Landscape` | **平均像素差 7.86、最大 54，确实变了** |
| `Group: Camera Standard` | `Group: Camera Standard` | 恢复原状 |

操作后逐字段比对，除 `CameraProfile` 的字符串表示外**完全一致**，可安全回滚。

### 为什么以前会「切走切不回来」

三个可能原因，按概率排序：

1. **没带 `--path`**，写入落到了当前选中的另一张照片上，然后以为目标照片变了
2. 值拼错，例如 `Adobe Standard v2`、`Camera Standard (Nikon)` 这类不存在的名字，
   LR 静默丢弃，不报错
3. 照片本身不支持该配置文件（比如跨品牌套用 Camera Matching），LR 会回落到 Adobe Standard

### 配置文件对画面的影响

`Camera Flat` / `Adobe Flat` 是为最大后期空间设计的**最平**配置，直方图挤在中间，
暗部抬得很高。用它做成品，无论后面加多少对比都不通透。

风光成品的常见选择：`Camera Standard`（忠于原厂渲染）、`Adobe Landscape`（自动加暖加饱和）、
`Adobe Color`（通用）。人像用 `Adobe Portrait` 或 `Camera Portrait`。

**切换前先确认这是不是用户想要的基调**，它比任何蒙版都更能改变画面。

## 其他

| 键名 | 说明 |
| --- | --- |
| `ProcessVersion` | 当前 15.4，改它会重置部分参数，不要动 |
| `CropLeft/Top/Right/Bottom` | 0–1 归一化 |
| `CropAngle` | 角度 |
| `LensProfileEnable` | 镜头校正开关 |
| `ConvertToGrayscale` | 黑白开关 |

## 快速体检：先看这五项

拿到一份 dump，先看 `CameraProfile` `Shadows2012` `Blacks2012` `Contrast2012`
`ToneCurvePV2012`。这五项组合起来决定了一张片子「灰不灰」：

- `Camera Flat` + `Shadows +45` + `Blacks −4` + `Contrast +8` + 曲线为空
  = 典型的灰片，暗部被抬平，任何局部压暗都会被抵消
