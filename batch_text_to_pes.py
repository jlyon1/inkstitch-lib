#!/usr/bin/env python3
"""
Simple CLI tool to convert text to embroidery files using Ink/Stitch fonts.
Usage: python batch_text_to_pes.py "Text" output.pes --font FontName --scale 100
"""

import sys
import os
import tempfile
from zipfile import ZipFile

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lxml import etree
from lib.extensions.batch_lettering import BatchLettering


def create_minimal_svg():
    """Create a minimal SVG document for the extension."""
    svg = etree.Element(
        "{http://www.w3.org/2000/svg}svg",
        nsmap={
            None: "http://www.w3.org/2000/svg",
            "inkscape": "http://www.inkscape.org/namespaces/inkscape",
            "inkstitch": "http://inkstitch.org/namespace",
        },
        attrib={
            "width": "200mm",
            "height": "200mm",
            "viewBox": "-100 -100 400 400",
        }
    )

    # Add required metadata
    defs = etree.SubElement(svg, "{http://www.w3.org/2000/svg}defs")
    metadata = etree.SubElement(svg, "{http://www.w3.org/2000/svg}metadata")
    inkstitch_metadata = etree.SubElement(
        metadata,
        "{http://inkstitch.org/namespace}inkstitch-metadata"
    )

    # Add version to prevent popup
    version_elem = etree.SubElement(inkstitch_metadata, "{http://inkstitch.org/namespace}inkstitch-version")
    version_elem.text = "3.0"

    # Add default settings
    settings = {
        'collapse_len_mm': '3.0',
        'min_stitch_len_mm': '0.2',
        'thread-palette': ''
    }
    for key, value in settings.items():
        elem = etree.SubElement(inkstitch_metadata, f"{{http://inkstitch.org/namespace}}{key}")
        elem.text = value

    return svg


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description='Convert text to embroidery files using Ink/Stitch fonts',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  %(prog)s "Hello World" output.pes
  %(prog)s "Text" out.dst --font "Apex Lake" --scale 150
  %(prog)s "Custom" out.pes --font "Abécédaire AGS" --letter-spacing 2.0 --trim line
  %(prog)s "Centered" out.pes --text-align center --line-height 5.0
        ''')

    parser.add_argument('text', help='Text to embroider')
    parser.add_argument('output', help='Output file path (.pes, .dst, .jef, etc.)')
    parser.add_argument('--font', default='CooperMarif', help='Font name (default: CooperMarif)')
    parser.add_argument('--scale', type=int, default=100, help='Scale percentage (default: 100)')
    parser.add_argument('--trim', choices=['off', 'line', 'word', 'glyph'], default='off',
                        help='Trim/cut thread option (default: off)')
    parser.add_argument('--color-sort', choices=['off', 'all', 'line', 'word'], default='off',
                        help='Sort stitches by color (default: off)')
    parser.add_argument('--text-align', choices=['left', 'center', 'right', 'block', 'letterspacing'],
                        default='left', help='Text alignment (default: left)')
    parser.add_argument('--letter-spacing', type=float, default=0.0,
                        help='Letter spacing in mm (default: 0.0)')
    parser.add_argument('--word-spacing', type=float, default=0.0,
                        help='Word spacing in mm (default: 0.0)')
    parser.add_argument('--line-height', type=float, default=0.0,
                        help='Line height in mm (default: 0.0)')
    parser.add_argument('--use-command-symbols', action='store_true',
                        help='Use command symbols for trims/stops')

    args = parser.parse_args()

    # Determine output format from file extension
    output_format = os.path.splitext(args.output)[1][1:].lower()
    if not output_format:
        output_format = 'pes'
        args.output += '.pes'

    # Create temporary SVG file
    svg = create_minimal_svg()
    svg_file = tempfile.NamedTemporaryFile(mode='w', suffix='.svg', delete=False, encoding='utf-8')
    svg_file.write(etree.tostring(svg, encoding='unicode'))
    svg_file.close()

    try:
        # Create BatchLettering instance
        ext = BatchLettering()

        # Set up arguments
        cmd_args = [
            svg_file.name,
            f'--text={args.text}',
            f'--font={args.font}',
            f'--scale={args.scale}',
            f'--file-formats={output_format}',
            f'--trim={args.trim}',
            f'--color-sort={args.color_sort}',
            f'--text-align={args.text_align}',
            f'--letter_spacing={args.letter_spacing}',
            f'--word_spacing={args.word_spacing}',
            f'--line_height={args.line_height}',
        ]
        if args.use_command_symbols:
            cmd_args.append('--use-command-symbols=true')

        # Redirect stdout to capture zip output
        output_file = tempfile.NamedTemporaryFile(mode='wb', suffix='.zip', delete=False)
        original_stdout = sys.stdout

        class StdoutWrapper:
            def __init__(self, file):
                self.buffer = file
            def write(self, data):
                if isinstance(data, str):
                    data = data.encode('utf-8')
                self.buffer.write(data)
            def flush(self):
                self.buffer.flush()

        sys.stdout = StdoutWrapper(output_file)

        try:
            ext.run(cmd_args)
        except SystemExit:
            pass
        finally:
            sys.stdout = original_stdout
            output_file.close()

        # Extract file from the zip
        with ZipFile(output_file.name, 'r') as zip_file:
            output_dir = os.path.dirname(args.output) or '.'

            files = [f for f in zip_file.namelist() if f.endswith(f'.{output_format}')]
            if not files:
                print(f"Error: No {output_format} file found in output")
                return False

            # Extract and rename to final output path
            zip_file.extract(files[0], output_dir)
            extracted = os.path.join(output_dir, files[0])

            if os.path.exists(args.output):
                os.remove(args.output)
            os.rename(extracted, args.output)

            print(f"✓ Created {args.output}")
            return True

    finally:
        # Cleanup
        if os.path.exists(svg_file.name):
            os.remove(svg_file.name)
        if 'output_file' in locals() and os.path.exists(output_file.name):
            os.remove(output_file.name)


if __name__ == "__main__":
    try:
        success = main()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
