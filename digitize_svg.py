#!/usr/bin/env python3
"""
Prototype #2: an ALREADY-vector SVG (a real logo/flag, not a raster photo)
fed straight into Ink/Stitch, skipping vtracer entirely. Proves the "zero
extra tagging needed" claim directly -- node_to_elements() classifies any
filled <rect>/<path>/<polygon>/etc. as a FillStitch element by default, so a
plain flat-color SVG someone already has should Just Work.

Usage:
    uv run digitize_svg.py input.svg output.pes [--width-mm N]
"""

import argparse
import re
import sys
import os
import tempfile

from lxml import etree

# lib.extensions/__init__.py has every extension's eager import commented
# out (see "Remove wx dependency from lettering path" on main) -- unlike the
# digitize-svg-prototype branch this was lifted from, these imports resolve
# with no wx shim needed and no real wxPython installed, the same way
# batch_text_to_pes.py's lib.extensions.batch_lettering import already does.
import inkex  # noqa: E402
from lib.elements.fill_stitch import FillStitch  # noqa: E402
from lib.extensions.output import Output  # noqa: E402
from shapely.ops import unary_union  # noqa: E402
from svgelements import Length

SVG_NS = "http://www.w3.org/2000/svg"
INKSCAPE_NS = "http://www.inkscape.org/namespaces/inkscape"
INKSTITCH_NS = "http://inkstitch.org/namespace"

# Same convention Ink/Stitch itself uses internally (see lib/svg/__init__.py's
# PIXELS_PER_MM) -- FillStitch.shape returns coordinates already converted
# into this space, so anything rebuilding an SVG from extracted .shape
# geometry has to declare its viewBox in these units, not the source
# document's original ones.
PIXELS_PER_MM = 96 / 25.4

# See prepare_svg's own docstring: the floor under which knockdown's
# FillStitch-based geometry math is never actually run, regardless of how
# small the real requested output is, so self-intersecting source shapes
# don't silently lose pieces to Ink/Stitch's own fixed-area validity
# threshold. 100mm is not a precisely measured minimum -- it's a generous
# floor chosen to comfortably clear that threshold for realistic design
# detail; there was no report of shapes vanishing at 100mm+ during testing.
MIN_SAFE_GEOMETRY_WIDTH_MM = 100

# See remove_hidden_overlap's own comment on where this is used. Below this
# ratio, a shape's "long axis" is close enough to arbitrary (a near-circle,
# a near-square) that forcing a fill angle onto it isn't worth doing; above
# it, getting the angle right measurably changes stitch density, verified
# on a real martini-glass stem (aspect_ratio 14.36, width 1.87mm).
ASPECT_RATIO_ANGLE_THRESHOLD = 2.0

# Ink/Stitch's own FillStitch.row_spacing default (lib/elements/fill_stitch.py:
# get_float_param("row_spacing_mm", 0.25)) -- used as the baseline to widen
# from when nothing else was actually requested for a thin shape.
DEFAULT_ROW_SPACING_MM = 0.25

# See remove_hidden_overlap's own comment on where these are used.
THIN_SHAPE_WIDTH_MM = 5.0
MAX_ROWS_FOR_THIN_SHAPES = 4


def add_inkstitch_metadata(svg):
    metadata = etree.SubElement(svg, f"{{{SVG_NS}}}metadata")
    inkstitch_metadata = etree.SubElement(metadata, f"{{{INKSTITCH_NS}}}inkstitch-metadata")
    version_elem = etree.SubElement(inkstitch_metadata, f"{{{INKSTITCH_NS}}}inkstitch-version")
    version_elem.text = "3.0"
    settings = {"collapse_len_mm": "3.0", "min_stitch_len_mm": "0.2", "thread-palette": ""}
    for key, value in settings.items():
        elem = etree.SubElement(inkstitch_metadata, f"{{{INKSTITCH_NS}}}{key}")
        elem.text = value


