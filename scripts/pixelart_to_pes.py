#!/usr/bin/env python3
"""
Convert pixel art image to PES embroidery file.

Each pixel in the input image becomes a 1cm x 1cm filled square in embroidery.

Usage:
    python pixelart_to_pes.py pixelart.png -o output.pes
    python pixelart_to_pes.py pixelart.png -o output.pes --stitch-spacing 0.4
    python pixelart_to_pes.py pixelart.png -o output.pes --row-order zigzag
"""

import argparse
import sys
from collections import defaultdict
from pathlib import Path
from typing import List, Tuple, Dict, Set

import numpy as np
from PIL import Image

import pystitch


# Constants
MM_PER_PIXEL = 10  # Each pixel = 1cm = 10mm
UNITS_PER_MM = 10  # pystitch uses tenths of mm


def rgb_to_hex(rgb: Tuple[int, int, int]) -> str:
    """Convert RGB tuple to hex string."""
    return f"#{rgb[0]:02X}{rgb[1]:02X}{rgb[2]:02X}"


def hex_to_rgb(hex_color: str) -> Tuple[int, int, int]:
    """Convert hex color string to RGB tuple."""
    hex_color = hex_color.lstrip('#')
    return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))


def create_thread(color: Tuple[int, int, int], name: str = None) -> pystitch.EmbThread:
    """Create a pystitch thread from RGB color."""
    thread = pystitch.EmbThread()
    thread.set_color(color[0], color[1], color[2])
    thread.name = name or rgb_to_hex(color)
    return thread


def generate_pixel_fill_stitches(
    x: int,
    y: int,
    pixel_size_mm: float,
    stitch_spacing_mm: float,
    stitch_length_mm: float
) -> List[Tuple[float, float]]:
    """
    Generate fill stitches for a single pixel.

    Uses horizontal rows with alternating direction (zigzag pattern).

    Returns list of (x, y) coordinates in mm.
    """
    stitches = []

    # Pixel boundaries in mm
    x_start = x * pixel_size_mm
    y_start = y * pixel_size_mm
    x_end = x_start + pixel_size_mm
    y_end = y_start + pixel_size_mm

    # Small inset to avoid exact edge stitches
    inset = 0.2
    x_start += inset
    x_end -= inset
    y_start += inset
    y_end -= inset

    # Number of rows
    num_rows = int((y_end - y_start) / stitch_spacing_mm)
    if num_rows < 1:
        num_rows = 1

    actual_spacing = (y_end - y_start) / num_rows

    # Generate rows
    direction = 1  # 1 = left-to-right, -1 = right-to-left
    for row in range(num_rows + 1):
        row_y = y_start + row * actual_spacing
        if row_y > y_end:
            row_y = y_end

        # Determine stitch positions along this row
        if direction == 1:
            row_x_start = x_start
            row_x_end = x_end
        else:
            row_x_start = x_end
            row_x_end = x_start

        # Add stitches along the row
        num_stitches = max(2, int(abs(row_x_end - row_x_start) / stitch_length_mm) + 1)
        for i in range(num_stitches):
            t = i / (num_stitches - 1) if num_stitches > 1 else 0
            stitch_x = row_x_start + t * (row_x_end - row_x_start)
            stitches.append((stitch_x, row_y))

        direction *= -1  # Alternate direction

    return stitches


def find_connected_regions(
    pixels: Set[Tuple[int, int]]
) -> List[Set[Tuple[int, int]]]:
    """
    Find connected regions of same-colored pixels using flood fill.
    This helps minimize jumps by stitching connected areas together.
    """
    remaining = set(pixels)
    regions = []

    while remaining:
        # Start a new region
        start = remaining.pop()
        region = {start}
        queue = [start]

        while queue:
            current = queue.pop()
            # Check 4-connected neighbors
            for dx, dy in [(0, 1), (0, -1), (1, 0), (-1, 0)]:
                neighbor = (current[0] + dx, current[1] + dy)
                if neighbor in remaining:
                    remaining.remove(neighbor)
                    region.add(neighbor)
                    queue.append(neighbor)

        regions.append(region)

    return regions


