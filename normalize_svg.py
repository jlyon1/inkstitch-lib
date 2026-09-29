#!/usr/bin/env python3
"""
Normalize an SVG's authoring shortcuts into plain filled shapes that
digitize_svg.py / check_design.py can process unchanged. Handles two
patterns real-world SVGs (flags, logos, icons
exported from Wikipedia/Illustrator/etc.) commonly use that a plain
fill-based pipeline doesn't:

  1. <use> clones -- one shape defined once and reused at several
     positions (often nested: a clone of a clone of a clone, to avoid
     repeating the same geometry dozens of times). Resolved recursively
     into concrete, already-transformed shapes.
  2. Stroked-only paths with no fill -- e.g. a zigzag line meant to *look*
     like a set of solid bands when stroked at a given width, rather than
     actual filled rectangles. Converted into one filled shape per stroked
     line segment (buffered by half the stroke width), not one shape
     covering the whole path -- see "why per-segment, not unioned" below.

First proven against the real Wikipedia US flag SVG, which uses both:
the 50-star canton is a single star <path> cloned through several nested
<use> levels (1 -> 4 -> 5 -> 9 -> 18 -> 50 stars), and the 6 white stripes
are one stroked zigzag path, not 6 rects.

Usage:
    uv run normalize_svg.py input.svg output.svg --width-mm 80
"""

import argparse
import copy
import os

from lxml import etree
from shapely.geometry import LineString

import inkex
from lib.elements.element import EmbroideryElement
from digitize_svg import build_wrapped_svg, document_dimensions, polygon_to_path_d, PIXELS_PER_MM

SVG_NS = "http://www.w3.org/2000/svg"
XLINK_NS = "http://www.w3.org/1999/xlink"

EMBROIDERABLE_TAGS = ("rect", "path", "polygon", "polyline", "circle", "ellipse", "line", "g")

# Same set, minus "g" -- for the final rebuild loop, which has to emit one
# leaf shape per node, not the group wrapping them.
_LEAF_SHAPE_TAGS = ("rect", "path", "polygon", "polyline", "circle", "ellipse", "line")


def resolve_uses(root):
    """Recursively replace every <use> with a deep copy of what it
    references, wrapped in a translating <g> -- <use> can reference a <g>
    that itself contains further <use> elements (exactly how the US flag's
    star canton doubles one star up to 50 through several nested levels),
    so resolution has to recurse into what it just cloned rather than
    assuming one pass reaches real geometry.
    """
    id_map = {el.get("id"): el for el in root.iter() if el.get("id")}

    def walk(el):
        for child in list(el):
            if etree.QName(child).localname == "use":
                href = child.get(f"{{{XLINK_NS}}}href") or child.get("href")
                ref = id_map[href.lstrip("#")]
                x = float(child.get("x", 0))
                y = float(child.get("y", 0))
                clone = copy.deepcopy(ref)
                wrapper = etree.SubElement(el, f"{{{SVG_NS}}}g")
                wrapper.set("transform", f"translate({x},{y})")
                wrapper.append(clone)
                el.remove(child)
                walk(wrapper)
            else:
                walk(child)

    walk(root)


def rings_to_path_d(paths):
    return " ".join(
        "M " + " L ".join(f"{x},{y}" for x, y in ring) + " Z"
        for ring in paths if len(ring) >= 3
    )


