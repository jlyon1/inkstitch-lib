#!/usr/bin/env python3
"""
Simple CLI tool to convert text to embroidery files using Ink/Stitch fonts.
Usage: python batch_text_to_pes.py "Text" output.pes --font FontName --scale 100

Can also be imported as a library:
    from batch_text_to_pes import text_to_embroidery

    text_to_embroidery(
        text="Hello World",
        output_path="output.pes",
        font="CooperMarif",
        scale=100
    )
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


def text_to_embroidery(
    text,
    output_path,
    font='CooperMarif',
    scale=100,
    trim='off',
    color_sort='off',
    text_align='left',
    letter_spacing=0.0,
    word_spacing=0.0,
    line_height=0.0,
    use_command_symbols=False
):
    """
    Convert text to an embroidery file using Ink/Stitch fonts.

    This function can be imported and called from other Python scripts.

    Args:
        text (str): Text to embroider
        output_path (str): Output file path (.pes, .dst, .jef, etc.)
        font (str): Font name (default: 'CooperMarif')
        scale (int): Scale percentage (default: 100)
        trim (str): Trim option - 'off', 'line', 'word', 'glyph' (default: 'off')
        color_sort (str): Color sorting - 'off', 'all', 'line', 'word' (default: 'off')
        text_align (str): Text alignment - 'left', 'center', 'right', 'block', 'letterspacing' (default: 'left')
        letter_spacing (float): Letter spacing in mm (default: 0.0)
        word_spacing (float): Word spacing in mm (default: 0.0)
        line_height (float): Line height in mm (default: 0.0)
        use_command_symbols (bool): Use command symbols (default: False)

    Returns:
        str: Path to the created embroidery file

    Raises:
        ValueError: If output format is not supported or file cannot be created
        Exception: If embroidery generation fails

    Example:
        >>> from batch_text_to_pes import text_to_embroidery
        >>> output = text_to_embroidery(
        ...     text="Hello World",
        ...     output_path="output.pes",
        ...     font="Apex Lake",
        ...     scale=150
        ... )
        >>> print(f"Created: {output}")
    """
    # Determine output format from file extension
    output_format = os.path.splitext(output_path)[1][1:].lower()
    if not output_format:
        output_format = 'pes'
        output_path += '.pes'

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
            f'--text={text}',
            f'--font={font}',
            f'--scale={scale}',
            f'--file-formats={output_format}',
            f'--trim={trim}',
            f'--color-sort={color_sort}',
            f'--text-align={text_align}',
            f'--letter_spacing={letter_spacing}',
            f'--word_spacing={word_spacing}',
            f'--line_height={line_height}',
        ]
        if use_command_symbols:
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
            output_dir = os.path.dirname(output_path) or '.'

            files = [f for f in zip_file.namelist() if f.endswith(f'.{output_format}')]
            if not files:
                raise ValueError(f"No {output_format} file found in output")

            # Extract and rename to final output path
            zip_file.extract(files[0], output_dir)
            extracted = os.path.join(output_dir, files[0])

            if os.path.exists(output_path):
                os.remove(output_path)
            os.rename(extracted, output_path)

            return output_path

    finally:
        # Cleanup
        if os.path.exists(svg_file.name):
            os.remove(svg_file.name)
        if 'output_file' in locals() and os.path.exists(output_file.name):
            os.remove(output_file.name)


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

    try:
        output = text_to_embroidery(
            text=args.text,
            output_path=args.output,
            font=args.font,
            scale=args.scale,
            trim=args.trim,
            color_sort=args.color_sort,
            text_align=args.text_align,
            letter_spacing=args.letter_spacing,
            word_spacing=args.word_spacing,
            line_height=args.line_height,
            use_command_symbols=args.use_command_symbols
        )
        print(f"✓ Created {output}")
        return True
    except Exception as e:
        print(f"Error: {e}")
        return False


if __name__ == "__main__":
    try:
        success = main()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
