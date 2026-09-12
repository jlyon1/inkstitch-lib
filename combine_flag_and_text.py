#!/usr/bin/env python3
"""
[Flag] CountryName -- combine digitize_svg.py's flag output with
batch_text_to_pes.py's text output into one embroidery file, in one of
three layouts: text to the right of the flag (default), text to the left,
or text centered underneath.

These are two independently-proven pipelines (flag: real SVG through Ink/
Stitch's fill engine; text: the same lettering pipeline embroider-web uses
in production) merged at the stitch-plan level with pyembroidery, rather
than trying to combine them inside a single Ink/Stitch SVG document --
simpler, and each half stays exactly as verified on its own.

Usage:
    uv run combine_flag_and_text.py flag.svg "Spain" "Roman AGS" output.pes --layout right
    uv run combine_flag_and_text.py flag.svg "Spain" "Roman AGS" output.pes --layout left
    uv run combine_flag_and_text.py flag.svg "Spain" "Roman AGS" output.pes --layout under
"""

import argparse
import os
import sys

import pyembroidery

import _inkstitch_headless  # noqa: E402,F401
from digitize_svg import digitize_svg  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from batch_text_to_pes import text_to_embroidery  # noqa: E402


def pattern_bounds_mm(pattern):
    xs = [s[0] for s in pattern.stitches]
    ys = [s[1] for s in pattern.stitches]
    return min(xs) / 10, min(ys) / 10, max(xs) / 10, max(ys) / 10


def combine(patterns_with_offsets_mm):
    """patterns_with_offsets_mm: [(EmbPattern, dx_mm, dy_mm), ...], left to
    right in the order they should stitch."""
    combined = pyembroidery.EmbPattern()
    first = True
    for pattern, dx_mm, dy_mm in patterns_with_offsets_mm:
        dx, dy = dx_mm * 10, dy_mm * 10
        for stitches, thread in pattern.get_as_colorblocks():
            if not first:
                combined.color_change()
            combined.add_thread(thread)
            for x, y, cmd in stitches:
                # Each source pattern's own last stitch carries its own
                # trailing END command (get_as_colorblocks() hands that back
                # verbatim) -- copying it through mid-sequence made writers
                # treat the pattern as over right there, silently dropping
                # everything appended after it (the flag's END was cutting
                # the text off entirely). Only a single END at the very end
                # of the whole combined pattern belongs here. Same story for
                # COLOR_CHANGE: a block's stitches can carry their own
                # leading/trailing color-change command from the source
                # pattern's original threadlist transition, which duplicated
                # against the explicit combined.color_change() call above --
                # an adjacent, zero-length "dead" color segment that shifted
                # every later thread index by one (the flag's real yellow
                # silently inherited an unrelated black thread slot).
                # Transitions are entirely our own explicit calls now.
                if cmd in (pyembroidery.END, pyembroidery.COLOR_CHANGE):
                    continue
                combined.add_stitch_absolute(cmd, x + dx, y + dy)
            first = False
    combined.add_stitch_absolute(pyembroidery.END, 0, 0)
    return combined


LAYOUTS = ("right", "left", "under")


def _layout_offsets(layout, flag_w, flag_h, text_w, text_h, gap_mm):
    """Where each piece's own (0,0)-normalized origin should land, for one
    of the three arrangements. Perpendicular-axis centering always centers
    the *smaller* piece on the *larger* one (e.g. flag_dy's
    max(0, (text_h - flag_h) / 2) is a no-op, and text gets centered on the
    flag instead, whenever the flag is the taller of the two) -- same
    formula covers either direction rather than needing a per-case branch.
    """
    if layout == "right":
        return (
            0, max(0, (text_h - flag_h) / 2),
            flag_w + gap_mm, max(0, (flag_h - text_h) / 2),
        )
    elif layout == "left":
        return (
            text_w + gap_mm, max(0, (text_h - flag_h) / 2),
            0, max(0, (flag_h - text_h) / 2),
        )
    elif layout == "under":
        max_w = max(flag_w, text_w)
        return (
            max(0, (max_w - flag_w) / 2), 0,
            max(0, (max_w - text_w) / 2), flag_h + gap_mm,
        )
    raise ValueError(f"layout must be one of {LAYOUTS}, got {layout!r}")


