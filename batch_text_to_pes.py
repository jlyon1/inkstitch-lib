#!/usr/bin/env python3
"""
Wrapper for BatchLettering to render text to embroidery files.
Usage: python batch_text_to_pes.py "Text" output.pes [font] [scale]
"""

import sys
import os
import tempfile
from zipfile import ZipFile

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lxml import etree
import pystitch
from lib.extensions.batch_lettering import BatchLettering


def measure_embroidery_width(embroidery_file):
    """Measure the actual width of an embroidery file in mm."""
    try:
        pattern = pystitch.read(embroidery_file)
        if pattern and pattern.stitches:
            # Stitches are [x, y, flags] lists in tenths of mm
            x_coords = [s[0] for s in pattern.stitches if len(s) >= 2]
            if x_coords:
                min_x = min(x_coords)
                max_x = max(x_coords)
                # Convert from tenths of mm to mm
                width_mm = (max_x - min_x) / 10.0
                return width_mm
    except Exception as e:
        print(f"Warning: Could not measure embroidery width: {e}")
        import traceback
        traceback.print_exc()
    return None


def render_and_measure(svg_path, text, font_name, args, output_format):
    """Render text at 100% scale and measure the actual width."""
    import tempfile

    # Create temporary output
    temp_output = tempfile.NamedTemporaryFile(suffix=f'.{output_format}', delete=False)
    temp_output.close()

    try:
        ext = BatchLettering()
        cmd_args = [
            svg_path,
            f'--text={text}',
            f'--font={font_name}',
            '--scale=100',
            f'--file-formats={output_format}',
            f'--trim={args.trim}',
            f'--color-sort={args.color_sort}',
            f'--text-align={args.text_align}',
            f'--letter_spacing={args.letter_spacing}',
            f'--word_spacing={args.word_spacing}',
            f'--line_height={args.line_height}',
        ]

        # Redirect stdout
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

        # Extract and measure
        with ZipFile(output_file.name, 'r') as zip_file:
            files = [f for f in zip_file.namelist() if f.endswith(f'.{output_format}')]
            if files:
                zip_file.extract(files[0], os.path.dirname(temp_output.name))
                extracted = os.path.join(os.path.dirname(temp_output.name), files[0])
                width = measure_embroidery_width(extracted)
                os.remove(extracted)
                os.remove(output_file.name)
                return width
    except Exception as e:
        print(f"Warning: Measurement render failed: {e}")
    finally:
        if os.path.exists(temp_output.name):
            os.remove(temp_output.name)

    return None


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
            "width": "100mm",
            "height": "100mm",
            "viewBox": "0 0 100 100",
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
    version_elem.text = "3.0"  # Current Ink/Stitch version

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
    parser.add_argument('--scale', type=int, default=100, help='Scale percentage (default: 100, overridden by --target-width)')
    parser.add_argument('--target-width', type=float, help='Target width in mm (auto-calculates scale). Use with units: --target-width-inches for inches')
    parser.add_argument('--target-width-inches', type=float, help='Target width in inches (25.4mm per inch)')
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

    text = args.text
    output_path = args.output
    font_name = args.font
    scale = args.scale

    # Handle target width
    target_width_mm = None
    if args.target_width_inches:
        target_width_mm = args.target_width_inches * 25.4  # Convert inches to mm
    elif args.target_width:
        target_width_mm = args.target_width

    if target_width_mm:
        # We'll render once at 100% scale to measure actual width, then adjust
        print(f"Calculating scale for target width: {target_width_mm:.1f}mm ({target_width_mm/25.4:.2f} inches)")

        # Get font scale limits
        from lib.lettering.utils import get_font_by_name as get_font_info
        font_obj = get_font_info(font_name, False)
        if font_obj:
            font_min_scale = int(font_obj.min_scale * 100)
            font_max_scale = int(font_obj.max_scale * 100)
            print(f"Font '{font_name}' scale limits: {font_min_scale}-{font_max_scale}%")
        else:
            font_min_scale = 10
            font_max_scale = 300

        scale = 100  # Start with 100% for measurement

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
        # If we need to calculate scale based on target width, render twice
        if target_width_mm and scale == 100:
            # First render at 100% to measure
            actual_width = render_and_measure(svg_file.name, text, font_name, args, output_format)
            if actual_width and actual_width > 0:
                # Calculate correct scale
                calculated_scale = int((target_width_mm / actual_width) * 100)
                print(f"Measured width at 100% scale: {actual_width:.1f}mm ({actual_width/25.4:.2f} inches)")
                print(f"Calculated scale: {calculated_scale}%")

                # Check if within font limits
                if calculated_scale < font_min_scale:
                    scale = font_min_scale
                    achievable_width = actual_width * (font_min_scale / 100.0)
                    print(f"⚠ WARNING: Scale {calculated_scale}% is below font minimum of {font_min_scale}%")
                    print(f"  Using minimum scale {font_min_scale}%, which will produce {achievable_width:.1f}mm ({achievable_width/25.4:.2f} inches)")
                    print(f"  Consider choosing a smaller font or adjusting your target width")
                elif calculated_scale > font_max_scale:
                    scale = font_max_scale
                    achievable_width = actual_width * (font_max_scale / 100.0)
                    print(f"⚠ WARNING: Scale {calculated_scale}% exceeds font maximum of {font_max_scale}%")
                    print(f"  Using maximum scale {font_max_scale}%, which will produce {achievable_width:.1f}mm ({achievable_width/25.4:.2f} inches)")
                    print(f"  Consider choosing a larger font or adjusting your target width")
                else:
                    scale = calculated_scale
                    print(f"✓ Using scale: {scale}%")
            else:
                print("Warning: Could not measure width, using 100% scale")

        # Create BatchLettering instance
        ext = BatchLettering()

        # Set up arguments
        cmd_args = [
            svg_file.name,
            f'--text={text}',
            f'--font={font_name}',
            f'--scale={scale}',
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

        # Create a wrapper that has a 'buffer' attribute
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
            # Run the extension
            ext.run(cmd_args)
        except SystemExit:
            # BatchLettering calls sys.exit(0), which is expected
            pass
        finally:
            sys.stdout = original_stdout
            output_file.close()

        # Extract the embroidery file from the zip
        with ZipFile(output_file.name, 'r') as zip_file:
            # Get the first file with the correct extension
            files = [f for f in zip_file.namelist() if f.endswith(f'.{output_format}')]
            if files:
                zip_file.extract(files[0], os.path.dirname(output_path) or '.')
                # Rename to desired output name
                extracted = os.path.join(os.path.dirname(output_path) or '.', files[0])
                if os.path.exists(output_path):
                    os.remove(output_path)
                os.rename(extracted, output_path)

                # Report final dimensions
                final_width = measure_embroidery_width(output_path)
                if final_width:
                    print(f"✓ Created {output_path}")
                    print(f"  Final width: {final_width:.1f}mm ({final_width/25.4:.2f} inches)")
                else:
                    print(f"✓ Created {output_path}")
                return True
            else:
                print(f"Error: No {output_format} file found in output")
                return False

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
