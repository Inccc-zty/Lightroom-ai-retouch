# Lightroom AI Retouch

English | **[中文](README.zh-CN.md)**

> Skill directory name: `lr-ai-retouch` · Repo: `Lightroom-ai-retouch`

Let AI actually operate your Lightroom Classic — not by simulating mouse drags on sliders,
but by reading and writing develop settings and local masks directly, verifying every change
with a real export. Measurement is a guardrail; the aesthetic call stays with you.

```
┌──────────────┐   write <id>.cmd   ┌────────────────────┐
│ Python client│ ─────────────────→ │                    │
│ lr_bridge.py │                    │  Lightroom         │
│              │ ←───────────────── │  AIBridge.lrplugin │
└──────────────┘   read <id>.res    └────────────────────┘
        │                                     │
        ↓                                     ↓
   export JPEG                        read/write develop
   measure, judge                     settings + masks
```

The protocol is plain text, `key|type|value`, one field per line. No ports, no daemon, no
dependencies — just files. Which also means it behaves identically on Windows and macOS.

---

## What this solves

Most "AI photo editing" today sits at one of two levels: applying presets (every photo looks
the same), or driving the UI with Computer Use (can't hit a slider precisely, can't build a
dozen masks).

This project takes a different route: **run a plugin inside Lightroom and talk to it over a
file queue.** The plugin executes in its own Lua interpreter with the same permissions as you
clicking in the UI, so it can:

- write parameters to six decimal places
- build a dozen local masks in one shot, each geometry precise to a thousandth
- read back all 1000+ develop fields for verification
- ignore dialogs, focus, screen resolution and display scaling

The trade-off is speed — every step needs an export to verify. That slowness is the point:
**open-loop editing only drifts further off.**

## Why trust the results

This is not a prompt collection. It grew out of 8000+ real frames and dozens of failed edits.
Every rule carries measured numbers, and every rule documents **where it breaks**:

| Rule | Measured | Counter-example (when NOT to use it) |
| --- | --- | --- |
| Same-hue subject/background: desaturate the background | bg saturation 0.816 → 0.623, subject−bg colour gap 30.9 → 38.5 | When the background IS the main colour (green meadow): it flattened the frame, mid-tone dropped to 73, the user called it "depressing" |
| If luminance separation is already strong, add nothing | At ratio 1.34, more exposure just looks like flash | At ratio 1.02 (marmot vs. grass), you must switch to hue + texture |
| Lower a channel's HSL *luminance* to push it back | ✗ Wrong. Green luminance −7 pushed saturation 0.36 → 0.42 | Saturation is `(max−min)/max`; shrinking the denominator raises the ratio |
| Ring the subject with a dark halo to make it pop | ✗ Wrong. A ring on all sides = cut-out sticker | Put a **cast shadow only on the backlit side** — the only evidence an object sits on the ground |

**No rule here is universal.** That's why rule zero is: *diagnose first; the plan grows out of
this photo, it is not carried over from the last one.*

---

## Install

**Requirements**: Lightroom Classic (2018+, developed against 13.x), Python 3.9+, Windows or macOS.

```bash
# 1. Clone into your skills directory
git clone https://github.com/Inccc-zty/Lightroom-ai-retouch.git \
        ~/.workbuddy/skills/lr-ai-retouch

# 2. Install the Lightroom plugin
cp -r assets/plugin/AIBridge.lrplugin \
      ~/Library/Application\ Support/Adobe/Lightroom/Modules/     # macOS
# Windows: %APPDATA%\Adobe\Lightroom\Modules\
# Then in Lightroom: File → Plug-in Manager → Add → select that folder

# 3. Verify
cd ~/.workbuddy/skills/lr-ai-retouch
python scripts/lr_bridge.py ping
```