def flag_and_name(flag_svg_path, country_name, font, output_path, layout="right",
                   flag_height_mm=20, gap_mm=5, text_scale=60):
    if layout not in LAYOUTS:
        raise ValueError(f"layout must be one of {LAYOUTS}, got {layout!r}")

    tmp_dir = os.path.dirname(output_path) or "."

    flag_path = os.path.join(tmp_dir, f"_tmp_flag_{os.getpid()}.pes")
    text_path = os.path.join(tmp_dir, f"_tmp_text_{os.getpid()}.pes")

    # Flag width follows from its own aspect ratio at the target height --
    # digitize_svg takes a target *width*, so read the source aspect ratio
    # first rather than guessing.
    from lxml import etree
    source = etree.parse(flag_svg_path).getroot()
    vb = source.get("viewBox")
    if vb:
        _, _, vb_w, vb_h = [float(v) for v in vb.split()]
    else:
        vb_w = float(source.get("width", "100").rstrip("px"))
        vb_h = float(source.get("height", "100").rstrip("px"))
    flag_width_mm = flag_height_mm * (vb_w / vb_h)

    digitize_svg(flag_svg_path, flag_path, target_width_mm=flag_width_mm)
    text_to_embroidery(country_name, text_path, font=font, scale=text_scale)

    flag_pattern = pyembroidery.read(flag_path)
    text_pattern = pyembroidery.read(text_path)

    flag_x0, flag_y0, flag_x1, flag_y1 = pattern_bounds_mm(flag_pattern)
    text_x0, text_y0, text_x1, text_y1 = pattern_bounds_mm(text_pattern)
    flag_w, flag_h = flag_x1 - flag_x0, flag_y1 - flag_y0
    text_w, text_h = text_x1 - text_x0, text_y1 - text_y0

    flag_off_x, flag_off_y, text_off_x, text_off_y = _layout_offsets(
        layout, flag_w, flag_h, text_w, text_h, gap_mm
    )

    # Each pattern's stitches start wherever its own bbox happens to begin,
    # not necessarily at (0, 0) -- normalize to a shared origin first, then
    # add the layout's own placement offset on top.
    flag_dx, flag_dy = -flag_x0 + flag_off_x, -flag_y0 + flag_off_y
    text_dx, text_dy = -text_x0 + text_off_x, -text_y0 + text_off_y

    combined = combine([
        (flag_pattern, flag_dx, flag_dy),
        (text_pattern, text_dx, text_dy),
    ])

    ext = os.path.splitext(output_path)[1][1:].lower()
    write_fn = getattr(pyembroidery, f"write_{ext}")
    write_fn(combined, output_path)

    os.unlink(flag_path)
    os.unlink(text_path)

    x0, y0, x1, y1 = pattern_bounds_mm(combined)
    return {
        "output": output_path,
        "stitches": len(combined.stitches),
        "width_mm": round(x1 - x0, 1),
        "height_mm": round(y1 - y0, 1),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("flag_svg")
    parser.add_argument("name")
    parser.add_argument("font")
    parser.add_argument("output")
    parser.add_argument("--layout", "--position", dest="layout", choices=LAYOUTS, default="right")
    parser.add_argument("--flag-height-mm", type=float, default=20)
    parser.add_argument("--gap-mm", type=float, default=5)
    parser.add_argument("--text-scale", type=float, default=60)
    args = parser.parse_args()

    result = flag_and_name(
        args.flag_svg, args.name, args.font, args.output, layout=args.layout,
        flag_height_mm=args.flag_height_mm, gap_mm=args.gap_mm, text_scale=args.text_scale,
    )
    print(result)