EMBROIDERABLE_TAGS = ("rect", "path", "polygon", "polyline", "circle", "ellipse", "line")


class DesignTooComplexError(Exception):
    """Raised when a design is still too expensive to fill-stitch for a
    synchronous request, even after remove_hidden_overlap's own
    simplify-before-knockdown pass (see SIMPLIFY_TOLERANCE_MM) has already
    thinned it out -- a real failure mode, not a hypothetical one: a
    57-shape hand-traced botanical SVG (a public-domain Openclipart
    dandelion, ~3600mm2 of total fill area across those 57 shapes) took
    120-195s to generate fill stitches for depending on simplification
    tolerance, past embroider-web's 180s request timeout, surfacing there as
    a bare 500 with no useful detail. The first instinct was that outline
    point density was the driver (simplifying heavily did cut points
    8093->2804), but real measurement showed stitch *count* barely moved
    (39600->37424) and generation time stayed at ~120s regardless --
    fill-stitch cost here tracks total area needing filling, not how
    detailed each shape's outline is. See MAX_ESTIMATED_STITCHES, the check
    that actually catches this. Raised as soon as knockdown finishes (the
    point where real post-knockdown area is known), before the far more
    expensive fill-generation step runs.
    """


# Empirically calibrated multiplier: real dandelion measurement (37465
# stitches, 3584mm2 total post-knockdown fill area, 0.25mm row spacing --
# Ink/Stitch's own FillStitch default) gives 37465 / (3584 / 0.25) = 2.61.
# Stitch count is modeled as scaling with area/row_spacing (not
# area/row_spacing^2, i.e. not assuming stitch length inside a row also
# scales with row_spacing) since that's what this one real data point
# supports -- a single calibration point, not a verified physical model, so
# MAX_ESTIMATED_STITCHES below carries real margin rather than cutting close.
STITCHES_PER_MM2_PER_MM_SPACING = 2.61

# Estimated stitch count above which fill-stitch generation is too slow for
# a synchronous request. The dandelion above (actual ~37,500 stitches)
# measured 120-195s -- consistently well past embroider-web's 180s timeout.
# 15,000 estimated stitches is under half that, and comfortably above a
# real reference design elsewhere in this pipeline that ran fine at
# 6,400-11,000 stitches (see row_spacing_mm's own docstring in
# svg_digitize_api.py) -- real margin on both sides of this one calibration
# point, not a precisely measured cutoff.
MAX_ESTIMATED_STITCHES = 15000

# Total path/polygon coordinate-point count above which fill-stitch
# generation is too slow -- a secondary guard behind MAX_ESTIMATED_STITCHES
# above (the one that actually caught the dandelion; see
# DesignTooComplexError's own docstring for why point count alone turned
# out not to predict generation cost). Kept as a backstop for the
# knockdown=False path, which never computes shape area and so has no other
# way to bound cost, and for pathologically outline-heavy-but-low-area
# shapes the area check wouldn't otherwise catch.
MAX_TOTAL_PATH_POINTS = 3000

# Simplification tolerance (Douglas-Peucker, shapely's .simplify) applied to
# every shape's geometry before knockdown -- see remove_hidden_overlap. Kept
# at half of DEFAULT_ROW_SPACING_MM's own companion setting,
# min_stitch_len_mm (0.2mm, add_inkstitch_metadata) -- the embroidery
# machine itself can't produce a stitch shorter than that, so outline detail
# finer than half of it can't meaningfully change the stitched-out result
# regardless of how faithfully it's traced. Worth doing regardless of
# MAX_ESTIMATED_STITCHES above (free, no quality cost, and it does cut
# generation time somewhat -- 142s->120s measured across the dandelion's
# tolerance range) even though it isn't sufficient by itself to rescue a
# design whose cost is area-driven rather than outline-driven.
SIMPLIFY_TOLERANCE_MM = 0.15


