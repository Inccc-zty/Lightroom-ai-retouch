# Changelog

All notable changes to this project. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/); versions are pre-1.0 and may break.

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
