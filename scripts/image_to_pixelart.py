#!/usr/bin/env python3
"""
Convert an image to pixel art with a limited color palette.

Each output pixel represents 1cm in embroidery (at 16x16 source pixels per output pixel).

Usage:
    python image_to_pixelart.py input.png -o output.png --colors "#FF0000,#00FF00,#0000FF,#FFFFFF,#000000"
    python image_to_pixelart.py input.png -o output.png --palette-file palette.txt
    python image_to_pixelart.py input.png -o output.png --colors "#FF0000,#00FF00" --dither
"""

import argparse
import sys
from pathlib import Path
from typing import List, Tuple

import numpy as np
from PIL import Image


def hex_to_rgb(hex_color: str) -> Tuple[int, int, int]:
    """Convert hex color string to RGB tuple."""
    hex_color = hex_color.lstrip('#')
    if len(hex_color) != 6:
        raise ValueError(f"Invalid hex color: {hex_color}")
    return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))


def rgb_to_hex(rgb: Tuple[int, int, int]) -> str:
    """Convert RGB tuple to hex string."""
    return f"#{rgb[0]:02X}{rgb[1]:02X}{rgb[2]:02X}"


def parse_colors(colors_str: str) -> List[Tuple[int, int, int]]:
    """Parse comma-separated hex colors."""
    colors = []
    for c in colors_str.split(','):
        c = c.strip()
        if c:
            colors.append(hex_to_rgb(c))
    return colors


def load_palette_file(path: Path) -> List[Tuple[int, int, int]]:
    """Load colors from a file (one hex color per line)."""
    colors = []
    with open(path, 'r') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#'):  # Allow comments with #
                # But also handle hex colors starting with #
                if line.startswith('//'):
                    continue
                colors.append(hex_to_rgb(line))
    return colors


def color_distance(c1: np.ndarray, c2: np.ndarray) -> float:
    """Calculate perceptual color distance (weighted Euclidean in RGB)."""
    # Weighted RGB distance - human eye is more sensitive to green
    weights = np.array([0.299, 0.587, 0.114])
    diff = (c1.astype(float) - c2.astype(float)) * weights
    return np.sqrt(np.sum(diff ** 2))


def find_nearest_color(pixel: np.ndarray, palette: np.ndarray) -> int:
    """Find the index of the nearest palette color to the given pixel."""
    min_dist = float('inf')
    min_idx = 0
    for i, color in enumerate(palette):
        dist = color_distance(pixel, color)
        if dist < min_dist:
            min_dist = dist
            min_idx = i
    return min_idx


def quantize_simple(image: np.ndarray, palette: np.ndarray) -> np.ndarray:
    """Simple nearest-color quantization without dithering."""
    h, w = image.shape[:2]
    output = np.zeros_like(image)

    for y in range(h):
        for x in range(w):
            idx = find_nearest_color(image[y, x], palette)
            output[y, x] = palette[idx]

    return output


def quantize_floyd_steinberg(image: np.ndarray, palette: np.ndarray) -> np.ndarray:
    """Floyd-Steinberg dithering for better gradient representation."""
    h, w = image.shape[:2]
    # Work with float to handle error diffusion
    work = image.astype(np.float32).copy()
    output = np.zeros_like(image)

    for y in range(h):
        for x in range(w):
            old_pixel = work[y, x].copy()
            idx = find_nearest_color(old_pixel.astype(np.uint8), palette)
            new_pixel = palette[idx].astype(np.float32)
            output[y, x] = palette[idx]

            # Calculate quantization error
            error = old_pixel - new_pixel

            # Distribute error to neighboring pixels (Floyd-Steinberg pattern)
            if x + 1 < w:
                work[y, x + 1] += error * 7 / 16
            if y + 1 < h:
                if x > 0:
                    work[y + 1, x - 1] += error * 3 / 16
                work[y + 1, x] += error * 5 / 16
                if x + 1 < w:
                    work[y + 1, x + 1] += error * 1 / 16

    return output