def _count_shape_points(node, tag):
    """Rough coordinate-point count for one shape -- every numeric token in
    the relevant attribute is ~half a coordinate pair, which is all this
    needs to bound how expensive the shape's outline is to fill-stitch; an
    exact path parse isn't worth it just for that.
    """
    if tag == "path":
        return len(re.findall(r"-?\d*\.?\d+", node.get("d", "") or "")) // 2
    if tag in ("polygon", "polyline"):
        return len(re.findall(r"-?\d*\.?\d+", node.get("points", "") or "")) // 2
    # rect/circle/ellipse/line: a handful of fixed attributes regardless of
    # how many of them appear -- not worth counting against the limit.
    return 1


def _measure_polygon(poly):
    import math
    min_rect = poly.minimum_rotated_rectangle
    coords = list(min_rect.exterior.coords)
    # minimum_rotated_rectangle's first two edges give the two side lengths;
    # whichever is shorter is the "width" a satin/fill judgment call hinges on.
    edge_lengths = [
        ((coords[i + 1][0] - coords[i][0]) ** 2 + (coords[i + 1][1] - coords[i][1]) ** 2) ** 0.5
        for i in range(2)
    ]
    length, width = max(edge_lengths), min(edge_lengths)
    long_edge_index = edge_lengths.index(length)
    (x1, y1), (x2, y2) = coords[long_edge_index], coords[long_edge_index + 1]
    angle_degrees = math.degrees(math.atan2(y2 - y1, x2 - x1)) % 180

    return {
        "area_mm2": round(poly.area / PIXELS_PER_MM ** 2, 2),
        "length_mm": round(length / PIXELS_PER_MM, 2),
        "width_mm": round(width / PIXELS_PER_MM, 2),
        "aspect_ratio": round(length / width, 2) if width > 0 else None,
        "long_axis_angle_degrees": round(angle_degrees, 1),
    }


def measure_shape(shape):
    """Geometric facts about one region, in real mm -- the raw material an
    agent needs to reason about stitch type/angle itself, rather than a
    single hardcoded heuristic baked in here. A shape that's long and
    narrow (aspect_ratio far from 1, width_mm small) is a satin-column
    candidate a human digitizer would rarely fill; long_axis_angle_degrees
    is the shape's own orientation, a reasonable starting point for a fill
    angle that runs with (or, just as validly, across) the shape instead of
    at an arbitrary default.

    Knockdown can leave a shape as several disconnected pieces (e.g. a
    background split into a strip above and below a band on top of it) --
    measuring the combined bounding rectangle in that case understates how
    thin any one piece actually is (two 13mm-tall strips 40mm apart read as
    one 53mm-tall region), which is exactly the fact a fill-vs-satin choice
    hinges on. Multi-part shapes get a per-part breakdown; the top-level
    fields stay as an aggregate for a quick single-number read.
    """
    polys = list(shape.geoms) if hasattr(shape, "geoms") else [shape]
    polys = [p for p in polys if not p.is_empty]
    parts = [_measure_polygon(p) for p in polys]

    aggregate = _measure_polygon(shape)
    aggregate["part_count"] = len(parts)
    if len(parts) > 1:
        aggregate["parts"] = parts
    return aggregate


def build_wrapped_svg(vb_w, vb_h, target_width_mm, elements):
    """The required Ink/Stitch shell (see add_inkstitch_metadata), with the
    given already-final shape elements dropped straight into a plain group.
    """
    height_mm = target_width_mm * (vb_h / vb_w)
    svg = etree.Element(
        f"{{{SVG_NS}}}svg",
        nsmap={None: SVG_NS, "inkscape": INKSCAPE_NS, "inkstitch": INKSTITCH_NS},
        attrib={
            "width": f"{target_width_mm}mm",
            "height": f"{height_mm}mm",
            "viewBox": f"0 0 {vb_w} {vb_h}",
        },
    )
    etree.SubElement(svg, f"{{{SVG_NS}}}defs")
    add_inkstitch_metadata(svg)
    group = etree.SubElement(svg, f"{{{SVG_NS}}}g")
    for el in elements:
        group.append(el)
    return svg


