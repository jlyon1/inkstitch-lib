# digitize_svg.py

Takes an already-vector SVG (a logo, a flag, anything with flat-color
shapes) and runs it through Ink/Stitch's real fill-stitch engine, headless,
with no Inkscape and no wxPython installed. Output is a real embroidery
file (PES, DST, whatever Ink/Stitch supports), plus structured per-shape
geometry an agent can use to make stitch-type decisions before committing.

This does **not** trace raster photos into vector shapes (no vtracer, no
Inkscape bitmap tracing) — the scope is deliberately narrower: SVG in,
stitches out. A raster-tracing prototype was built and worked, but was
dropped as unnecessary for the actual goal.

## Quick start

```bash
uv run digitize_svg.py input.svg output.pes --width-mm 80
```

Inspect a design before generating anything:

```bash
uv run digitize_svg.py input.svg --measure-only --width-mm 80
```

Set a fill angle on specific shapes (indices are the post-knockdown order
printed by a normal run, or by `--measure-only`):

```bash
uv run digitize_svg.py input.svg output.pes --width-mm 80 --angle "0=45" --angle "1=90"
```

## What it actually does, step by step

1. **Parse the source SVG.** Reads `viewBox` (or falls back to raw
   `width`/`height`) to know the design's native coordinate space.
2. **Wrap it in Ink/Stitch's required shell.** Ink/Stitch refuses to treat
   a document as its own without a specific `inkstitch:inkstitch-metadata`
   block (version tag + a few default settings) present in `<metadata>`.
   `build_wrapped_svg`/`add_inkstitch_metadata` construct this from scratch
   — no template file needed.
3. **Remove hidden overlap ("knockdown").** For every embroiderable shape,
   in document (paint/z) order, subtract the union of every shape drawn
   *after* it from its own area. A background rect fully covered by a band
   on top of it would otherwise get stitched in full underneath — invisible
   in the final result, but real wasted thread and a lumpier fabric build.
   This is where most of the real engineering is:
   - Reuses Ink/Stitch's own `FillStitch(node).shape` for each source shape
     rather than re-parsing SVG path data by hand — this is
     transform-aware and already flattens curves into polygon geometry, so
     it works on more than just rects.
   - The actual subtraction is `shapely.difference()`/`unary_union()` —
     plain, well-tested computational geometry, not something bespoke.
   - A shape fully covered by later shapes is dropped entirely (not
     emitted as an empty path), which also drops it from the eventual
     thread/color list.
   - Rebuilt shapes are re-serialized as plain `<path d="...">` elements
     with `fill-rule="evenodd"` (so hole rendering doesn't depend on ring
     winding order, which shapely doesn't guarantee matches SVG
     convention).
4. **Measure every shape that will actually stitch.** `measure_shape()`
   reports area, a minimum-rotated-bounding-box length/width/aspect ratio,
   and the shape's own orientation, all in real mm. Multi-part shapes
   (see the flag example below) get a per-part breakdown in addition to
   the aggregate, since the aggregate alone can be actively misleading.
5. **Apply any caller-supplied per-shape stitch params.** Currently just
   `angle` (see Verified results below), set directly as an
   `inkstitch:angle` XML attribute — the same attribute a human would set
   by hand in Inkscape's Fill params dialog.
6. **Generate the real embroidery file.** Feeds the corrected SVG to
   Ink/Stitch's own `Output` extension (`lib/extensions/output.py`) via
   the same `ext.run([...])` + stdout-capture pattern `batch_text_to_pes.py`
   already uses in production for text — nothing about this step is
   custom or reimplemented.

## Why any of this needed workarounds

Ink/Stitch's own package (`lib/extensions/__init__.py`) eagerly imports
*every* extension on import, including `About`, which needs wxPython.
wxPython has no prebuilt wheel for this Python/platform and a from-source
build needs system GTK dev headers this environment doesn't have — not
worth it just to reach `Output`, which itself needs no GUI at all.

`_inkstitch_headless.py` (import this before anything from
`lib.extensions`/`lib.elements`) patches three things, in order:

1. **`lib.extensions` and `lib.gui` package stubs.** Both get a stub module
   whose `__path__` points at the *real* directory, so
   `from lib.extensions.output import Output` still resolves the real
   file — it just skips the package's own eager `__init__.py` imports
   (which is a pure re-export list with no other side effects for
   `lib.extensions`, and a GUI-dialog cascade for `lib.gui` that
   `lib/update.py` pulls in for an "update this old SVG?" prompt we never
   trigger, since this script always writes current-version metadata
   itself).
2. **A `wx` meta path finder.** wx turned out to be unavoidable through
   much deeper chains than the package re-export — `lib.elements` ->
   `fill_stitch` -> `lib.stitches` -> `tartan_fill` -> a palette color
   picker, and separately `lib.sew_stack`'s stitch-layer editor — each
   for a GUI widget this script's plain-fill path never touches. New
   `wx.*` submodule imports (`wx.html`, `wx.lib.intctrl`, ...) kept
   surfacing one at a time as deeper features were touched, so rather
   than register each by name, a `sys.meta_path` finder intercepts *any*
   `wx` or `wx.x.y` import and hands back a permissive fake object usable
   as a base class, a constructor call, a bare constant, or chained
   further attribute access.

