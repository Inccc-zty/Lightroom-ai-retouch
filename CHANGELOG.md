# Changelog

All notable changes to this project. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/); versions are pre-1.0 and may break.

## [0.2.0] — 2026-11-10

Reframes what this project is actually selling, and records the three failure modes found
while retouching a high-altitude meadow frame (daylily + Lilium pumilum, noon hard light).

### Changed

- **The pitch now leads with "the photo is still yours", not "the result looks better".**
  A generative model hands back *a different image*: detail smoothed away, upscaled and
  re-drawn, plausibly invented content. You cannot tell which part you shot. Parameters are
  opaque, unrollbackable, and impossible to discuss. The technical weaknesses (copying slider
  values, open-loop editing, quantifying aesthetics) are now the *third* layer of the argument,
  not the first. See `references/user-corrections.md` §32.
- **Handover is now a hard delivery requirement** (`SKILL.md`): full global parameter table,
  per-layer list including *what problem each layer solves*, which layers are structural vs.
  taste, and a one-line rollback command. Returning a picture plus "done, take a look" is
  explicitly called out as a failing delivery — it is indistinguishable from a generative
  black box.
- README / README.zh-CN: new "what it is" section stating this is an agent skill; the two
  headline capabilities (ingest a web tutorial; parametric, reversible edits) moved to the top.

### Added

- **Pitfall 41 — preview fast-loop dies once masks are written.** `get_photo_previews` returned
  `error loading thumb` on 6 consecutive attempts after the first mask write, and never
  recovered. The 2–3 s verification loop only holds for the global phase.
- **Pitfall 42 — star-shaped petals fall into the feather ramp.** An ellipse that visually
  "covers" a lily still leaves the petal tips at r ≈ 0.85, where alpha is 0.3–0.5, so a
  `EV −0.26` recovered almost nothing (36% → 34% red-channel clipping). Rule: compute
  `r = √((dx/a)² + (dy/b)²)` for every petal tip and require **r ≤ 0.75**.
- **Pitfall 43 — when a colour appears exactly once in frame, use the HSL band, not a mask.**
  Desaturating a red lily inside an ellipse produced a visible elliptical halo (ring vs.
  distant grass: 9.8 vs 5.1). Switching to `SaturationAdjustmentRed = −14` plus
  `HueAdjustmentRed = −4` removed it entirely (4.96 vs. 5.10, Δ 0.15).
- `check_skill.py`: 41 → **45** invariants, now guarding the new framing and handover rules.

### Known limitations (updated)

- **Red-channel clipping cannot always be recovered.** On backlit scarlet petals the channel is
  near-saturated in the RAW; pulling exposure and desaturating reduces but does not eliminate
  flat patches at 100% zoom.
- **Clipping is a luminance problem, not a saturation problem.** A blown blue sky looks greyer,
  not better, when you desaturate it — the fix is to darken it.
- Single-image retouching is still slow. The real leverage is batch: calibrate a scene once,
  then solve per image. Per-image judgement does not compress.

## [0.1.0] — 2026-11-10

First public release.

### Added

- **Bridge**: file-queue protocol between a Lightroom Classic plugin (Lua) and a Python client.
  Read/write develop settings, mask groups, metadata, export. Cross-platform path resolution
  (`LR_BRIDGE_ROOT` → `~/lr_bridge` → legacy `O:\lr_bridge`).
- **Diagnosis framework** (`references/scene-diagnosis.md`): the six separation tools
  (luminance / hue / saturation / texture / focus / space), six scene archetypes with measured
  case studies, and an explicit *counter-example* for every rule.
- **Nine-step global pass** (`references/adjustment-order.md`): profile → exposure → white
  balance → white/black point → highlights/shadows → contrast & curve → colour → masks → detail,
  with a target metric for each step.
- **Light-sculpting templates** (`references/light-sculpting.md`): lit plane, shadow plane,
  ridge highlight, contact shadow, and force ranges for each.
- **Boolean masks**: `A ∩ B = A − ¬B` implemented as `MaskBlendMode=1` + inverted second mask.
  Verified on subject edges (difference 11.4 on subject vs 0.0 on background).
- **`orig_compare.py`**: one command does backup → reset → export true original → restore →
  field-by-field verification → export final → stacked comparison. Three safety gates built in.
- **`export_shot.py`**: export photos carrying AI masks without getting stuck on the
  "recommended AI update" dialog.
- **`references/case-studies.md`**: three complete diagnosis-to-final walkthroughs
  (snake on moss / orchid in meadow / marmot at its burrow), including the parameter
  tables, measured results, and what went wrong in each.
- **40 documented pitfalls** (`references/pitfalls.md`), each with measured data and cost.
- **31 user corrections** (`references/user-corrections.md`) plus a 12-point pre-delivery
  checklist.
- **Tutorial ingestion** (`references/style-transfer.md`): search strategy, credibility grading,
  and the style-decision vs. that-photo's-solution split.

### Known limitations

- Luminance / colour range masks are **not writable** — the SDK silently drops all `RangeMask*`
  fields (7 key names × 2 mask types tested).
- No spot removal, no brush masks, no local curves.
- AI sky mask alpha measures ~0.12 on blown skies, so sky adjustments apply at ~10%; use a
  geometric linear gradient instead.
- Composition is never changed: no crop, no rotate, no aspect change.

### Notes

- Python 3.9+; only standard library plus Pillow and NumPy.
- Tested on Windows with Lightroom Classic 13.x. macOS support is implemented but less exercised.