def polygon_to_path_d(geom):
    """shapely (Multi)Polygon -> SVG path d string. fill-rule=evenodd on the
    caller's side is what makes holes render correctly regardless of ring
    winding order, which shapely doesn't guarantee matches SVG convention.
    """
    polygons = list(geom.geoms) if hasattr(geom, "geoms") else [geom]
    parts = []
    for poly in polygons:
        if poly.is_empty:
            continue
        for ring in [poly.exterior] + list(poly.interiors):
            coords = list(ring.coords)
            if len(coords) < 3:
                continue
            d = f"M {coords[0][0]},{coords[0][1]} "
            d += " ".join(f"L {x},{y}" for x, y in coords[1:])
            d += " Z"
            parts.append(d)
    return " ".join(parts)


def remove_hidden_overlap(svg_path, vb_w, vb_h, geometry_width_mm, shape_params=None, uniform_params=None, output_width_mm=None):
    """Subtract every shape's on-top neighbors from its own area, in document
    (z/paint) order, so two overlapping fills never both stitch the same
    ground -- e.g. a background rect fully covered by a band on top of it
    should not *also* get stitched underneath, just wasted thread and a
    lumpier fabric build-up for no visual difference. Reuses FillStitch's own
    .shape (transform-aware, curve-flattened real geometry) for each source
    shape rather than re-parsing path data by hand.

    Also measures each *visible* (post-subtraction) shape and applies any
    caller-supplied per-shape stitch params (angle, row_spacing_mm, keyed by
    the same index measurements are reported under) -- measuring before
    subtraction would hand back facts about geometry that may no longer be
    what actually gets stitched. uniform_params applies to every shape
    regardless of index -- e.g. one row_spacing_mm for a whole design's
    stitch density, set before knowing how many shapes will survive
    knockdown. shape_params (index-keyed) wins on any key both set, since
    it's the more specific request.

    geometry_width_mm and output_width_mm are deliberately separate.
    geometry_width_mm must match whatever physical width svg_path (the
    incoming wrap) was already built at -- it is only used to declare the
    *coordinate space* the corrected doc's viewBox is in, matching where
    FillStitch.shape's extracted coordinates actually live. output_width_mm
    (defaults to geometry_width_mm) is the real physical size to declare
    for the finished document -- see prepare_svg's own comment for why a
    caller may deliberately ask for shape math at a larger scale than the
    real requested output size.
    """
    shape_params = shape_params or {}
    uniform_params = uniform_params or {}
    with open(svg_path, "rb") as f:
        doc = inkex.load_svg(f).getroot()

    nodes = [child for child in doc.iter() if etree.QName(child).localname in EMBROIDERABLE_TAGS]
    shapes = [FillStitch(node).shape for node in nodes]
    colors = [node.get("fill", "#000000") for node in nodes]

    # Thin out outline detail finer than the embroidery machine can stitch
    # anyway (see SIMPLIFY_TOLERANCE_MM) before the O(shapes^2) difference/
    # union work below and the far more expensive fill-generation step that
    # follows prepare_svg() -- both scale with how many points these shapes
    # carry, and a hand-traced source can carry far more than the stitched
    # result could ever show.
    tolerance_px = SIMPLIFY_TOLERANCE_MM * PIXELS_PER_MM
    shapes = [shape.simplify(tolerance_px, preserve_topology=True) for shape in shapes]

    # measure_shape's area_mm2 is computed in *geometry* space, i.e. at
    # geometry_width_mm (floor-clamped to MIN_SAFE_GEOMETRY_WIDTH_MM --
    # see prepare_svg's own docstring on why), not necessarily the real
    # final output_width_mm this document will actually be stitched at.
    # row_spacing_mm, in contrast, is a fixed real-mm value applied at the
    # *final* declared size. For a request below the geometry floor (e.g.
    # target_width_mm=25 against a 100mm geometry floor), real stitched
    # area is smaller than geometry-space area by the square of that scale
    # ratio -- skipping this correction would overestimate real stitch
    # count for any such request and could reject designs that would
    # actually generate fine at the real (small) size requested.
    real_width_mm = output_width_mm or geometry_width_mm
    area_scale_correction = (real_width_mm / geometry_width_mm) ** 2

    new_elements = []
    measurements = []
    estimated_stitches = 0
    for i, (node, shape, color) in enumerate(zip(nodes, shapes, colors)):
        on_top = shapes[i + 1:]
        visible = shape.difference(unary_union(on_top)) if on_top else shape
        if visible.is_empty:
            # Fully hidden under later shapes -- nothing to stitch, and
            # skipping it entirely (not just an empty path) keeps it out of
            # the thread/color list too.
            continue
        index = len(new_elements)
        d = polygon_to_path_d(visible)
        path_el = etree.SubElement(etree.Element(f"{{{SVG_NS}}}g"), f"{{{SVG_NS}}}path")
        path_el.set("d", d)
        path_el.set("fill", color)
        path_el.set("fill-rule", "evenodd")

        measurement = measure_shape(visible)
        params = {**uniform_params}
        # Ink/Stitch's own angle default is a flat 0 degrees (get_float_param
        # in fill_stitch.py) -- fine for a roughly round/square shape, where
        # no direction is meaningfully better than another, but wrong often
        # enough to matter for anything elongated: rows running across a
        # narrow shape's short axis instead of along its long one still
        # cover the same area, but need far more of them (row_spacing_mm
        # applies across whichever axis the rows run perpendicular to), each
        # one short, which reads as "way too dense" even though row spacing
        # never changed. measure_shape's own long_axis_angle_degrees is
        # exactly the fix -- already computed here for every shape, just
        # never applied until now. ASPECT_RATIO_ANGLE_THRESHOLD guards
        # against forcing an angle onto a shape too close to round for
        # "long axis" to mean much (a near-circle's minimum-rotated-
        # rectangle angle is essentially noise).
        if measurement["aspect_ratio"] and measurement["aspect_ratio"] >= ASPECT_RATIO_ANGLE_THRESHOLD:
            params["angle"] = measurement["long_axis_angle_degrees"]

        # Second, independent fix for the same "way too dense" symptom:
        # even with the angle now correct, a genuinely narrow shape (under
        # THIN_SHAPE_WIDTH_MM) still packs an unreasonable number of rows
        # across its own short axis at a row_spacing_mm tuned for a normal-
        # sized area -- e.g. a 1.87mm-wide sliver at 0.25mm spacing is ~7.5
        # rows, each barely longer than the width itself, before this fix.
        # Capping to MAX_ROWS_FOR_THIN_SHAPES by widening spacing (never
        # narrowing -- an explicit denser request from the caller still
        # wins below) measurably fixed this on a real design: isolated
        # (angle-only-fixed) stem shape went from 310 stitches to 178 once
        # this was added on top, a 43% drop on top of angle's own ~6%.
        # Deliberately keyed on absolute width_mm, not aspect_ratio: a
        # 12mm-wide elongated shape at the same 0.25mm spacing is a normal
        # ~48 rows, not a density problem, and this must not touch it.
        width_mm = measurement.get("width_mm") or 0
        thin_shape_adjusted = False
        if 0 < width_mm < THIN_SHAPE_WIDTH_MM:
            requested_spacing = params.get("row_spacing_mm", DEFAULT_ROW_SPACING_MM)
            min_spacing_for_width = width_mm / MAX_ROWS_FOR_THIN_SHAPES
            if min_spacing_for_width > requested_spacing:
                params["row_spacing_mm"] = min_spacing_for_width
                thin_shape_adjusted = True

        params.update(shape_params.get(index, {}))  # explicit request always wins

        # This shape's share of total estimated stitch count -- uses its own
        # effective row_spacing_mm (which may have been widened just above
        # for a thin shape, or overridden by an explicit request), not a
        # single design-wide spacing, since a mix of normal and thin-adjusted
        # shapes genuinely costs less than treating every shape at the
        # densest spacing in play. See STITCHES_PER_MM2_PER_MM_SPACING.
        shape_row_spacing = params.get("row_spacing_mm", DEFAULT_ROW_SPACING_MM)
        real_area_mm2 = measurement["area_mm2"] * area_scale_correction
        estimated_stitches += (
            STITCHES_PER_MM2_PER_MM_SPACING * real_area_mm2 / shape_row_spacing
        )

        for param, value in params.items():
            path_el.set(f"{{{INKSTITCH_NS}}}{param}", str(value))
        new_elements.append(path_el)
        # thin_shape_adjusted: surfaced so a caller (an end-user-facing page,
        # say) can tell someone "this area was narrow enough that we widened
        # the stitch spacing automatically" -- a real, actionable fact about
        # the output, not something to silently apply and never mention.
        measurements.append({"index": index, "color": color, "thin_shape_adjusted": thin_shape_adjusted, **measurement})

    if estimated_stitches > MAX_ESTIMATED_STITCHES:
        raise DesignTooComplexError(
            f"This design has too much fill area to digitize automatically "
            f"(an estimated {round(estimated_stitches)} stitches across "
            f"{len(new_elements)} shapes; the limit is {MAX_ESTIMATED_STITCHES}). "
            f"Try a smaller or simpler design -- fewer filled areas, less "
            f"total coverage -- and upload it again."
        )

    # No post-knockdown point-count check here, deliberately -- an earlier
    # version had one, but point count turned out not to predict generation
    # cost (see DesignTooComplexError's docstring) and, unlike
    # estimated_stitches above, a raw point count can't be corrected for
    # area_scale_correction either: it's the same count regardless of what
    # target_width_mm was actually requested, so it would reject a small
    # request's genuinely-fast design for the same reason it rejects the
    # full-size one. MAX_TOTAL_PATH_POINTS is still used, but only pre-
    # knockdown for the knockdown=False path in prepare_svg(), which has no
    # area information to check against at all.

    # FillStitch.shape returns coordinates in Ink/Stitch's own physical unit
    # space (96 units/inch, same convention as PIXELS_PER_MM elsewhere in
    # this codebase), NOT the source SVG's raw viewBox units -- reusing
    # vb_w/vb_h here would declare a viewBox against a unit scale the
    # extracted path coordinates are no longer in, silently shrinking the
    # whole design (caught by comparing stitch bounding boxes against the
    # non-knockdown output: this was off by exactly that conversion factor).
    # The new document's viewBox has to match the space the coordinates are
    # actually in (geometry_width_mm, matching svg_path's own scale), so
    # express it directly in that same physical scale -- output_width_mm is
    # a separate, purely declarative choice of the finished document's
    # physical size (see this function's own docstring).
    px_w = geometry_width_mm * PIXELS_PER_MM
    px_h = (geometry_width_mm * (vb_h / vb_w)) * PIXELS_PER_MM

    corrected = build_wrapped_svg(px_w, px_h, output_width_mm or geometry_width_mm, new_elements)
    corrected_fd, corrected_path = tempfile.mkstemp(suffix=".svg")
    with os.fdopen(corrected_fd, "wb") as f:
        f.write(etree.tostring(corrected))
    return corrected_path, measurements