def quantize_ordered(image: np.ndarray, palette: np.ndarray, matrix_size: int = 4) -> np.ndarray:
    """Ordered (Bayer) dithering for a retro pixel art look."""
    # Bayer matrices
    bayer_matrices = {
        2: np.array([[0, 2], [3, 1]]) / 4,
        4: np.array([
            [0, 8, 2, 10],
            [12, 4, 14, 6],
            [3, 11, 1, 9],
            [15, 7, 13, 5]
        ]) / 16,
        8: np.array([
            [0, 32, 8, 40, 2, 34, 10, 42],
            [48, 16, 56, 24, 50, 18, 58, 26],
            [12, 44, 4, 36, 14, 46, 6, 38],
            [60, 28, 52, 20, 62, 30, 54, 22],
            [3, 35, 11, 43, 1, 33, 9, 41],
            [51, 19, 59, 27, 49, 17, 57, 25],
            [15, 47, 7, 39, 13, 45, 5, 37],
            [63, 31, 55, 23, 61, 29, 53, 21]
        ]) / 64
    }

    if matrix_size not in bayer_matrices:
        matrix_size = 4

    bayer = bayer_matrices[matrix_size]
    h, w = image.shape[:2]
    output = np.zeros_like(image)

    # Threshold adjustment range (higher = more dithering effect)
    threshold_range = 64

    for y in range(h):
        for x in range(w):
            # Get threshold from Bayer matrix
            threshold = (bayer[y % matrix_size, x % matrix_size] - 0.5) * threshold_range

            # Adjust pixel with threshold
            adjusted = image[y, x].astype(np.float32) + threshold
            adjusted = np.clip(adjusted, 0, 255).astype(np.uint8)

            idx = find_nearest_color(adjusted, palette)
            output[y, x] = palette[idx]

    return output


def downscale_image(image: Image.Image, block_size: int) -> Image.Image:
    """Downscale image by averaging blocks of pixels."""
    # Convert to numpy for processing
    img_array = np.array(image)

    h, w = img_array.shape[:2]
    new_h = h // block_size
    new_w = w // block_size

    if new_h == 0 or new_w == 0:
        raise ValueError(f"Image too small for block size {block_size}. "
                        f"Image: {w}x{h}, need at least {block_size}x{block_size}")

    # Crop to exact multiple of block_size
    cropped = img_array[:new_h * block_size, :new_w * block_size]

    # Reshape and average
    if len(img_array.shape) == 3:
        channels = img_array.shape[2]
        reshaped = cropped.reshape(new_h, block_size, new_w, block_size, channels)
        downscaled = reshaped.mean(axis=(1, 3)).astype(np.uint8)
    else:
        reshaped = cropped.reshape(new_h, block_size, new_w, block_size)
        downscaled = reshaped.mean(axis=(1, 3)).astype(np.uint8)

    return Image.fromarray(downscaled)


def convert_to_pixelart(
    input_path: Path,
    output_path: Path,
    palette: List[Tuple[int, int, int]],
    block_size: int = 16,
    dither_mode: str = 'none',
    upscale: int = 1
) -> dict:
    """
    Convert an image to pixel art.

    Args:
        input_path: Path to input image
        output_path: Path to output image
        palette: List of RGB color tuples
        block_size: Source pixels per output pixel (default 16)
        dither_mode: 'none', 'floyd-steinberg', or 'ordered'
        upscale: Factor to upscale output for visibility (default 1)

    Returns:
        dict with metadata about the conversion
    """
    # Load and convert to RGB
    image = Image.open(input_path)
    if image.mode == 'RGBA':
        # Handle transparency by compositing on white background
        background = Image.new('RGB', image.size, (255, 255, 255))
        background.paste(image, mask=image.split()[3])
        image = background
    elif image.mode != 'RGB':
        image = image.convert('RGB')

    original_size = image.size

    # Downscale
    pixelated = downscale_image(image, block_size)
    pixel_size = pixelated.size

    # Convert palette to numpy array
    palette_array = np.array(palette, dtype=np.uint8)
    pixel_array = np.array(pixelated)

    # Quantize to palette
    if dither_mode == 'floyd-steinberg':
        quantized = quantize_floyd_steinberg(pixel_array, palette_array)
    elif dither_mode == 'ordered':
        quantized = quantize_ordered(pixel_array, palette_array)
    else:
        quantized = quantize_simple(pixel_array, palette_array)

    result = Image.fromarray(quantized)

    # Upscale for visibility if requested
    if upscale > 1:
        result = result.resize(
            (result.width * upscale, result.height * upscale),
            Image.Resampling.NEAREST
        )

    # Save
    result.save(output_path)

    # Count colors used
    colors_used = set()
    for y in range(quantized.shape[0]):
        for x in range(quantized.shape[1]):
            colors_used.add(tuple(quantized[y, x]))

    return {
        'original_size': original_size,
        'pixel_size': pixel_size,
        'output_size': result.size,
        'colors_used': [rgb_to_hex(c) for c in sorted(colors_used)],
        'embroidery_size_cm': (pixel_size[0], pixel_size[1])
    }


