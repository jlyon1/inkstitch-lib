# Understanding Font Dimensions

## Font Size = Character HEIGHT

The `size` value in font metadata is the **character height** (em-size), NOT width.

### Example: Ink/Stitch Small Font

```
Base Character Height: 5.08mm
Min Scale: 70%  → Height: 3.6mm (0.14 inches)
Max Scale: 300% → Height: 15.2mm (0.60 inches)
```

**What this means:**
- At 100% scale, characters are **5.08mm tall**
- At 299% scale, characters are **~15mm tall** (5.08 × 2.99)
- Width depends on the specific text content

### Example Output

For text "TEST" with Ink/Stitch Small Font at 299% scale:
- **Height**: 16.6mm (0.65 inches) ✓ Matches font height × scale
- **Width**: 61.6mm (2.43 inches) ← Depends on characters used

## How to Control Dimensions

### Control WIDTH (Most Common)

Use `--target-width-inches` to specify the desired width:

```bash
# Create text that's 2.5 inches wide (height auto-calculated)
uv run batch_text_to_pes.py "TEST" out.pes \
  --font "Ink/Stitch Small Font" \
  --target-width-inches 2.5
```

The script will:
1. Render at 100% to measure actual width
2. Calculate scale needed: `scale = (target / actual) × 100`
3. Check font scale limits (70-300% for this font)
4. Re-render at calculated scale
5. Report final dimensions

### Control HEIGHT (Scale-Based)

Use `--scale` to control character height:

```bash
# Characters will be 15mm tall (5.08mm × 3.0)
uv run batch_text_to_pes.py "TEST" out.pes \
  --font "Ink/Stitch Small Font" \
  --scale 300
```

**Height calculation:**
```
Actual Height = Font Base Height × (Scale / 100)
             = 5.08mm × 3.0
             = 15.24mm
```

**Width will vary** based on the text content.

## Font Metadata You Can Display

Use the `font_info.py` tool:

```bash
uv run font_info.py "Ink/Stitch Small Font"
```

Shows:
- **Base Character Height**: The font's native em-size
- **Min/Max Scale**: Allowed scale range (enforced for quality)
- **Min/Max Height**: Calculated from base height × scale
- **Estimated Width Range**: Rough estimate for typical text
- **Available Glyphs**: What characters the font supports

## Quick Reference

| What You Know | How to Specify It | Command |
|---------------|-------------------|---------|
| Desired WIDTH | `--target-width-inches` | `--target-width-inches 2.5` |
| Desired HEIGHT | `--scale` | Calculate: `(desired_height / font_height) × 100` |
| Both dimensions | Use `--target-width-inches` | Height scales proportionally |

## Example Calculations

### Want 1 inch tall text with "Apex Lake"

```
Font base height: 57mm = 2.24 inches
Target height: 1 inch = 25.4mm
Required scale: (25.4 / 57) × 100 = 45%
✗ ERROR: Font minimum is 80%
```

**Solution**: Choose a smaller font like "Ink/Stitch Small Font" (5.08mm base)

### Want 3 inch wide text

```bash
# Let the script calculate the scale automatically
uv run batch_text_to_pes.py "HELLO" out.pes \
  --font "Excalibur KOR" \
  --target-width-inches 3.0

# Output will show:
# Measured width at 100% scale: 92.1mm (3.63 inches)
# Calculated scale: 83%
# ✓ Using scale: 83%
# Final width: 76.2mm (3.00 inches)
# Final height: 14.9mm (0.59 inches)
```

## Tips

1. **Always use `--target-width-inches`** - it's the most accurate way to get your desired width
2. **Check font limits** with `font_info.py` before choosing a font
3. **Font height controls character size**, width varies by text
4. **Aspect ratio is maintained** - you can't independently control width and height