def _parse_length(value, default="100"):
    """A bare width/height attribute, in whatever CSS length unit a real
    SVG happens to use -- Inkscape has written plain "750", "750px", and
    "595.27559pt" all as valid document widths across its own versions,
    and other tools add mm/cm/in/pc to that list. svgelements' Length
    already knows every one of these conversions to the same 96-DPI "user
    unit" space viewBox coordinates and PIXELS_PER_MM both assume --
    handles this correctly rather than a hand-rolled .rstrip("px"), which
    only ever handled a bare "px" suffix or no suffix and crashed
    (ValueError: could not convert string to float) on anything else,
    caught on a real Inkscape-exported "pt" file.
    """
    return Length(value or default).value(ppi=96)


def document_dimensions(source):
    """(width, height) in real SVG user units (96 DPI) -- prefers an
    explicit viewBox (the coordinate space shape geometry is actually
    authored in, which can genuinely differ from the document's own
    width/height -- some SVGs declare a display size in one unit and an
    internal viewBox in a totally different numeric scale) and falls back
    to the width/height attributes only when there is no viewBox at all.
    """
    viewbox = source.get("viewBox")
    if viewbox:
        _, _, vb_w, vb_h = [float(v) for v in viewbox.split()]
    else:
        vb_w = _parse_length(source.get("width"))
        vb_h = _parse_length(source.get("height"))
    return vb_w, vb_h