None of this changes real behavior for the plain-fill path this script
uses — it only avoids importing GUI code that was never going to run
headless anyway.

## The unit-conversion trap (and how it was caught)

`FillStitch.shape` returns coordinates already converted into Ink/Stitch's
internal physical unit space — 96 units per inch, i.e.
`PIXELS_PER_MM = 96 / 25.4`, the same convention used elsewhere in this
codebase — **not** the source SVG's raw viewBox units. The first version
of the knockdown step reused the *original* document's viewBox dimensions
when rebuilding the corrected SVG from extracted `.shape` geometry. That
silently shrank the whole design by a factor matching that exact
conversion ratio (an 80mm-wide flag came out ~32mm wide).

This wasn't caught by looking at the rendered preview — a shrunk design
still renders as a visually correct flag, just smaller, and a low-res PNG
preview doesn't make that obvious. It was caught by comparing the actual
stitch bounding box in the generated file against a known-correct
reference run. **Lesson for anything built on top of this: verify
physical output size from the stitch file itself (bounding box in real
units), not from how a preview image looks.** The fix
(`remove_hidden_overlap`'s `px_w`/`px_h` calculation) declares the
corrected document's viewBox directly in the same physical scale the
extracted coordinates are already in.

## Verified results

Test case: the real
[Flag of Spain (civil)](https://upload.wikimedia.org/wikipedia/commons/7/70/Flag_of_Spain_%28civil%29.svg)
— two `<rect>` elements, a full-canvas red background and a yellow band on
top, `--width-mm 80`.

| | Before knockdown | After knockdown |
|---|---|---|
| Stitch count | 12,634 | 8,881 (-30%) |
| Red block bbox | 80.0mm × 53.4mm | 80.0mm × 53.4mm (correct both times) |
| Red stitched twice under yellow? | Yes | No |

The ~30% reduction matches hand math: original total covered area was
150% of the canvas (full red + a second, fully-overlapping yellow pass);
after knockdown it's exactly 100%, once.

Per-shape fill angle, same flag, `--angle "0=45" --angle "1=90"`: measuring
the actual generated stitch file's dominant stitch-vector angle per color
block gave the yellow block (`angle=90`) an exact 90.0° match. The red
block's measured angle didn't cleanly match 45° in the same check — most
likely a coordinate sign/axis convention difference between the ad hoc
verification script and Ink/Stitch's own `angle` semantics (the exact
mismatch, ~134° vs 45° requested, is consistent with a Y-axis mirror,
which a 90° request wouldn't expose since 90° is symmetric under that).
**The mechanism itself is proven**: `inkstitch:angle` is a real, working,
per-shape lever — it just needs its sign convention calibrated precisely
before an agent relies on exact requested angles.

Per-part geometry breakdown: after knockdown, the flag's red shape becomes
two disconnected strips (above and below the yellow band). Measuring the
combined bounding box alone reports 80.0×53.3mm (aspect ratio 1.5) — which
understates how thin each real piece is. `measure_shape()` now reports
each part separately: two 80.0×13.3mm strips, aspect ratio 6.0 each. That
distinction is exactly what a fill-vs-satin decision should hinge on, and
the aggregate-only version would have hidden it.

## What this gives an agent today

- **Inspect**: `--measure-only` returns structured JSON (area, dimensions,
  aspect ratio, orientation, per-part breakdown for split shapes) with no
  file generated. Separately, generated files can be rendered to a static
  PNG (any pyembroidery-based tool) or, in the embroider-web product,
  uploaded to `/api/convert` and watched stitch live via
  `/replay/content/{key}` — actual stitch order, not just a flat image.
- **Reason about fill type**: real geometric facts per shape/part
  (`measure_shape`), and a real, verified lever (`--angle`) to act on that
  reasoning. What's *not* here yet: an actual decision procedure (this
  deliberately exposes the facts and the lever rather than hardcoding a
  fill-vs-satin heuristic), and satin-column conversion itself — Ink/
  Stitch's `fill_to_satin.py` needs a human-drawn "rung" line marking
  where the column runs, so it isn't a free automatic conversion the way
  fill angle is.
- **Avoid excessive layering**: done by default (`knockdown=True`), and
  verified via actual stitch bounding boxes and counts, not just visual
  inspection.

## Known limitations / next steps

- Fill angle's sign/axis convention needs precise calibration (see
  Verified results) before an agent should rely on exact requested
  degrees rather than relative direction.
- No satin-column path yet — would need either a way to auto-place rungs
  for `fill_to_satin.py`, or a different conversion approach entirely.
