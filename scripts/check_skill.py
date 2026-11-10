#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""检查 user-corrections.md 里登记的每条纠正，是否真的写进了对应文件。

用法:
    python check_skill.py

为什么需要它
------------
用户说过：「你永远都会漏掉一些东西放到 skill 中。」
漏的方式有两种：
  1. 只改了 reference，没登记到 user-corrections（下次忘）
  2. 登记了，但对应 reference 里其实没写（假登记）

本脚本专治第 2 种：逐条去文件里找关键内容，找不到就报错。
"""
import io
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

# (纠正编号与名称, 文件, [必须出现的关键词])
CHECKS = [
    ("01 配置文件按题材选", "references/adjustment-order.md", ["Camera Standard", "Adobe Standard"]),
    ("02 九步顺序", "references/adjustment-order.md", ["第 1 步", "第 8 步"]),
    ("03 全局必须做", "references/adjustment-order.md", ["全局改动要克制"]),
    ("04 蒙版塑形不能省", "references/light-sculpting.md", ["都错", "4–8"]),
    ("05 塑形三件套", "references/light-sculpting.md", ["轮廓光", "核心阴影", "接触阴影"]),
    ("06 背景造光", "references/light-sculpting.md", ["斜射光带", "光热点"]),
    ("07 布尔相交", "references/mask-selection.md", ["A ∩ B", "MaskInverted"]),
    ("07b 布尔踩坑", "references/pitfalls.md", ["MaskBlendMode"]),
    ("08 蒙版类型选择", "references/mask-selection.md", ["整片的用 AI"]),
    ("09 验证覆盖", "SKILL.md", ["验证"]),
    ("10 逻辑冗余", "references/light-sculpting.md", ["等价"]),
    ("11 EV 换算 4.5", "references/develop-settings.md", ["4.5"]),
    ("12 不抄数值", "SKILL.md", ["抄数值"]),
    ("13 资料矛盾裁决", "references/style-transfer.md", ["多个资料互相矛盾"]),
    ("14 全局克制", "references/adjustment-order.md", ["全局改动要克制"]),
    ("15 不越界改色", "references/adjustment-order.md", ["禁止"]),
    ("16 白平衡参考物", "references/adjustment-order.md", ["参考物三不准"]),
    ("16b 白平衡工具", "references/adjustment-order.md", ["auto_wb"]),
    ("17 只一处降温", "references/light-sculpting.md", ["只允许一处降温"]),
    ("18 不要叠压暗", "references/light-sculpting.md", ["背景不要压太黑"]),
    ("19 严格照指令", "SKILL.md", ["有指令严格照指令"]),
    ("20 不许敷衍", "SKILL.md", ["不许越做越敷衍"]),
    ("21 dump 全量状态", "SKILL.md", ["开工第一件事"]),
    ("22 export_shot", "SKILL.md", ["export_shot"]),
    ("23 交稿三问", "SKILL.md", ["交稿前必须自问"]),
    ("24 想办法不能放弃", "references/pitfalls.md", ["值域"]),
    ("25 清单本身存在", "references/user-corrections.md", ["交付前 12 条核对"]),
    ("26 别用拉对比当塑形", "references/user-corrections.md", ["别拿「拉对比」当重塑"]),
    ("26b 主色不降饱和", "references/scene-diagnosis.md", ["不动绿的饱和"]),
    ("27 场景定制方案", "references/scene-diagnosis.md", ["六把刀", "第 0 步"]),
    ("27b 新题材必调研", "SKILL.md", ["先搜 3–5 篇"]),
    ("28 发闷先查自己", "references/user-corrections.md", ["色彩发闷"]),
    ("28b 键名勘误表", "references/develop-settings.md", ["Vibrance2012"]),
    ("29 每图必附原图对比", "SKILL.md", ["收尾必做", "orig_compare"]),
    ("29b 对比图工具存在", "scripts/orig_compare.py", ["归零", "逐键比对"]),
    ("30 归零后诊断", "references/scene-diagnosis.md", ["零状态", "1.02"]),
    ("31 分区双逻辑", "references/scene-diagnosis.md", ["分区处理", "风光", "动物"]),
    ("32 案例库存在", "references/case-studies.md", ["复盘", "案例 A"]),
    ("33 教程搜索策略", "references/style-transfer.md", ["关键词公式", "两篇以上独立来源"]),
    ("34 贴纸感四因", "references/pitfalls.md", ["贴纸", "投影"]),
    ("35 光斑破形", "references/pitfalls.md", ["椭圆", "feather"]),
    ("36 照片还是你的", "SKILL.md", ["不是你的照片", "不碰像素"]),
    ("37 交接单", "SKILL.md", ["交接单", "骨架层"]),
    ("38 对外表述顺序", "README.zh-CN.md", ["生成式", "一个字节都没动"]),
    ("39 价值判断登记", "references/user-corrections.md", ["照片还是你的"]),
    ("40 蒙版写入工具", "scripts/mask_tool.py", ["mask_fit", "回读"]),
    ("41 层参数修改工具", "scripts/set_layer.py", ["回读校验", "按层名"]),
    ("42 椭圆拟合工具", "scripts/mask_fit.py", ["feather", "偏弱"]),
    ("43 椭圆规则已入正文", "SKILL.md", ["mask_fit", "r ≤ 0.71"]),
]


def main():
    missing = []
    for name, rel, kws in CHECKS:
        path = os.path.join(ROOT, rel)
        if not os.path.isfile(path):
            missing.append((name, rel, "文件不存在"))
            continue
        text = io.open(path, encoding="utf-8").read()
        for kw in kws:
            if kw not in text:
                missing.append((name, rel, "缺: " + kw))

    print("核对 %d 项" % len(CHECKS))
    if missing:
        print("\n未落实：")
        for n, p, r in missing:
            print("  %-22s %-36s %s" % (n, p, r))
        print("\n%d 项缺失。清单登记了但正文没写 = 假登记。" % len(missing))
        return 1
    print("全部落实。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