def prepare_svg(input_svg_path, target_width_mm=100, knockdown=True, shape_params=None, uniform_params=None):
    """Build the corrected, ready-to-stitch intermediate SVG and measure
    every shape that will actually produce stitches -- the "inspect before
    committing" half of the pipeline, usable on its own (--measure-only)
    without ever invoking Output.

    Runs the actual knockdown/FillStitch geometry math at
    max(target_width_mm, MIN_SAFE_GEOMETRY_WIDTH_MM), then declares the
    *real* target_width_mm only in the final corrected document (a pure
    viewBox/width relabeling -- remove_hidden_overlap's output_width_mm --
    not a recomputation). This exists because Ink/Stitch's own
    FillStitch.shape (lib/elements/fill_stitch.py) hardcodes an absolute
    minimum area (min_size=3 in its own internal unit space) when cleaning
    up self-intersecting source geometry via make_valid() -- a threshold
    that does not scale with target_width_mm, so a shape needing that
    cleanup (e.g. a star drawn as one self-intersecting pentagram path,
    which make_valid splits into several small triangles) can have all its
    pieces fall below that fixed threshold at a small physical size and
    vanish entirely, while surviving fine at a larger one. Caught on a real
    50-star flag SVG: 58 shapes survived knockdown at 100/150mm, only 8 at
    50mm -- 44 stars silently gone, not smaller. Simple shapes (no
    self-intersection, nothing for make_valid to touch) are unaffected at
    any size; this fix costs them nothing since the final rescale is
    purely declarative.
    """
    source = etree.parse(input_svg_path).getroot()
    vb_w, vb_h = document_dimensions(source)
    geometry_width_mm = max(target_width_mm, MIN_SAFE_GEOMETRY_WIDTH_MM) if knockdown else target_width_mm

    shapes = [child for child in source if etree.QName(child).localname in EMBROIDERABLE_TAGS]

    if not knockdown:
        # remove_hidden_overlap never runs below, so neither does its
        # simplify-before-measuring pass (see SIMPLIFY_TOLERANCE_MM) -- this
        # is the only complexity guard a knockdown=False request gets, so
        # unlike the knockdown=True path (checked post-simplification, in
        # remove_hidden_overlap itself) it has to check the raw point count.
        total_points = sum(_count_shape_points(s, etree.QName(s).localname) for s in shapes)
        if total_points > MAX_TOTAL_PATH_POINTS:
            raise DesignTooComplexError(
                f"This design has too much outline detail to digitize "
                f"automatically ({total_points} path points across {len(shapes)} "
                f"shapes; the limit is {MAX_TOTAL_PATH_POINTS}). Try simplifying "
                f"the artwork -- fewer nodes, less fine detail -- and upload it "
                f"again."
            )

    svg = build_wrapped_svg(vb_w, vb_h, geometry_width_mm, shapes)

    svg_fd, svg_path = tempfile.mkstemp(suffix=".svg")
    with os.fdopen(svg_fd, "wb") as f:
        f.write(etree.tostring(svg))

    measurements = []
    if knockdown:
        svg_path, measurements = remove_hidden_overlap(
            svg_path, vb_w, vb_h, geometry_width_mm, shape_params=shape_params,
            uniform_params=uniform_params, output_width_mm=target_width_mm,
        )
    elif uniform_params:
        # No knockdown means remove_hidden_overlap (the only place params
        # get written as inkstitch:* attributes) never runs -- without this,
        # a caller-requested row_spacing_mm would silently do nothing on a
        # knockdown=False request instead of applying or erroring.
        for node in svg.iter():
            if etree.QName(node).localname in EMBROIDERABLE_TAGS:
                for param, value in uniform_params.items():
                    node.set(f"{{{INKSTITCH_NS}}}{param}", str(value))
        with open(svg_path, "wb") as f:
            f.write(etree.tostring(svg))

    return svg_path, measurements