def order_pixels_for_stitching(
    pixels: Set[Tuple[int, int]],
    row_order: str = 'zigzag'
) -> List[Tuple[int, int]]:
    """
    Order pixels for efficient stitching (minimize jumps).

    row_order: 'zigzag' (alternate row direction) or 'rows' (all left-to-right)
    """
    if not pixels:
        return []

    # Group by row
    rows: Dict[int, List[int]] = defaultdict(list)
    for x, y in pixels:
        rows[y].append(x)

    # Sort each row
    for y in rows:
        rows[y].sort()

    # Order rows
    sorted_rows = sorted(rows.keys())
    result = []

    for i, y in enumerate(sorted_rows):
        x_values = rows[y]
        if row_order == 'zigzag' and i % 2 == 1:
            x_values = reversed(x_values)
        for x in x_values:
            result.append((x, y))

    return result


def convert_pixelart_to_pes(
    input_path: Path,
    output_path: Path,
    stitch_spacing_mm: float = 0.4,
    stitch_length_mm: float = 2.5,
    pixel_size_mm: float = 10.0,
    row_order: str = 'zigzag',
    color_order: str = 'frequency'
) -> dict:
    """
    Convert pixel art image to PES embroidery file.

    Args:
        input_path: Path to pixel art PNG
        output_path: Path for output PES file
        stitch_spacing_mm: Space between stitch rows (default 0.4mm)
        stitch_length_mm: Maximum stitch length (default 2.5mm)
        pixel_size_mm: Size of each pixel in mm (default 10mm = 1cm)
        row_order: 'zigzag' or 'rows'
        color_order: 'frequency' (most common first) or 'luminance' (dark to light)

    Returns:
        dict with metadata about the conversion
    """
    # Load image
    image = Image.open(input_path)
    if image.mode == 'RGBA':
        # Remove fully transparent pixels by converting to RGB with white background
        background = Image.new('RGB', image.size, (255, 255, 255))
        background.paste(image, mask=image.split()[3])
        image = background
    elif image.mode != 'RGB':
        image = image.convert('RGB')

    img_array = np.array(image)
    height, width = img_array.shape[:2]

    # Group pixels by color
    color_pixels: Dict[Tuple[int, int, int], Set[Tuple[int, int]]] = defaultdict(set)
    for y in range(height):
        for x in range(width):
            color = tuple(img_array[y, x])
            color_pixels[color].add((x, y))

    # Order colors
    colors = list(color_pixels.keys())
    if color_order == 'frequency':
        colors.sort(key=lambda c: len(color_pixels[c]), reverse=True)
    elif color_order == 'luminance':
        # Dark to light
        colors.sort(key=lambda c: 0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2])

    # Create pattern
    pattern = pystitch.EmbPattern()

    total_stitches = 0
    color_stats = []

    for color in colors:
        pixels = color_pixels[color]

        # Create thread for this color
        thread = create_thread(color)
        pattern.add_thread(thread)

        # Find connected regions for efficient stitching
        regions = find_connected_regions(pixels)

        first_stitch_in_color = True

        for region in regions:
            # Order pixels within region
            ordered_pixels = order_pixels_for_stitching(region, row_order)

            first_in_region = True
            for px, py in ordered_pixels:
                # Generate fill stitches for this pixel
                fill_stitches = generate_pixel_fill_stitches(
                    px, py, pixel_size_mm, stitch_spacing_mm, stitch_length_mm
                )

                for i, (sx, sy) in enumerate(fill_stitches):
                    # Convert mm to tenths of mm for pystitch
                    x_units = sx * UNITS_PER_MM
                    y_units = sy * UNITS_PER_MM

                    if first_stitch_in_color and i == 0:
                        # First stitch of color - just position
                        pattern.add_stitch_absolute(pystitch.NEEDLE_AT, x_units, y_units)
                        first_stitch_in_color = False
                    elif first_in_region and i == 0:
                        # Jump to new region
                        pattern.add_stitch_absolute(pystitch.TRIM, x_units, y_units)
                        pattern.add_stitch_absolute(pystitch.JUMP, x_units, y_units)
                    else:
                        pattern.add_stitch_absolute(pystitch.NEEDLE_AT, x_units, y_units)

                    total_stitches += 1

                first_in_region = False

        # Add color change (except for last color)
        if color != colors[-1]:
            pattern.add_stitch_absolute(pystitch.COLOR_CHANGE, 0, 0)

        color_stats.append({
            'color': rgb_to_hex(color),
            'pixels': len(pixels),
            'regions': len(regions)
        })

    # End the pattern
    pattern.add_stitch_absolute(pystitch.END, 0, 0)

    # Write PES file
    settings = {
        'encode': True,
        'trims': True,
    }

    pystitch.write(pattern, str(output_path), settings)

    return {
        'image_size': (width, height),
        'embroidery_size_mm': (width * pixel_size_mm, height * pixel_size_mm),
        'embroidery_size_cm': (width * pixel_size_mm / 10, height * pixel_size_mm / 10),
        'total_colors': len(colors),
        'total_stitches': total_stitches,
        'color_stats': color_stats
    }


