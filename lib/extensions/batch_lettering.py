# Authors: see git history
#
# Copyright (c) 2025 Authors
# Licensed under the GNU GPL version 3.0 or later.  See the file LICENSE for details.
import argparse
import json
import os
import sys

from inkex import Boolean, Group
from lxml import etree
import pystitch

from lib.commands import global_command
from lib.stitch_plan.stitch import Stitch
from ..elements import nodes_to_elements, iterate_nodes
from ..extensions.lettering_along_path import TextAlongPath
from ..i18n import _
# Deferred import to avoid circular dependency: from ..lettering import get_font_by_name
from ..metadata import InkStitchMetadata
from ..stitch_plan import stitch_groups_to_stitch_plan
from ..svg import get_correction_transform, PIXELS_PER_MM
from ..threads import ThreadCatalog
from ..utils import DotDict, Point


def errormsg(message):
    print(message, file=sys.stderr)

class BatchLettering():
    def __init__(self, svg_element, *args, **kwargs):
        """
        Initialize BatchLettering with an SVG element.

        Args:
            svg_element: An lxml Element representing the SVG root
        """
        self.arg_parser = argparse.ArgumentParser(description=_("Generate embroidery patterns for multiple texts at once."))

        self.arg_parser.add_argument('--notebook')

        self.arg_parser.add_argument('--text', type=str, default='', dest='text')
        self.arg_parser.add_argument('--separator', type=str, default='', dest='separator')

        self.arg_parser.add_argument('--font', type=str, default='', dest='font')
        self.arg_parser.add_argument('--scale', type=int, default=100, dest='scale')
        self.arg_parser.add_argument('--color-sort', type=str, default='off', dest='color_sort')
        self.arg_parser.add_argument('--trim', type=str, default='off', dest='trim')
        self.arg_parser.add_argument('--use-command-symbols', type=Boolean, default=False, dest='command_symbols')
        self.arg_parser.add_argument('--text-align', type=str, default='left', dest='text_align')
        self.arg_parser.add_argument('--letter_spacing', type=float, default=0, dest='letter_spacing')
        self.arg_parser.add_argument('--word_spacing', type=float, default=0, dest='word_spacing')
        self.arg_parser.add_argument('--line_height', type=float, default=0, dest='line_height')

        self.arg_parser.add_argument('--text-position', type=str, default='left', dest='text_position')

        self.arg_parser.add_argument('--file-formats', type=str, default='', dest='formats')

        self.elements = []

        # The svg_element should already be an inkex element (parsed with SVG_PARSER)
        # which has the .metadata property needed by InkStitchMetadata
        self.svg = svg_element
        self.document = etree.ElementTree(svg_element)

    def effect(self):
        pass

    def parse_arguments(self, args):
        self.options = self.arg_parser.parse_args(args)

    def get_elements(self):
        """Convert SVG nodes to inkstitch elements."""
        # Iterate all nodes in the document (no selection)
        nodes = iterate_nodes(self.document.getroot(), selection=None, troubleshoot=False)
        self.elements = nodes_to_elements(nodes)
        return bool(self.elements)

    def elements_to_stitch_groups(self, elements):
        """Convert inkstitch elements to stitch groups."""
        next_elements = [None]
        if len(elements) > 1:
            next_elements = elements[1:] + next_elements
        stitch_groups = []
        for element, next_element in zip(elements, next_elements):
            if stitch_groups:
                last_stitch_group = stitch_groups[-1]
            else:
                last_stitch_group = None

            stitch_groups.extend(element.embroider(last_stitch_group, next_element))

        return stitch_groups

    def get_inkstitch_metadata(self):
        """Get inkstitch metadata from the SVG."""
        return InkStitchMetadata(self.svg)

    def effect_new(self, args):
        """Run the effect and return embroidery patterns instead of writing to stdout."""
        self.parse_arguments(args)

        separator = self.options.separator
        if not separator:
            separator = '\n'
        text_input = self.options.text
        if not text_input:
            errormsg(_("Please specify a text"))
            return
        texts = text_input.replace('\\n', '\n').split(separator)

        if not self.options.font:
            errormsg(_("Please specify a font"))
            return
        # Lazy import to avoid circular dependency
        from ..lettering import get_font_by_name
        self.font = get_font_by_name(self.options.font, False)
        if self.font is None:
            errormsg(_("Please specify a valid font name."))
            errormsg(_("You can find a list with all font names on our website: https://inkstitch.org/fonts/font-library/"))
            return

        if not self.options.formats:
            errormsg(_("Please specify at least one output file format"))
            return
        available_formats = [file_format['extension'] for file_format in pystitch.supported_formats()] + ['svg']
        file_formats = self.options.formats.split(',')
        file_formats = [file_format.strip().lower() for file_format in file_formats if file_format.strip().lower() in available_formats]
        if not file_formats:
            errormsg(_("Please specify at least one file format supported by Ink/Stitch"))
            errormsg(_("You can find a list with all supported file formats our website: https://inkstitch.org/docs/file-formats/#writing"))
            return

        self.setup_trim()
        self.setup_text_align()
        self.setup_color_sort()
        self.setup_scale()

        # Generate and return embroidery patterns
        return self.generate_output_files(texts, file_formats)


    def setup_trim(self):
        self.trim = 0
        if self.options.trim == "line":
            self.trim = 1
        elif self.options.trim == "word":
            self.trim = 2
        elif self.options.trim == "glyph":
            self.trim = 3

    def setup_text_align(self):
        self.text_align = 0
        if self.options.text_align == "center":
            self.text_align = 1
        elif self.options.text_align == "right":
            self.text_align = 2
        elif self.options.text_align == "block":
            self.text_align = 3
        elif self.options.text_align == "letterspacing":
            self.text_align = 4

    def setup_color_sort(self):
        self.color_sort = 0
        if self.options.color_sort == "all":
            self.color_sort = 1
        elif self.options.color_sort == "line":
            self.color_sort = 2
        elif self.options.color_sort == "word":
            self.color_sort = 3

    def setup_scale(self):
        self.scale = self.options.scale / 100
        if self.scale < self.font.min_scale:
            self.scale = self.font.min_scale
        elif self.scale > self.font.max_scale:
            self.scale = self.font.max_scale

    def generate_output_files(self, texts, file_formats):
        """Generate embroidery patterns for the given texts and return them."""
        self.metadata = self.get_inkstitch_metadata()
        self.collapse_len = self.metadata['collapse_len_mm']
        self.min_stitch_len = self.metadata['min_stitch_len_mm']

        # The user can specify a path which can be used for the text along path method.
        # The path should be labeled as "batch lettering"
        text_positioning_path = self.svg.findone(".//*[@inkscape:label='batch lettering']")

        ret_vals = []
        for text in texts:
            if not text:
                continue
            stitch_plan, lettering_group = self.generate_stitch_plan(text, text_positioning_path)
            embroidery_pattern, settings = self.stitch_to_pes(stitch_plan, self.svg, settings={})
            ret_vals.append((embroidery_pattern, settings))

        return ret_vals

    def get_origin(self, svg, bounding_box):
        """Calculate the origin point from the bounding box center."""
        (minx, miny, maxx, maxy) = bounding_box
        bounding_box_center = [(maxx + minx) / 2, (maxy + miny) / 2]
        return Point(*bounding_box_center)

    def jump_to_stop_point(self, pattern, svg):
        # TODO: figure out how to remove stop_position global
        stop_position = global_command(svg, "stop_position")
        if stop_position:
            pattern.add_stitch_absolute(pystitch.JUMP, stop_position.point.x, stop_position.point.y)

    def get_command(self, stitch):
        if stitch.jump:
            return pystitch.JUMP
        elif stitch.trim:
            return pystitch.TRIM
        elif stitch.color_change:
            return pystitch.COLOR_CHANGE
        elif stitch.stop:
            return pystitch.STOP
        else:
            return pystitch.NEEDLE_AT
    def stitch_to_pes(self, stitch_plan, svg, settings={}):
        scale = 10 / PIXELS_PER_MM
        origin = self.get_origin(svg, stitch_plan.bounding_box)

        pattern = pystitch.EmbPattern()

        stitch = Stitch(0, 0)

        for color_block in stitch_plan:
            pattern.add_thread(color_block.color.pystitch_thread)

            for stitch in color_block:
                if stitch.stop:
                    self.jump_to_stop_point(pattern, svg)
                command = self.get_command(stitch)
                pattern.add_stitch_absolute(command, stitch.x, stitch.y)
        
        pattern.add_stitch_absolute(pystitch.END, stitch.x, stitch.y)
        settings.update({
            # correct for the origin
            "translate": -origin,

            # convert from pixels to millimeters
            # also multiply by 10 to get tenths of a millimeter as required by pystitch
            "scale": (scale, scale),

            # This forces a jump at the start of the design and after each trim,
            # even if we're close enough not to need one.
            "full_jump": True,

            # defaults to False in pystitch (see https://github.com/EmbroidePy/pyembroidery/issues/188)
            "trims": True,
        })

        return pattern, settings

    def generate_stitch_plan(self, text, text_positioning_path):

        self.settings = DotDict({
            "text": text,
            "text_align": self.text_align,
            "back_and_forth": True,
            "font": self.font.marked_custom_font_id,
            "scale": int(self.scale * 100),
            "trim_option": self.trim,
            "use_trim_symbols": self.options.command_symbols,
            "color_sort": self.color_sort,
            "letter_spacing": self.options.letter_spacing,
            "word_spacing": self.options.word_spacing,
            "line_height": self.options.line_height
        })

        lettering_group = Group()
        lettering_group.label = _("Ink/Stitch Lettering")
        lettering_group.set('inkstitch:lettering', json.dumps(self.settings))
        self.svg.append(lettering_group)
        lettering_group.set("transform", get_correction_transform(lettering_group, child=True))

        destination_group = Group()
        destination_group.label = f"{self.font.name} {_('scale')} {self.scale * 100}%"
        lettering_group.append(destination_group)

        text = self.font.render_text(
            text,
            destination_group,
            trim_option=self.trim,
            use_trim_symbols=self.options.command_symbols,
            color_sort=self.color_sort,
            text_align=self.text_align,
            letter_spacing=self.options.letter_spacing,
            word_spacing=self.options.word_spacing,
            line_height=self.options.line_height
        )

        destination_group.attrib['transform'] = f'scale({self.scale})'

        if text_positioning_path is not None:
            parent = text_positioning_path.getparent()
            index = parent.index(text_positioning_path)
            parent.insert(index, lettering_group)
            TextAlongPath(self.svg, lettering_group, text_positioning_path, self.options.text_position)
            text_positioning_path.delete()

        self.get_elements()
        stitch_groups = self.elements_to_stitch_groups(self.elements)
        stitch_plan = stitch_groups_to_stitch_plan(stitch_groups, collapse_len=self.collapse_len, min_stitch_len=self.min_stitch_len)
        ThreadCatalog().match_and_apply_palette(stitch_plan, self.get_inkstitch_metadata()['thread-palette'])
        return stitch_plan, lettering_group
