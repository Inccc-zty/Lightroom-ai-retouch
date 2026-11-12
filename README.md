# Lightroom AI Retouch

English | **[中文](README.zh-CN.md)**

> Skill directory name: `lr-ai-retouch` · Repo: `Lightroom-ai-retouch`

Let AI actually operate your Lightroom Classic — not by simulating mouse drags on sliders,
but by reading and writing develop settings and local masks directly, verifying every change
with a real export. Measurement is a guardrail; the aesthetic call stays with you.

**Topics**: photography · photo editing · photo post-processing · retouching ·
automated retouching · Lightroom · Lightroom Classic · image processing ·
image editing · batch editing · local masks · AI agent skill

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

## What it is

**This is an AI agent skill** — drop the folder into your agent's skills directory
(`~/.workbuddy/skills/lr-ai-retouch`), and the agent can drive Lightroom Classic directly.
If you're not using a skill-capable agent, the `references/` folder still reads fine on its own
as a retouching methodology.

Three things in one repository:

| | What | Where |
| --- | --- | --- |
| **1. An agent skill** | The entry point: rules, workflow, and the scripts the agent calls | `SKILL.md` + `scripts/` |
| **2. A methodology** | Diagnosis framework, nine steps, mask recipes, 40 pitfalls — readable without any code | `references/` |
| **3. A Lightroom plugin** | The Lua bridge that makes write access possible | `assets/plugin/` |

## Two capabilities that matter most

### 1. Feed it a web tutorial — it retouches in that style

Point your agent at an article, a video transcript, a preset write-up, or just say
*"edit it the way people online edit this kind of photo"*. The skill then:

1. **Searches properly** — `<genre> + <specific difficulty> + post processing`,
   never "how to edit photos"
2. **Grades the source** — only conclusions that two independent sources agree on get adopted;
   a single source stays a reference
3. **Splits every number in two** — *style decision* (transferable, e.g. "crush highlights so
   clouds have weight") vs *that photo's solution* (must be recomputed, e.g. "exposure −0.20")
4. **Recomputes against your histogram** before touching a single slider

So "make it look like that tutorial" becomes a concrete plan instead of a preset dump.
Full procedure in [`references/style-transfer.md`](references/style-transfer.md).

### 2. Diagnose first — never carry the last photo's answer over

Every photo gets the same first question: *what already separates the subject from the
background?* There are exactly six physical tools, and the skill refuses to fake one that
doesn't exist.

This is not theory. The same action — desaturating the background — rescued one photo
(snake on moss) and destroyed another (orchid in a meadow). See
[`references/case-studies.md`](references/case-studies.md) for three complete
diagnosis-to-final walkthroughs, including what went wrong.

## What this solves

### The biggest problem isn't the parameters — it's that you don't get your photo back

Hand a photo to most AI editing tools and you get a *different* photo back. Behind the curtain:
detail quietly smoothed away, upscaling applied, details **invented** where the model decided
something belonged there. You can't tell which pixels are yours and which it imagined, and to
change one thing you have to start over.

A photograph's first value is *"I took this."* Once that's gone, everything layered on top is
decoration.

**This project never touches pixels — only parameters.** What comes back is your own negative,
plus a set of Lightroom develop settings and masks.

| | Generative / end-to-end AI retouching | This project |
| --- | --- | --- |
| What you get back | a new image | your image, with new settings |
| Pixels | may be smoothed, upscaled or invented | untouched — not one byte |
| Keep editing afterwards | start over | yes, in Lightroom, by hand |
| Roll back | no | one command, back to zero |
| Ask "why this value?" | no | every layer has a name, a reason, a measurement |
| Discuss with the AI | "make it nicer" | "layer 9 is too heavy — halve it" |

Underneath that, the three technical dead ends of conventional AI retouching:

1. **Copying numbers.** A tutorial's `highlights −98, shadows +71` is that photographer's
   answer on that photograph. On yours it's a disaster.
2. **Open loop.** You change something and have no idea whether it went too far.
3. **Aesthetics by arithmetic.** Judging "is this too red" with an RGB mean, and calling a dark
   green forest crushed black.

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
python scripts/mask_tool.py --path "/path/to/photo.NEF" --spec layers.json
python scripts/mask_tool.py --path "/path/to/photo.NEF" --spec layers.json --apply

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

### Handover — what you get besides the image

An image alone is not a deliverable here. Along with it comes:

- the **full global parameter table**
- **every mask layer**: name, coverage, values, and *what it is for*
- which layers are **structural** and which are **taste** (halve those freely, no need to ask)
- the **backup path** and a one-line rollback command

That is what makes the conversation possible: *"layer 9 is too heavy"* — or open that layer in
Lightroom and change it yourself, without redoing anything else.

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
│   ├── case-studies.md        # three complete diagnosis-to-final walkthroughs
│   ├── pitfalls.md             # 43 documented failures, each with measured data
│   ├── user-corrections.md     # 31 corrections + a 12-point pre-delivery checklist
│   └── bridge-setup.md         # plugin install and troubleshooting
├── scripts/
│   ├── lr_bridge.py            # bridge client (settings, masks, export)
│   ├── lr_masks.py             # mask builders (including boolean layers)
│   ├── mask_append.py          # append masks with backup + read-back verification
│   ├── mask_tool.py            # main: batch-write layers from a spec, verify and read back
│   ├── set_layer.py            # main: patch existing layers by name, never rewrite the tree
│   ├── mask_fit.py             # solve safe radial semi-axes, or audit existing geometry
│   ├── export_shot.py          # export with AI masks (handles the dialog)
│   ├── orig_compare.py         # original ↔ final comparison (run before delivery)
│   ├── auto_wb.py              # white balance diagnostics
│   ├── qc.py / depth_qc.py     # quality checks
│   └── check_skill.py          # self-check: 49 documentation invariants
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