# Default embroidery thread palette (common colors)
DEFAULT_PALETTE = [
    "#FFFFFF",  # White
    "#000000",  # Black
    "#FF0000",  # Red
    "#00FF00",  # Green
    "#0000FF",  # Blue
    "#FFFF00",  # Yellow
    "#FF00FF",  # Magenta
    "#00FFFF",  # Cyan
    "#FFA500",  # Orange
    "#800080",  # Purple
    "#FFC0CB",  # Pink
    "#A52A2A",  # Brown
    "#808080",  # Gray
    "#FFD700",  # Gold
    "#000080",  # Navy
    "#008000",  # Dark Green
]


def main():
    parser = argparse.ArgumentParser(
        description='Convert an image to pixel art with a limited color palette.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s input.png -o output.png --colors "#FF0000,#00FF00,#0000FF"
  %(prog)s input.png -o output.png --palette-file palette.txt --dither floyd-steinberg
  %(prog)s input.png -o output.png --block-size 8 --upscale 10
        """
    )

    parser.add_argument('input', type=Path, help='Input image file')
    parser.add_argument('-o', '--output', type=Path, required=True, help='Output image file')

    color_group = parser.add_mutually_exclusive_group()
    color_group.add_argument(
        '--colors', '-c',
        type=str,
        help='Comma-separated hex colors (e.g., "#FF0000,#00FF00,#0000FF")'
    )
    color_group.add_argument(
        '--palette-file', '-p',
        type=Path,
        help='File with hex colors, one per line'
    )

    parser.add_argument(
        '--block-size', '-b',
        type=int,
        default=16,
        help='Source pixels per output pixel (default: 16)'
    )
    parser.add_argument(
        '--dither', '-d',
        choices=['none', 'floyd-steinberg', 'ordered'],
        default='none',
        help='Dithering algorithm (default: none)'
    )
    parser.add_argument(
        '--upscale', '-u',
        type=int,
        default=1,
        help='Upscale output by this factor for visibility (default: 1)'
    )
    parser.add_argument(
        '--list-default-palette',
        action='store_true',
        help='Print the default color palette and exit'
    )

    args = parser.parse_args()

    if args.list_default_palette:
        print("Default palette:")
        for color in DEFAULT_PALETTE:
            print(f"  {color}")
        sys.exit(0)

    # Load palette
    if args.colors:
        palette = parse_colors(args.colors)
    elif args.palette_file:
        palette = load_palette_file(args.palette_file)
    else:
        palette = [hex_to_rgb(c) for c in DEFAULT_PALETTE]

    if len(palette) < 2:
        print("Error: Palette must have at least 2 colors", file=sys.stderr)
        sys.exit(1)

    if not args.input.exists():
        print(f"Error: Input file not found: {args.input}", file=sys.stderr)
        sys.exit(1)

    print(f"Converting {args.input} to pixel art...")
    print(f"  Block size: {args.block_size}x{args.block_size} pixels")
    print(f"  Palette: {len(palette)} colors")
    print(f"  Dithering: {args.dither}")

    try:
        result = convert_to_pixelart(
            args.input,
            args.output,
            palette,
            block_size=args.block_size,
            dither_mode=args.dither,
            upscale=args.upscale
        )

        print(f"\nSuccess! Output saved to {args.output}")
        print(f"  Original size: {result['original_size'][0]}x{result['original_size'][1]}")
        print(f"  Pixel art size: {result['pixel_size'][0]}x{result['pixel_size'][1]}")
        print(f"  Embroidery size: {result['embroidery_size_cm'][0]}cm x {result['embroidery_size_cm'][1]}cm")
        print(f"  Colors used: {len(result['colors_used'])}")
        for color in result['colors_used']:
            print(f"    {color}")

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
