# Contributing · 参与贡献

**中文** | [English](#english)

---

## 中文

这个项目最需要的东西**不是新功能，是新的反例**。

它的每一条规则都来自真实拍摄和真实翻车。所以最有价值的贡献是这五类：

### 1. 新题材的实测案例

鸟、昆虫、水下、夜景、星空、城市建筑、人像逆光……只要 `references/scene-diagnosis.md`
里没有对应条目，就是缺口。

提交时请带上：

- **原片**（或者一张能说明光线的局部）
- **诊断结论**：这张靠哪把刀分离？（明度/色相/饱和/质感/焦点/空间）
- **动作 + 实测数字**：改了什么，改之前和之后的关键指标
- **结论**：成立还是不成立，为什么

### 2. "这条规则在这里不成立"

比"这条规则有用"更有价值。格式：

```
规则：<引用原文>
反例：<什么题材/什么光线>
实测：<数字对比>
结论：<应该怎么改这条规则>
```

### 3. SDK 边界的新发现

某个参数其实能写、某个不能、某个写了不报错但没生效。
务必附上**回读验证**（`dump` 出来的实际值），不要只贴写入返回值。

### 4. 抓错别字、死链、跑不通的代码

直接开 PR，不用先开 issue。

### 5. 翻译

英文版和中文版必须同步。改了中文版请在 PR 里注明"需要同步英文"。

---

### 提交前自查

- [ ] 数字是我自己实测的，不是从别处抄的？
- [ ] 我写了这条规则**什么时候不成立**？
- [ ] 涉及写操作的部分，我 dump 回读确认过吗？
- [ ] 文档里的路径是示例路径（`/path/to/photo.NEF`），不是我的本机路径？
- [ ] 没有提交原片、个人照片、Lightroom 目录数据库？

### 文档风格

- 每条规则后面要有**实测数字**，或者是"实测：不成立，因为……"
- **反例跟正例一样重要**，不要只写成立的情况
- 单位要写清：`LocalExposure2012` 是 EV÷4.5，别直接当 EV 报
- 不要写"效果很好"这种话，写"亮度比 1.02 → 1.07"

---

## English

What this project needs most is **not new features — it's new counter-examples.**

Every rule here came from real shooting and real mistakes. So the most valuable contributions
are these five kinds:

### 1. Measured case studies for new genres

Birds, insects, underwater, night, astro, architecture, backlit portraits — if
`references/scene-diagnosis.md` has no entry for it, that's a gap.

Please include:

- **The RAW** (or a crop that shows the light)
- **Your diagnosis**: which of the six tools actually separates the subject here?
  (luminance / hue / saturation / texture / focus / space)
- **Action + measurements**: what you changed, and the key metrics before/after
- **Verdict**: does the rule hold, and why

### 2. "This rule doesn't hold here"

More valuable than "this rule works". Format:

```
Rule: <quote the original>
Counter-example: <genre / lighting condition>
Measured: <numbers>
Conclusion: <how the rule should change>
```

### 3. New SDK boundary findings

A parameter that turns out to be writable, one that isn't, one that writes but silently does
nothing. **Always include read-back verification** (the actual value from `dump`) — never just
the write return value.

### 4. Typos, dead links, code that doesn't run

Open a PR directly; no issue needed.

### 5. Translation

English and Chinese must stay in sync. If you change the Chinese docs, note
"needs English sync" in the PR.

---

### Pre-submit checklist

- [ ] Are the numbers my own measurements, not copied from somewhere?
- [ ] Did I document **when this rule does not hold**?
- [ ] For anything involving writes, did I verify by dumping the field back?
- [ ] Are paths in the docs examples (`/path/to/photo.NEF`) rather than my local paths?
- [ ] Did I avoid committing RAW files, personal photos, or a Lightroom catalog?

### Documentation style

- Every rule needs **measured numbers**, or an explicit "measured: does not hold, because…"
- **Counter-examples matter as much as examples** — don't only document the cases that work
- Be precise about units: `LocalExposure2012` is EV ÷ 4.5; don't report it as EV
- Never write "looks much better" — write "luminance ratio 1.02 → 1.07"

---

## 开发环境 · Dev setup

```bash
git clone https://github.com/<your-name>/lr-ai-retouch.git
cd lr-ai-retouch
python scripts/check_skill.py    # 文档完整性自检 / documentation self-check
python scripts/lr_bridge.py ping # 需要 Lightroom 在运行 / requires Lightroom running
```

`check_skill.py` 会核对清单里的每一条是否真的写进了正文——它防止"说了但没写"。

`check_skill.py` verifies that every item in the checklist is actually present in the docs.
It exists to prevent "claimed but never written".
