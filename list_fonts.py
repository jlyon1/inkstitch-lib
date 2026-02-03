#!/usr/bin/env python3
"""
List all available Ink/Stitch fonts.
Usage: python list_fonts.py
"""

import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib.lettering.utils import get_font_list

def main():
    print("Available Ink/Stitch fonts:\n")
    print("NOTE: 'height' is character height. Width varies by text content.\n")
    fonts = get_font_list(show_font_path_warning=False)

    for i, font in enumerate(sorted(fonts, key=lambda f: f.name), 1):
        print(f"{i:3d}. {font.name:30s} (height: {font.size}mm, scale: {int(font.min_scale*100)}-{int(font.max_scale*100)}%)")

    print(f"\nTotal: {len(fonts)} fonts")
    print("\nUsage: python batch_text_to_pes.py 'Your Text' output.pes --font 'FontName' --target-width-inches 2.5")
    print("Use font_info.py 'FontName' for detailed information about a specific font.")

if __name__ == "__main__":
    main()
