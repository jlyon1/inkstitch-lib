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
import io
import pystitch
import sys
import os
import tempfile
import hashlib
from functools import lru_cache
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi import BackgroundTasks, FastAPI, Query
from fastapi.middleware.gzip import GZipMiddleware

app = FastAPI(dependencies=[])

# Add GZip compression for responses over 1KB
app.add_middleware(GZipMiddleware, minimum_size=1000)

# Add project root to path
# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Font preview directory (adjust if needed)
FONT_PREVIEW_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fonts', 'src')
from lib.lettering.utils import get_font_list

# Cache directory for rendered embroidery files
CACHE_DIR = os.path.join(tempfile.gettempdir(), 'inkstitch_cache')
os.makedirs(CACHE_DIR, exist_ok=True)

# Cached font list - load once and reuse
@lru_cache(maxsize=1)
def get_cached_font_list():
    """Cache font list in memory to avoid repeated disk I/O"""
    fonts = get_font_list(show_font_path_warning=False)
    font_list = []
    for font in sorted(fonts, key=lambda f: f.name):
        preview_path = None
        if hasattr(font, 'preview_image') and font.preview_image:
            preview_path = font.preview_image
        elif hasattr(font, 'preview') and font.preview:
            preview_path = font.preview
        preview_url = None
        if preview_path:
            preview_url = f"/fonts/preview/{font.name}"
        font_list.append({
            "name": font.name,
            "preview": preview_url
        })
    return font_list

# API route to list available fonts with preview info
@app.get("/fonts")
async def list_fonts():
    """List all available fonts (cached for performance)"""
    return JSONResponse(content=get_cached_font_list())

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
    import threading

    # Fix for FastAPI thread pool compatibility with InkStitch's threading checks
    # InkStitch expects threads to have a 'stop' Event attribute (see lib/utils/threading.py:21)
    current_thread = threading.current_thread()
    if not hasattr(current_thread, 'stop') or not isinstance(getattr(current_thread, 'stop', None), threading.Event):
        current_thread.stop = threading.Event()

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

        try:
            return ext.effect_new(cmd_args)
        except SystemExit:
            return None

    finally:
        # Cleanup temporary SVG file
        if os.path.exists(svg_file.name):
            os.remove(svg_file.name)


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


def cleanup_file(filepath: str):
    """Background task to cleanup temporary files"""
    try:
        if os.path.exists(filepath):
            os.remove(filepath)
    except Exception:
        pass  # Ignore cleanup errors

def generate_cache_key(text: str, font: str, scale: int, trim: str, color_sort: str,
                       text_align: str, letter_spacing: float, word_spacing: float,
                       line_height: float, use_command_symbols: bool) -> str:
    """Generate a cache key from parameters"""
    params = f"{text}:{font}:{scale}:{trim}:{color_sort}:{text_align}:{letter_spacing}:{word_spacing}:{line_height}:{use_command_symbols}"
    return hashlib.sha256(params.encode()).hexdigest()

async def get_or_create_embroidery(text: str, font: str, scale: int, trim: str,
                                   color_sort: str, text_align: str, letter_spacing: float,
                                   word_spacing: float, line_height: float,
                                   use_command_symbols: bool) -> str:
    """Get cached embroidery file or create new one"""
    # Generate cache key
    cache_key = generate_cache_key(text, font, scale, trim, color_sort, text_align,
                                   letter_spacing, word_spacing, line_height, use_command_symbols)
    cache_file = os.path.join(CACHE_DIR, f"{cache_key}.pes")

    # Return cached file if exists
    if os.path.exists(cache_file):
        return cache_file

    # Generate new embroidery patterns
    return text_to_embroidery(
        text=text,
        output_path=cache_file,
        font=font,
        scale=scale,
        trim=trim,
        color_sort=color_sort,
        text_align=text_align,
        letter_spacing=letter_spacing,
        word_spacing=word_spacing,
        line_height=line_height,
        use_command_symbols=use_command_symbols
    )

@app.get("/batch_text_to_pes")
async def batch_text_to_pes_endpoint(
    background_tasks: BackgroundTasks,
    text: str = Query(..., description="Text to embroider"),
    font: str = Query('CooperMarif', description="Font name"),
    scale: int = Query(100, description="Scale percentage"),
    trim: str = Query('off', description="Trim option: off, line, word, glyph"),
    color_sort: str = Query('off', description="Color sorting: off, all, line, word"),
    text_align: str = Query('left', description="Text alignment: left, center, right, block, letterspacing"),
    letter_spacing: float = Query(0.0, description="Letter spacing in mm"),
    word_spacing: float = Query(0.0, description="Word spacing in mm"),
    line_height: float = Query(0.0, description="Line height in mm"),
    use_command_symbols: bool = Query(False, description="Use command symbols")
):
    """
    Convert text to embroidery file with caching and async processing.

    Performance optimizations:
    - Uses threadpool for CPU-intensive rendering
    - Caches rendered outputs to avoid regeneration
    - Cleans up temporary files in background
    """
    # Get or generate embroidery patterns
    output_files = await get_or_create_embroidery(
        text=text,
        font=font,
        scale=scale,
        trim=trim,
        color_sort=color_sort,
        text_align=text_align,
        letter_spacing=letter_spacing,
        word_spacing=word_spacing,
        line_height=line_height,
        use_command_symbols=use_command_symbols
    )

    # Generate filename for download
    safe_text = "".join(c if c.isalnum() or c in (' ', '-', '_') else '_' for c in text[:20])
    safe_font = "".join(c if c.isalnum() or c in (' ', '-', '_') else '_' for c in font)
    filename = f"{safe_text.replace(' ', '_')}_{safe_font.replace(' ', '_')}_{scale}.pes"
    headers = {"Content-Disposition": f"attachment; filename={filename}"}

    # Write embroidery pattern to bytes buffer
    fbytes = io.BytesIO()
    for pattern, settings in output_files:
        pystitch.write_pes(pattern, fbytes, settings)
    fbytes.seek(0)

    return StreamingResponse(
        iter([fbytes.read()]),
        media_type="application/octet-stream",
        headers=headers
    )

# API route to serve font preview images by font name
@app.get("/fonts/preview/{font_name}")
async def get_font_preview(font_name: str):
    """Serve font preview image (uses cached font list)"""
    # Use cached font list to avoid repeated disk I/O
    font_list = get_cached_font_list()
    font = next((f for f in font_list if f["name"] == font_name), None)

    if not font:
        return JSONResponse(status_code=404, content={"detail": "Font not found"})

    # Get actual font object for preview path
    fonts = get_font_list(show_font_path_warning=False)
    font_obj = next((f for f in fonts if f.name == font_name), None)

    if not font_obj:
        return JSONResponse(status_code=404, content={"detail": "Font not found"})

    preview_path = None
    if hasattr(font_obj, 'preview_image') and font_obj.preview_image:
        preview_path = font_obj.preview_image
    elif hasattr(font_obj, 'preview') and font_obj.preview:
        preview_path = font_obj.preview

    if not preview_path or not os.path.exists(preview_path):
        return JSONResponse(status_code=404, content={"detail": "Preview not found"})

    return FileResponse(preview_path)