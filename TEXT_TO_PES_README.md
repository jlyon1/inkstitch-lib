# Text to PES Converter

Simple Python scripts to render text with Ink/Stitch fonts to embroidery files (PES, DST, etc).

## Setup

Dependencies are already installed via `uv`. The circular import issue in the codebase has been fixed.

## Usage

### Convert Text to PES

```bash
uv run batch_text_to_pes.py "Your Text" output.pes [options]
```

**Required Arguments:**
- `"Your Text"`: The text to embroider
- `output.pes`: Output file path - extension determines format (pes, dst, jef, etc.)

**Options:**
- `--font FONT`: Font name (default: CooperMarif)
- `--scale SCALE`: Scale percentage (default: 100)
- `--target-width MM`: Target width in millimeters (auto-calculates scale)
- `--target-width-inches INCHES`: Target width in inches (auto-calculates scale)
- `--also-svg`: Also output an SVG file alongside the embroidery file
- `--trim {off,line,word,glyph}`: Thread trim/cut option
- `--color-sort {off,all,line,word}`: Sort stitches by color
- `--text-align {left,center,right,block,letterspacing}`: Text alignment
- `--letter-spacing MM`: Additional letter spacing in mm
- `--word-spacing MM`: Additional word spacing in mm
- `--line-height MM`: Additional line height in mm
- `--use-command-symbols`: Use command symbols for trims/stops

**Examples:**
```bash
# Basic usage with default font
uv run batch_text_to_pes.py "Hello World" hello.pes

# With custom font and scale percentage
uv run batch_text_to_pes.py "Embroidery" output.pes --font "Abécédaire AGS" --scale 150

# Target width of 5 inches (auto-calculates scale)
uv run batch_text_to_pes.py "HELLO" output.pes --font "Apex Lake" --target-width-inches 5.0

# Center-aligned with custom spacing
uv run batch_text_to_pes.py "Custom Text" output.pes --text-align center --letter-spacing 2.0 --line-height 5.0

# With trim commands (cuts thread between lines/words/glyphs)
uv run batch_text_to_pes.py "Multi\nLine\nText" output.pes --trim line

# Different output format
uv run batch_text_to_pes.py "Test" output.dst --font "Apex Lake"

# Output SVG alongside embroidery file for preview/editing
uv run batch_text_to_pes.py "Design" output.pes --also-svg
# Creates: output.pes (embroidery) + output.svg (visual)
```

### List Available Fonts

```bash
uv run list_fonts.py
```

This shows all 100+ available fonts with their sizes and scale ranges.

## How It Works

The `batch_text_to_pes.py` script:
1. Creates a minimal SVG document with Ink/Stitch metadata
2. Uses the `BatchLettering` extension to render text with the specified font
3. Generates embroidery stitches
4. Exports to the requested file format
5. Extracts the file from the output ZIP

## Supported Output Formats

Any format supported by Ink/Stitch:
- **PES**: Brother, Babylock
- **DST**: Tajima
- **JEF**: Janome
- **EXP**: Melco
- **VP3**: Husqvarna Viking
- And many more...

## Files Created

- `batch_text_to_pes.py` - Main conversion script
- `list_fonts.py` - Font listing utility
- `simple_text_to_pes.py` - Earlier experimental version (can be deleted)
- `text_to_pes.py` - Earlier experimental version (can be deleted)

## Fixed Issues

The following circular import issues were fixed in the codebase:
- `/Users/joeylyon/src/inkstitch/lib/extensions/lettering_along_path.py` - Deferred import of `get_font_by_id`
- `/Users/joeylyon/src/inkstitch/lib/extensions/batch_lettering.py` - Deferred import of `get_font_by_name`
- `/Users/joeylyon/src/inkstitch/lib/lettering/utils.py` - Deferred import of `get_custom_font_dir`
- `/Users/joeylyon/src/inkstitch/lib/lettering/font.py` - Deferred import of `get_custom_font_dir`

These changes allow the library to be used programmatically without triggering import errors.
