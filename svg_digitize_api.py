#!/usr/bin/env python3
"""
FastAPI routes for the SVG-digitizing pipeline: an already-vector SVG in,
a real embroidery file plus structured issue/geometry metadata out. Kept as
its own router, included into batch_text_to_pes.py's app rather than merged
into that file directly -- this is a separate pipeline (vector design -> PES)
from that file's text-to-embroidery one, and keeping them apart means either
can be read or changed without wading through the other.

Two endpoints, matching the two real steps an admin tool drives:

  POST /svg/normalize  -- resolve <use> clones and stroked-line shortcuts
                           into plain filled shapes (normalize_svg.py).
  POST /svg/digitize    -- knock down hidden overlap, measure every shape,
                           run Ink/Stitch's own troubleshooting checks, and
                           generate the real embroidery file -- all three
                           against the same prepared intermediate SVG, so
                           measurements/problems element_index values line
                           up with each other (digitize_svg.py + check_design.py).

Deliberately not exposing combine_design_and_text.py's text-merging step --
out of scope for what this router does.
"""

import base64
import os
import tempfile

from fastapi import APIRouter, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse

from check_design import check_design
from digitize_svg import prepare_svg, write_embroidery_file

router = APIRouter(prefix="/svg", tags=["svg-digitize"])

# Matches Ink/Stitch's own Output extension -- an admin tool has no reason to
# ask for anything else today, and a wide-open format string would let a
# request write to an arbitrary Output code path never exercised or verified
# here.
_ALLOWED_FORMATS = ("pes", "dst", "exp", "jef", "vp3", "png")


async def _save_upload(file: UploadFile, suffix: str) -> str:
    fd, path = tempfile.mkstemp(suffix=suffix)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(await file.read())
    except Exception:
        os.unlink(path)
        raise
    return path


@router.post("/normalize")
async def normalize_endpoint(file: UploadFile, width_mm: float = Form(100)):
    """Step 1. Input: a raw, possibly-shortcut-using source SVG. Output: an
    equivalent SVG with every <use> resolved and every stroked-line band
    turned into real filled shapes -- ready for /svg/digitize, which expects
    plain filled shapes and doesn't itself resolve either shortcut.
    """
    from normalize_svg import normalize_svg  # local: keeps this route's own failure isolated from import-time errors in the other

    input_path = await _save_upload(file, ".svg")
    output_fd, output_path = tempfile.mkstemp(suffix=".svg")
    os.close(output_fd)
    try:
        shape_count = normalize_svg(input_path, output_path, target_width_mm=width_mm)
        with open(output_path, "rb") as f:
            svg_bytes = f.read()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Could not normalize this SVG: {exc}") from exc
    finally:
        os.unlink(input_path)
        if os.path.exists(output_path):
            os.unlink(output_path)

    return JSONResponse({
        "shape_count": shape_count,
        "svg_filename": (file.filename or "design.svg"),
        "svg_base64": base64.b64encode(svg_bytes).decode("ascii"),
    })


@router.post("/digitize")
async def digitize_endpoint(
    file: UploadFile,
    width_mm: float = Form(100),
    knockdown: bool = Form(True),
    format: str = Form("pes"),
    # Fill row spacing in mm, applied to every shape -- smaller means denser
    # (more stitches per area). Ink/Stitch's own default is 0.25mm
    # (FillStitch.row_spacing_mm); left unset here reproduces that default
    # exactly rather than silently picking a different one. Verified this
    # actually changes stitch count, not just a cosmetic no-op: the same
    # design at 0.2/0.25/0.35mm produced 10996/8881/6398 stitches.
    row_spacing_mm: float | None = Form(None),
):
    """Step 2. Input: a plain-shapes SVG (normally /svg/normalize's own
    output, but a simple design with no <use>/stroke shortcuts can skip
    straight here). Output: the real embroidery file plus two pieces of
    metadata an admin reviewing a batch of designs actually needs --
    per-shape geometry (measure_shape: is this long-and-narrow enough that
    a human should convert it to satin instead of a plain fill?) and real
    Ink/Stitch troubleshooting findings (check_design: disconnected pieces,
    fills too small to stitch reliably, object types Ink/Stitch can't
    embroider at all).
    """
    fmt = format.lower()
    if fmt not in _ALLOWED_FORMATS:
        raise HTTPException(status_code=400, detail=f"Unsupported format {format!r}. Choose one of {_ALLOWED_FORMATS}.")

    uniform_params = {"row_spacing_mm": row_spacing_mm} if row_spacing_mm is not None else None

    input_path = await _save_upload(file, ".svg")
    output_path = None
    try:
        # One shared prepared_path for both measurements and check_design --
        # element_index values from each have to reference the same
        # post-knockdown document to mean the same shape (see check_design.py's
        # own docstring on why raw-input indices don't line up after knockdown
        # can drop or split shapes).
        prepared_path, measurements = prepare_svg(
            input_path, target_width_mm=width_mm, knockdown=knockdown, uniform_params=uniform_params
        )
        try:
            problems = check_design(prepared_path)

            output_fd, output_path = tempfile.mkstemp(suffix=f".{fmt}")
            os.close(output_fd)
            write_embroidery_file(prepared_path, output_path)

            with open(output_path, "rb") as f:
                file_bytes = f.read()
        finally:
            os.unlink(prepared_path)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Could not digitize this SVG: {exc}") from exc
    finally:
        os.unlink(input_path)
        if output_path and os.path.exists(output_path):
            os.unlink(output_path)

    base_name = os.path.splitext(file.filename or "design")[0]
    return JSONResponse({
        "format": fmt,
        "filename": f"{base_name}.{fmt}",
        "file_base64": base64.b64encode(file_bytes).decode("ascii"),
        "shape_count": len(measurements),
        "measurements": measurements,
        "clean": not problems,
        "problems": problems,
    })