class _StdoutWrapper:
    """Output (like every Ink/Stitch extension) writes its result to
    stdout -- this redirects that to a real file without touching the
    process's actual stdout, so nothing else running in the same
    interpreter (an API server handling other requests concurrently) is
    affected.
    """

    def __init__(self, buf):
        self.buffer = buf

    def write(self, data):
        if isinstance(data, str):
            data = data.encode("utf-8")
        self.buffer.write(data)

    def flush(self):
        self.buffer.flush()


def write_embroidery_file(prepared_svg_path, output_path):
    """Generate the real embroidery file from an already-prepared
    (wrapped, optionally knocked-down) SVG -- the second half of
    digitize_svg() below, factored out so a caller that already has a
    prepared_svg_path (e.g. to also run check_design() against the exact
    same intermediate) doesn't need prepare_svg() run a second time.
    """
    output_format = os.path.splitext(output_path)[1][1:].lower()
    with open(output_path, "wb") as out_file:
        original_stdout = sys.stdout
        sys.stdout = _StdoutWrapper(out_file)
        try:
            ext = Output()
            ext.run([prepared_svg_path, f"--format={output_format}"])
        except SystemExit:
            pass
        finally:
            sys.stdout = original_stdout


def digitize_svg(input_svg_path, output_path, target_width_mm=100, knockdown=True, shape_params=None, uniform_params=None):
    svg_path, measurements = prepare_svg(
        input_svg_path, target_width_mm=target_width_mm, knockdown=knockdown,
        shape_params=shape_params, uniform_params=uniform_params,
    )
    write_embroidery_file(svg_path, output_path)
    return svg_path, measurements


