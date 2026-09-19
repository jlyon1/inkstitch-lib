#!/usr/bin/env python3
"""
Expose Ink/Stitch's own troubleshooting checks (lib/elements/*.py's
validation_errors()/validation_warnings(), the same data
lib/extensions/troubleshoot.py draws as pointer markers for a human in
Inkscape) as structured data an agent can read directly -- errors (will
prevent the shape from stitching), warnings (will stitch, but probably
shouldn't be ignored), and object-type warnings (not a shape Ink/Stitch
can embroider at all).

Not a new check of any kind -- this is the same validation logic Ink/
Stitch already runs, just returned as data instead of drawn as an SVG
layer for a human to look at.

Usage:
    uv run check_design.py design.svg
    uv run check_design.py design.svg --width-mm 80
"""

import argparse
import json

import _inkstitch_headless  # noqa: F401
import inkex
from lib.elements.utils.nodes import node_to_elements
from lxml import etree


EMBROIDERABLE_TAGS = ("rect", "path", "polygon", "polyline", "circle", "ellipse", "line")


def check_design(svg_path):
    """Every error/warning Ink/Stitch's own validation finds, across every
    embroiderable element in the document -- in document order, same as
    digitize_svg.py processes them. Each problem is
    {severity, name, description, position_mm, steps_to_solve, element_index},
    where element_index matches the index a caller would see from
    digitize_svg.py's own measure_shape() output for the same document,
    so problems can be cross-referenced against that geometry.
    """
    with open(svg_path, "rb") as f:
        doc = inkex.load_svg(f).getroot()

    nodes = [child for child in doc.iter() if etree.QName(child).localname in EMBROIDERABLE_TAGS]

    problems = []
    for index, node in enumerate(nodes):
        for element in node_to_elements(node):
            for error in element.validation_errors():
                problems.append(_problem_dict(index, "error", error))
            for warning in element.validation_warnings():
                severity = "type_warning" if type(warning).__name__.endswith("TypeWarning") else "warning"
                problems.append(_problem_dict(index, severity, warning))

    return problems


def _problem_dict(element_index, severity, problem):
    return {
        "element_index": element_index,
        "severity": severity,
        "name": problem.name,
        "description": problem.description,
        "position_mm": [round(problem.position.x / _PIXELS_PER_MM, 2), round(problem.position.y / _PIXELS_PER_MM, 2)],
        "steps_to_solve": list(problem.steps_to_solve),
    }


_PIXELS_PER_MM = 96 / 25.4


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("svg")
    args = parser.parse_args()

    problems = check_design(args.svg)
    if not problems:
        print(json.dumps({"clean": True, "problems": []}, indent=2))
    else:
        print(json.dumps({"clean": False, "problems": problems}, indent=2))
