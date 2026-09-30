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

    new_elements = []
    measurements = []
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
        params = {**uniform_params, **shape_params.get(index, {})}
        for param, value in params.items():
            path_el.set(f"{{{INKSTITCH_NS}}}{param}", str(value))
        new_elements.append(path_el)
        measurements.append({"index": index, "color": color, **measure_shape(visible)})

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