`ping` returning `{"running": true, "ok": true}` means you're connected.
If not, see [`references/bridge-setup.md`](references/bridge-setup.md) — six distinct failure
modes (a stalled heartbeat has several causes; don't just restart Lightroom).

### Queue directory

The Python side and the plugin talk through a shared directory. Resolution order is identical
on both ends:

1. `LR_BRIDGE_ROOT` environment variable
2. `~/lr_bridge` (recommended)
3. `O:\lr_bridge` (legacy installs; only if that directory already exists)

**Both ends must resolve to the same directory**, otherwise commands land in a queue nobody
reads. On a new machine, just set the environment variable.

---

## Sixty seconds to first run

```bash
# What's selected right now
python scripts/lr_bridge.py selection

# Dump every parameter on it (1000+ fields)
python scripts/lr_bridge.py dump --path "/path/to/photo.NEF" > before.json

# Change one parameter and wait for it to land on disk
python scripts/lr_bridge.py develop-set --path "/path/to/photo.NEF" --set Exposure2012=0.35

# Add masks (dry run first, then --apply)
python scripts/mask_append.py --path "/path/to/photo.NEF" --spec layers.json
python scripts/mask_append.py --path "/path/to/photo.NEF" --spec layers.json --apply

# Export and run the quality checks
python scripts/export_shot.py --path "/path/to/photo.NEF" --dest ./out --long-edge 2400
python scripts/qc.py out/photo.jpg
```

**Every write must carry an explicit `--path`.** Without it, the write goes to whatever is
selected — one stray click and you've edited the wrong photo. That's the most expensive
accident in this project's history.

---

## Key concepts

### A mask is data, not something you paint

A mask layer is just a set of numbers:

```json
{"name": "lit top of the rock", "kind": "radial",
 "lt": [0.27, 0.66], "rb": [0.60, 0.83],
 "ev": 0.20, "clarity": 12, "texture": 8}
```

`ev` is a real EV; the tool divides by 4.5 internally to produce `LocalExposure2012`.
Coordinates are 0–1 normalised, origin top-left.

### Camera profiles are writable

`CameraProfile` was long assumed read-only. It isn't — measured writable, plain names only:

```
Camera Flat / Camera Standard / Camera Neutral / Adobe Landscape / Adobe Standard
```

`Camera Flat` is the flattest starting point (designed for maximum editing latitude) and is
wrong for a finished image no matter what you stack on top. Changing it is often more effective
than adding ten masks.

### The workflow

```
RAW ──diagnose──> 9-step global ──> regional masks ──> export & measure ──> final + comparison
        ↑                    ↓
   six tools            diff map / detail ratio / thumbnail test
```

**Step 0 — Diagnose (non-negotiable).** Ask first: *what already separates the subject from
the background?* There are exactly six physical tools:

| Tool | Test | How to amplify |
| --- | --- | --- |
| Luminance | Brightness gap ≥ 15% | Lift subject / darken background / core shadow |
| Hue | ≥ 45° apart on the wheel | Push both sides in opposite directions, don't rotate hue itself |
| Saturation | One side clearly denser | Desaturate background (only if it isn't the main colour) |
| Texture | Subject has detail, background is soft | clarity to subject, negative to background |
| Focus | Depth of field already separates | Post can only approximate with clarity |
| Space | Negative space around the outline | Composition only — **this project never crops** |

**Diagnostics must come from a fully reset export.** A version carrying old adjustments gives
the opposite answer: measured on the same photo, the subject/background luminance ratio read
1.34 with old edits ("already fine") and 1.02 after resetting ("almost no difference") —
33 points apart, and a completely different plan.

**Steps 1–9 — the global pass.** Profile → Exposure → White balance → White/black point →
Highlights/shadows → Contrast & curve → Colour → Masks → Detail. One parameter family per step,
verify before moving on, never merge steps — each step changes the basis for judging the next.

**Step 8 — regional masks.** The only way to turn "correctly exposed" into "has volume". Rule of
thumb: *a landscape with a clear light direction needs at least 4–8 light-shaping layers after
the global pass*, otherwise it isn't finished. Anything applied to the subject goes through a
**boolean mask** (AI subject ∩ geometry) — a pure geometric box always takes the background
with it.

**Wrap-up — original comparison (mandatory).**

```bash
python scripts/orig_compare.py --path "/path/to/photo.NEF" --out ./output --apply
```

One command: back up → reset to zero → export the true original → restore exactly → verify field
by field (0 differences or it fails) → export the final → build a stacked comparison.
**"Original" means a render with every parameter zeroed** — never a version the user already
edited.

---

## Using online tutorials as reference

A core capability. When someone drops a link and says "edit it like this", the goal is not to
copy the numbers, but to copy the **decisions**.

| Type | Example | Transferable? |
| --- | --- | --- |
| **Style decision** | "Crush the highlights so the clouds have weight" | Yes — that's a taste |
| **Style decision** | "Pull purple/magenta all the way down to clean noise" | Yes — that's a technique |
| **That photo's solution** | "Exposure −0.20" | No — depends on the original exposure |
| **That photo's solution** | "Dehaze +17" | Half — depends on how much haze |

**Transfer the left column; recompute the right column for your own photo.**

When you search yourself, use the formula `<genre> + <specific difficulty> + post processing`.
Never search "how to edit photos". Worked vs. useless queries, how to grade source credibility,
and what to do when two sources contradict each other are all in
[`references/style-transfer.md`](references/style-transfer.md).

Only adopt conclusions that **two or more independent sources agree on**. A single source is a
reference, not a rule.

---

## Boundaries (the honest list)

| Cannot do | Why | Workaround |
| --- | --- | --- |
| **Luminance / colour range masks** | The SDK silently drops every `RangeMask*` field (7 key names × 2 mask types tested) | HSL per-channel is itself a colour range selector |
| **Spot removal / content-aware fill** | No API | A few clicks in the Lightroom UI |
| **Brush masks / local curves** | No API | Stack several geometric masks |
| **Changing composition** | Project rule: no crop, no rotate, no aspect change | Composition issues are reported, you decide |
| **Large sky darkening via AI sky mask** | On blown skies the alpha measures ~0.12, so parameters apply at ~10% | Use a plain geometric linear gradient |

One more trap you must know: **Lightroom does not error on unknown keys.** `SharpenMask` doesn't
exist (the real key is `SharpenEdgeMasking`); the write returns `applied: 762` and you only find
out by reading it back. So **always dump and verify the specific field — never trust `ok`.**

---

## Repository layout

```
lr-ai-retouch/
├── SKILL.md                    # five hard rules + nine steps + pre-delivery self-check
├── references/
│   ├── scene-diagnosis.md      # the six tools, six scene types, with counter-examples
│   ├── adjustment-order.md     # the nine steps, target metric for each
│   ├── light-sculpting.md      # lit plane, shadow plane, ridge, contact shadow
│   ├── mask-selection.md       # choosing mask types, boolean recipes
│   ├── mask-structure.md       # mask field structure (for writing trees)
│   ├── develop-settings.md     # key names + the 4.5× unit trap
│   ├── style-transfer.md       # extracting style from tutorials / reference images
│   ├── closed-loop.md          # export → measure → judge
│   ├── aesthetics.md           # the judgement measurement can't make
│   ├── pitfalls.md             # 40 documented failures, each with measured data
│   ├── user-corrections.md     # 31 corrections + a 12-point pre-delivery checklist
│   └── bridge-setup.md         # plugin install and troubleshooting
├── scripts/
│   ├── lr_bridge.py            # bridge client (settings, masks, export)
│   ├── lr_masks.py             # mask builders (including boolean layers)
│   ├── mask_append.py          # append masks with backup + read-back verification
│   ├── export_shot.py          # export with AI masks (handles the dialog)
│   ├── orig_compare.py         # original ↔ final comparison (run before delivery)
│   ├── auto_wb.py              # white balance diagnostics
│   ├── qc.py / depth_qc.py     # quality checks
│   └── check_skill.py          # self-check: documentation invariants
└── assets/plugin/AIBridge.lrplugin/   # the Lightroom plugin itself (Lua)
```

---

## FAQ

**Why not use Adobe's official API?**
There isn't one. The Camera Raw SDK does not expose develop settings for writing.

**Why export after every single step?**
Because each step changes how you judge the next. Change twenty parameters at once and you
can't tell which one did it — or whether any went too far. That's open loop vs. closed loop.

**Can it batch-edit a whole shoot?**
Yes, but only photos from the same scene under the same light. Different light needs a fresh
diagnosis — every failure in this project came from carrying one photo's solution to another.

**Why so many counter-examples and admissions of error in the docs?**
Because a rule's value isn't in the cases where it holds, but in knowing where it doesn't.
Every counter-example is a real failure with measured numbers behind it.

---

## Contributing

Issues and PRs welcome, especially measured case studies for new genres (birds, insects,
underwater, night), "this rule doesn't hold here" reports, and new findings about SDK
boundaries. See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

[MIT](LICENSE). Use it freely; don't blame me when it goes wrong.

## Acknowledgements

Every rule here came from real shooting and real mistakes. Special thanks to the moments that
went "this version is worse than what I edited myself" — without them, this would just be a
pile of pretty numbers.