def element_to_flat_paths(node, is_stroke):
    """One embroiderable node -> one or more absolute, already-transformed
    <path> elements, using EmbroideryElement's own geometry/color
    resolution (.paths, .fill_color/.stroke_color) rather than copying the
    node's raw attributes, which would lose inherited fill (e.g. this
    node's color set once on a distant ancestor <g>, not on the node
    itself) and any accumulated transform from resolve_uses's <g>
    wrapping.

    Why per-segment for strokes, not one unioned path: a stroked path
    disconnected into several separate line segments (like the flag's 6
    stripe lines) produces one shape per segment here, each its own
    element -- unioning them into a single multi-part path instead made
    check_design.py flag it as "Unconnected" (Ink/Stitch doesn't know what
    order to stitch disjoint pieces of one object in), which is a real,
    correct complaint caused by that unioning choice, not by the source
    design.
    """
    element = EmbroideryElement(node)
    paths = element.paths

    if is_stroke:
        color = str(element.stroke_color)
        width = element.stroke_width
        results = []
        for point_list in paths:
            if len(point_list) < 2:
                continue
            band = LineString(point_list).buffer(width / 2, cap_style="flat")
            d = polygon_to_path_d(band)
            if not d:
                continue
            el = etree.Element(f"{{{SVG_NS}}}path")
            el.set("d", d)
            el.set("fill", color)
            el.set("fill-rule", "evenodd")
            results.append(el)
        return results

    color = str(element.fill_color)
    d = rings_to_path_d(paths)
    if not d:
        return []
    el = etree.Element(f"{{{SVG_NS}}}path")
    el.set("d", d)
    el.set("fill", color)
    el.set("fill-rule", "evenodd")
    return [el]


def normalize_svg(input_svg_path, output_svg_path, target_width_mm=100):
    source = etree.parse(input_svg_path).getroot()
    resolve_uses(source)

    # Shared with digitize_svg.py's prepare_svg() -- same viewBox-or-
    # width/height fallback, same unit handling, one implementation.
    vb_w, vb_h = document_dimensions(source)

    # Wrap once, unmodified, purely so EmbroideryElement has a real, loaded
    # Ink/Stitch document to read transform-resolved geometry from -- it
    # needs a live document tree, not a bare lxml one.
    shapes = [copy.deepcopy(child) for child in source if etree.QName(child).localname in EMBROIDERABLE_TAGS]
    pre = build_wrapped_svg(vb_w, vb_h, target_width_mm, shapes)
    pre_fd, pre_path = __import__("tempfile").mkstemp(suffix=".svg")
    with os.fdopen(pre_fd, "wb") as f:
        f.write(etree.tostring(pre))

    with open(pre_path, "rb") as f:
        doc = inkex.load_svg(f).getroot()

    final_shapes = []
    for node in doc.iter():
        if etree.QName(node).localname not in _LEAF_SHAPE_TAGS:
            continue
        # Literal-attribute check, not computed style: good enough to
        # distinguish "stroked line meant to look like a band" from a
        # normally filled shape without needing a fully general CSS
        # fill-vs-stroke classifier for this scope.
        is_stroke = node.get("stroke") is not None and node.get("fill") is None
        final_shapes.extend(element_to_flat_paths(node, is_stroke))

    os.unlink(pre_path)

    # element.paths (used inside element_to_flat_paths) returns coordinates
    # already in Ink/Stitch's PIXELS_PER_MM physical space, not the source
    # document's raw viewBox units -- same trap remove_hidden_overlap in
    # digitize_svg.py hit and fixed. The output viewBox has to match the
    # space these rebuilt paths are actually in.
    #
    # Output as a *plain* source SVG (shapes as direct children of <svg>,
    # no Ink/Stitch metadata wrapper) -- digitize_svg.py's own prepare_svg
    # expects a plain design SVG and does its own wrapping; handing it
    # something already build_wrapped_svg-wrapped would hide every shape
    # one level too deep inside a <g> for prepare_svg's direct-children scan.
    px_w = target_width_mm * PIXELS_PER_MM
    px_h = (target_width_mm * (vb_h / vb_w)) * PIXELS_PER_MM
    final = etree.Element(
        f"{{{SVG_NS}}}svg",
        nsmap={None: SVG_NS},
        attrib={"width": f"{px_w}", "height": f"{px_h}", "viewBox": f"0 0 {px_w} {px_h}"},
    )
    for el in final_shapes:
        final.append(el)
    with open(output_svg_path, "wb") as f:
        f.write(etree.tostring(final))

    return len(final_shapes)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("input_svg")
    parser.add_argument("output_svg")
    parser.add_argument("--width-mm", type=float, default=100)
    args = parser.parse_args()

    count = normalize_svg(args.input_svg, args.output_svg, target_width_mm=args.width_mm)
    print(f"{count} shapes after normalization")