def main():
    parser = argparse.ArgumentParser(
        description='Convert pixel art to PES embroidery file. Each pixel becomes 1cm square.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s pixelart.png -o output.pes
  %(prog)s pixelart.png -o output.pes --stitch-spacing 0.3
  %(prog)s pixelart.png -o output.pes --pixel-size 5  # 5mm per pixel
        """
    )

    parser.add_argument('input', type=Path, help='Input pixel art image')
    parser.add_argument('-o', '--output', type=Path, required=True, help='Output PES file')

    parser.add_argument(
        '--stitch-spacing', '-s',
        type=float,
        default=0.4,
        help='Space between stitch rows in mm (default: 0.4)'
    )
    parser.add_argument(
        '--stitch-length', '-l',
        type=float,
        default=2.5,
        help='Maximum stitch length in mm (default: 2.5)'
    )
    parser.add_argument(
        '--pixel-size', '-p',
        type=float,
        default=10.0,
        help='Size of each pixel in mm (default: 10.0 = 1cm)'
    )
    parser.add_argument(
        '--row-order', '-r',
        choices=['zigzag', 'rows'],
        default='zigzag',
        help='Stitch row ordering (default: zigzag)'
    )
    parser.add_argument(
        '--color-order', '-c',
        choices=['frequency', 'luminance'],
        default='frequency',
        help='Order to stitch colors: frequency (most common first) or luminance (dark to light)'
    )

    args = parser.parse_args()

    if not args.input.exists():
        print(f"Error: Input file not found: {args.input}", file=sys.stderr)
        sys.exit(1)

    print(f"Converting {args.input} to embroidery...")
    print(f"  Pixel size: {args.pixel_size}mm ({args.pixel_size/10}cm)")
    print(f"  Stitch spacing: {args.stitch_spacing}mm")
    print(f"  Stitch length: {args.stitch_length}mm")
    print(f"  Row order: {args.row_order}")
    print(f"  Color order: {args.color_order}")

    try:
        result = convert_pixelart_to_pes(
            args.input,
            args.output,
            stitch_spacing_mm=args.stitch_spacing,
            stitch_length_mm=args.stitch_length,
            pixel_size_mm=args.pixel_size,
            row_order=args.row_order,
            color_order=args.color_order
        )

        print(f"\nSuccess! Output saved to {args.output}")
        print(f"  Image size: {result['image_size'][0]}x{result['image_size'][1]} pixels")
        print(f"  Embroidery size: {result['embroidery_size_cm'][0]}cm x {result['embroidery_size_cm'][1]}cm")
        print(f"  Total colors: {result['total_colors']}")
        print(f"  Total stitches: {result['total_stitches']}")
        print(f"\nColor breakdown:")
        for stat in result['color_stats']:
            print(f"  {stat['color']}: {stat['pixels']} pixels, {stat['regions']} regions")

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