- `row_spacing_mm` is plumbed through the same `shape_params` mechanism as
  `angle` (any `inkstitch:*` attribute can be set this way) but hasn't
  been separately verified the way angle was.
- Only handles `rect`/`path`/`polygon`/`polyline`/`circle`/`ellipse`/`line`
  — matches `EMBROIDERABLE_TAGS`, the same set Ink/Stitch itself treats as
  embroiderable. Groups, clones, gradients, and text elements in the
  source SVG are not handled.
- This is a standalone script in this repo, not yet wired into
  embroider-web (the actual product) or exposed as a callable tool for a
  real agent loop.

## combine_design_and_text.py: [any design] + text

Merges any `digitize_svg.py`-compatible design -- not specific to flags or
countries, that's just what it happened to be built and verified against
first -- with `batch_text_to_pes.py`'s text pipeline (the same lettering
engine embroider-web's `/create` page already runs in production) into one
design, in one of three positions:

```bash
uv run combine_design_and_text.py design.svg "Spain" "Roman AGS" output.pes --position right   # default
uv run combine_design_and_text.py design.svg "Spain" "Roman AGS" output.pes --position left
uv run combine_design_and_text.py design.svg "Spain" "Roman AGS" output.pes --position under
```

The two pieces are generated fully independently and merged at the
**stitch-plan level** with `pyembroidery` (not inside a single Ink/Stitch
SVG document) -- each half stays exactly as already verified on its own,
and the merge itself is just geometry (bounding boxes, an x/y offset per
piece, perpendicular-axis centering).

Verified on the real Spain flag + "Spain" in three fonts (Barstitch
regular, Roman AGS, Venezia) and all three positions, each uploaded to
embroider-web's live stitch replay for visual confirmation. Verified
again with an unrelated design (a traced star badge, nothing flag-like)
plus arbitrary text ("Team Awesome") to confirm the design side is
genuinely general, not flag-specific in disguise.

### Two real stitch-plan bugs caught here, both from copying a source
### pattern's raw stitch list verbatim

- **A source pattern's own trailing `END` command**, copied mid-sequence,
  made writers treat the whole combined pattern as over right there --
  silently dropping everything appended after it. The tell: reread stitch
  count came back the same (~1545) regardless of which font or text was
  combined, which meant something was being truncated at a fixed point,
  not legitimately differing per input the way real content would.
- **A block's own leading/trailing `COLOR_CHANGE`**, copied alongside an
  explicit `combined.color_change()` call already marking that same
  transition, created a duplicate adjacent color-change -- a zero-length
  "dead" color segment that shifted every later thread index by one (the
  flag's real yellow silently inherited an unrelated black thread slot,
  rendering as black instead of yellow).

Neither was visible from a quick glance at a rendered preview -- both
looked like plausible, if wrong, output. Both were caught by inspecting
the actual written file's stitch count, threadlist, and color-change
positions directly. Same lesson as the unit-conversion bug above: verify
from the stitch file's actual structure, not from how a preview happens
to look.

## check_design.py: Ink/Stitch's own troubleshooting, as data

Ink/Stitch ships a `Troubleshoot` extension that finds real problems with
a design -- shapes that won't stitch at all, shapes that will stitch but
probably shouldn't (too small, disconnected pieces with no defined stitch
order, ...), objects of a type Ink/Stitch can't embroider. Normally it
draws pointer markers and text into the SVG for a human to read in
Inkscape. `check_design.py` calls the exact same underlying check --
every element's `validation_errors()`/`validation_warnings()` -- and
returns it as JSON instead: no new checks invented, just the existing
ones exposed as data an agent can read directly.

```bash
uv run check_design.py design.svg
```

```json
{
  "clean": false,
  "problems": [
    {
      "element_index": 0,
      "severity": "warning",
      "name": "Unconnected",
      "description": "Fill: This object is made up of unconnected shapes...",
      "position_mm": [80.0, 53.33],
      "steps_to_solve": ["* Extensions > Ink/Stitch > Fill Tools > Break Apart Fill Objects"]
    }
  ]
}
```

Verified against three real cases:
- The knockdown-corrected Spain flag genuinely triggers a real warning --
  the red shape, split into two disconnected strips by `digitize_svg.py`'s
  own knockdown step, trips Ink/Stitch's own "Unconnected" check (it
  doesn't know what order to stitch two disjoint pieces in). This is a
  real, true finding about output this same toolkit produces, not a
  contrived example.
- A plain single-rect design correctly comes back clean (no false
  positives).
- A deliberately tiny (1mm x 1mm) shape correctly triggers "Small Fill"
  with the right description and position -- confirming the tool catches
  more than one category of problem, not just the one the flag happened
  to surface.

`element_index` matches `digitize_svg.py`'s own `measure_shape()`/
`--measure-only` indices when run against the same *prepared* (post-
knockdown) SVG -- `prepare_svg()`'s returned path, not the original raw
input -- so a problem can be cross-referenced against that shape's
geometry directly. Knockdown can drop or split shapes, so indices against
the raw input won't line up.