if __name__ == "__main__":
    import json

    parser = argparse.ArgumentParser()
    parser.add_argument("svg")
    parser.add_argument("output", nargs="?")
    parser.add_argument("--width-mm", type=float, default=100)
    parser.add_argument("--no-knockdown", action="store_true", help="skip hidden-overlap removal")
    parser.add_argument("--measure-only", action="store_true", help="print per-shape geometry, generate nothing")
    parser.add_argument(
        "--angle", action="append", default=[], metavar="INDEX=DEGREES",
        help="set inkstitch:angle on one shape by its post-knockdown index (repeatable)",
    )
    args = parser.parse_args()

    shape_params = {}
    for entry in args.angle:
        idx, degrees = entry.split("=")
        shape_params.setdefault(int(idx), {})["angle"] = float(degrees)

    if args.measure_only:
        _, measurements = prepare_svg(
            args.svg, target_width_mm=args.width_mm, knockdown=not args.no_knockdown
        )
        print(json.dumps(measurements, indent=2))
    else:
        svg_path, measurements = digitize_svg(
            args.svg, args.output, target_width_mm=args.width_mm,
            knockdown=not args.no_knockdown, shape_params=shape_params,
        )
        print(f"{len(measurements)} shape(s) after knockdown. Intermediate SVG: {svg_path}")
        for m in measurements:
            print(f"  [{m['index']}] {m['color']}: {m['length_mm']}x{m['width_mm']}mm, "
                  f"aspect {m['aspect_ratio']}, long axis {m['long_axis_angle_degrees']}deg")
