# Font Scale Guide

## Understanding Font Scale Limits

Each Ink/Stitch font has minimum and maximum scale limits to ensure quality embroidery. When you specify a target width, the script calculates the required scale and checks if it's within the font's limits.

## Common Scale Limits

| Font Name | Base Size | Min Scale | Max Scale | Good For |
|-----------|-----------|-----------|-----------|----------|
| **Ink/Stitch Small Font** | 5.1mm | 70% | 300% | 0.6" - 2.4" |
| **DinoMouse72** | 18mm | 50% | 300% | 1.5" - 8.5" |
| **Excalibur KOR** | 18mm | 50% | 140% | 1.5" - 4" |
| **Geneva Simple Sans** | 10mm | 100% | 200% | 1.6" - 3.2" |
| **Apex Lake** | 57mm | 80% | 130% | 7.5" - 12" |
| **Alchemy** | 50mm | 60% | 300% | 5" - 24" |
| **Apesplit** | 120mm | 70% | 110% | 13" - 21" |

## Choosing the Right Font

### For Small Text (< 2 inches)

Use fonts with:
- Small base size (< 10mm)
- High maximum scale (> 200%)

**Recommended fonts:**
```bash
uv run batch_text_to_pes.py "text" out.pes --font "Ink/Stitch Small Font" --target-width-inches 1.5
uv run batch_text_to_pes.py "text" out.pes --font "Caffeine tiny" --target-width-inches 1.0
uv run batch_text_to_pes.py "text" out.pes --font "Glacial Tiny 60 AGS" --target-width-inches 0.8
```

### For Medium Text (2-6 inches)

Most fonts work well in this range.

**Recommended fonts:**
```bash
uv run batch_text_to_pes.py "text" out.pes --font "Excalibur KOR" --target-width-inches 3.0
uv run batch_text_to_pes.py "text" out.pes --font "TT Directors" --target-width-inches 4.0
uv run batch_text_to_pes.py "text" out.pes --font "Geneva Simple Sans" --target-width-inches 2.5
```

### For Large Text (> 6 inches)

Use fonts with:
- Large base size (> 40mm)
- Good scale range

**Recommended fonts:**
```bash
uv run batch_text_to_pes.py "text" out.pes --font "Apex Lake" --target-width-inches 8.0
uv run batch_text_to_pes.py "text" out.pes --font "Alchemy" --target-width-inches 12.0
uv run batch_text_to_pes.py "text" out.pes --font "Apesplit" --target-width-inches 15.0
```

## What Happens When Limits Are Exceeded

If your target width requires a scale outside the font's limits, the script will warn you:

```bash
$ uv run batch_text_to_pes.py "TEST" out.pes --font "Apex Lake" --target-width-inches 2.5

Calculating scale for target width: 63.5mm (2.50 inches)
Font 'Apex Lake' scale limits: 80-130%
Measured width at 100% scale: 245.6mm (9.67 inches)
Calculated scale: 25%
⚠ WARNING: Scale 25% is below font minimum of 80%
  Using minimum scale 80%, which will produce 196.5mm (7.74 inches)
  Consider choosing a smaller font or adjusting your target width
✓ Created out.pes
  Final width: 196.4mm (7.73 inches)
```

## Tips

1. **Use `list_fonts.py`** to see all fonts with their sizes and scale ranges:
   ```bash
   uv run list_fonts.py | grep -i small
   ```

2. **Start with a test** at your target size to find the right font:
   ```bash
   # Try different fonts to see which works best
   uv run batch_text_to_pes.py "TEST" test1.pes --font "Ink/Stitch Small Font" --target-width-inches 2.0
   uv run batch_text_to_pes.py "TEST" test2.pes --font "Excalibur KOR" --target-width-inches 2.0
   ```

3. **The script is accurate** - it measures the actual rendered width and calculates the exact scale needed, within font limits.

4. **Height scales automatically** - you only need to specify width. The height will scale proportionally.
