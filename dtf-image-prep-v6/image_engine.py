"""Image-processing engine for DTF Image Prep.

The TIFF writer stores an RGB image, an unassociated alpha sample, a W1 spot
mask sample (Photoshop spot polarity), and Photoshop ImageResources metadata (8BIM resources 1006/1007).
Because RIP implementations differ, the resulting file must still be verified
in the target RIP before production use.
"""
from __future__ import annotations

import struct
from pathlib import Path

import numpy as np
import tifffile
from PIL import Image, ImageFilter, PngImagePlugin

APP_NAME = "DTF Image Prep"
SPOT_CHANNEL_NAME = "W1"


def source_dpi(image: Image.Image) -> tuple[float, float]:
    """Return positive source DPI, using 300 only when metadata is absent/invalid."""
    dpi = image.info.get("dpi", (300.0, 300.0))
    try:
        x, y = float(dpi[0]), float(dpi[1])
        if x <= 0 or y <= 0:
            raise ValueError
        return x, y
    except (TypeError, ValueError, IndexError):
        return 300.0, 300.0


def trim_transparent(image: Image.Image, alpha_threshold: int = 4, remove_islands: bool = True) -> Image.Image:
    """Crop to nontransparent bounds, retaining RGBA and image metadata."""
    rgba = image.convert("RGBA")
    if not 0 <= alpha_threshold <= 255:
        raise ValueError("Alpha threshold must be 0–255")
    a = np.asarray(rgba.getchannel("A"), dtype=np.uint8).copy()
    a[a <= alpha_threshold] = 0
    if remove_islands and a.any():
        # Remove isolated small opaque fragments disconnected from main artwork.
        # Keep components with at least 9 pixels, or at least 0.005% of the
        # occupied artwork area; don't erase fine connected edges.
        try:
            from scipy import ndimage
            occupied = a > 0
            labels, count = ndimage.label(occupied, structure=np.ones((3, 3), dtype=np.uint8))
            if count:
                sizes = np.bincount(labels.ravel())
                cutoff = max(9, int(occupied.sum() * 0.00005))
                remove = (labels > 0) & (sizes[labels] < cutoff)
                a[remove] = 0
        except ImportError:
            pass
    rgba.putalpha(Image.fromarray(a, "L"))
    bbox = rgba.getchannel("A").getbbox()
    result = rgba.copy() if bbox is None else rgba.crop(bbox)
    result.info.update(image.info)
    return result


def add_half_inch_canvas(image: Image.Image) -> Image.Image:
    """Increase total width and height by 0.5 inches, centered.

    This matches the user's Photoshop workflow: e.g. 12 x 5 inches becomes
    12.5 x 5.5 inches. The total added pixels are calculated from the image's
    DPI, then split as evenly as possible between opposite edges.
    """
    rgba = image if image.mode == "RGBA" else image.convert("RGBA")
    dx, dy = source_dpi(image)
    add_x = max(1, round(0.5 * dx))
    add_y = max(1, round(0.5 * dy))
    left = add_x // 2
    top = add_y // 2
    canvas = Image.new("RGBA", (rgba.width + add_x, rgba.height + add_y), (0, 0, 0, 0))
    canvas.alpha_composite(rgba, (left, top))
    canvas.info["dpi"] = (dx, dy)
    return canvas


def make_spot_mask(alpha: Image.Image, shrink_px: int) -> Image.Image:
    """Create a white-ink mask by contracting the alpha selection.

    A grayscale minimum filter approximates Photoshop's Select > Modify >
    Contract while retaining partial coverage at antialiased edges. A very small
    blur softens the new edge to avoid an unnecessarily jagged underbase.
    """
    if shrink_px not in (1, 2, 3):
        raise ValueError("Mask contraction must be 1, 2, or 3 pixels.")
    mask = alpha.convert("L")
    if mask.getbbox() is None:
        return Image.new("L", mask.size, 0)
    try:
        from scipy.ndimage import minimum_filter
    except ImportError:
        mask = mask.filter(ImageFilter.MinFilter(2 * shrink_px + 1))
    else:
        # A separable native filter gives the same grayscale minimum and clamped
        # image boundary as Pillow, without its costly large-window scan.
        values = minimum_filter(np.asarray(mask), size=2 * shrink_px + 1, mode="nearest")
        mask = Image.fromarray(values)
    mask = mask.filter(ImageFilter.GaussianBlur(0.35))
    return mask


def prepare_image(source: Path, alpha_threshold: int = 4, remove_islands: bool = True) -> Image.Image:
    """Load once and return the trimmed, padded image without encoding a temporary PNG."""
    with Image.open(source) as opened:
        dpi = source_dpi(opened)
        trimmed = trim_transparent(opened, alpha_threshold, remove_islands)
        try:
            trimmed.info["dpi"] = dpi
            return add_half_inch_canvas(trimmed)
        finally:
            trimmed.close()


def save_prepared_png(image: Image.Image, destination: Path, compress_level: int = 3) -> None:
    """Save lossless PNG quickly; compression affects file size, not image quality."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    meta = PngImagePlugin.PngInfo()
    meta.add_text("Software", APP_NAME)
    meta.add_text("CanvasExpansion", "Total canvas width +0.5 inch; total height +0.5 inch; centered")
    image.save(destination, format="PNG", dpi=source_dpi(image), pnginfo=meta,
               optimize=False, compress_level=compress_level)


def prepare_png(source: Path, destination: Path, alpha_threshold: int = 4, remove_islands: bool = True) -> tuple[int, int]:
    """Backward-compatible path-based PNG preparation API."""
    image = prepare_image(source, alpha_threshold, remove_islands)
    try:
        save_prepared_png(image, destination)
        return image.size
    finally:
        image.close()


def _resource_block(resource_id: int, data: bytes) -> bytes:
    """Encode one Photoshop 8BIM image-resource block."""
    # Empty Pascal resource name is two bytes (length=0 plus even-byte padding).
    block = b"8BIM" + struct.pack(">H", resource_id) + b"\x00\x00"
    block += struct.pack(">I", len(data)) + data
    if len(data) & 1:
        block += b"\x00"
    return block


def _pascal_names(names: list[str]) -> bytes:
    """Encode the legacy Photoshop alpha-channel names resource (ID 1006)."""
    result = bytearray()
    for name in names:
        encoded = name.encode("latin-1", errors="replace")[:255]
        result.append(len(encoded))
        result.extend(encoded)
    return bytes(result)


def _display_info_rgb(red: int, green: int, blue: int, opacity: int = 100, kind: int = 0) -> bytes:
    """Encode Photoshop's 14-byte DisplayInfo record (resource ID 1007)."""
    # Color space 0 = RGB; values are unsigned 16-bit full-range RGB components.
    # The fourth component is unused for RGB and set to zero.
    return struct.pack(">H4HHBB", 0, red, green, blue, 0, opacity, kind, 0)


def _photoshop_resources() -> bytes:
    """Build Photoshop channel names/display resources for alpha + W1 channels."""
    # The TIFF samples after RGB are: unassociated alpha, then the W1 spot plane.
    names = _pascal_names(["Transparency", SPOT_CHANNEL_NAME])
    # Transparency is displayed neutrally; W1 has a white display swatch and 100% solidity.
    display = _display_info_rgb(32768, 0, 0, 50) + _display_info_rgb(65535, 65535, 65535, 100, kind=2)
    return _resource_block(1006, names) + _resource_block(1007, display)


def export_tiff_with_w1(png_path: Path, tiff_path: Path, shrink_px: int) -> None:
    """Write RGB + transparency + named W1 spot sample to a TIFF.

    TIFF tag 34377 carries Photoshop 8BIM ImageResources, including the channel
    names and spot display color/solidity. This is designed to be Photoshop/RIP
    compatible, but the user's exact RIIN version still needs a real-app test.
    """
    with Image.open(png_path) as opened:
        export_tiff_image_with_w1(opened, tiff_path, shrink_px)


def export_tiff_image_with_w1(image: Image.Image, tiff_path: Path, shrink_px: int) -> None:
    """Export the prepared in-memory image, preserving the existing TIFF layout/resources."""
    rgba_image = image if image.mode == "RGBA" else image.convert("RGBA")
    dpi = source_dpi(image)
    rgba = np.asarray(rgba_image, dtype=np.uint8)
    alpha_image = rgba_image.getchannel("A")
    coverage = np.asarray(make_spot_mask(alpha_image, shrink_px), dtype=np.uint8)
    # Allocate the five-channel output once. No temporary PNG or separate spot copy.
    pixels = np.empty((rgba.shape[0], rgba.shape[1], 5), dtype=np.uint8)
    pixels[:, :, :4] = rgba
    # Photoshop plate polarity: 0 = full ink, 255 = no ink. Alpha stays separate.
    np.subtract(255, coverage, out=pixels[:, :, 4])

    resources = _photoshop_resources()
    tiff_path.parent.mkdir(parents=True, exist_ok=True)
    tifffile.imwrite(
        tiff_path,
        pixels,
        photometric="rgb",
        planarconfig="contig",
        extrasamples=("unassalpha", "unspecified"),
        compression=None,
        resolution=(dpi[0], dpi[1]),
        resolutionunit="INCH",
        metadata=None,
        software=APP_NAME,
        description="RGB artwork with transparency and Photoshop spot channel W1",
        extratags=[(34377, "B", len(resources), resources, False)],
    )


def verify_tiff_structure(tiff_path: Path) -> tuple[bool, str]:
    """Basic structural check: five samples and Photoshop channel metadata present."""
    try:
        with tifffile.TiffFile(tiff_path) as tif:
            page = tif.pages[0]
            if page.samplesperpixel != 5:
                return False, f"Expected 5 TIFF samples (RGB + alpha + W1); found {page.samplesperpixel}."
            if 34377 not in page.tags:
                return False, "Photoshop ImageResources tag (34377) is missing."
            resources = page.tags[34377].value
            if b"W1" not in resources or b"8BIM" not in resources:
                return False, "Photoshop channel metadata does not contain W1 as expected."
            if b"\x00\x64\x02\x00" not in resources:
                return False, "Spot display metadata does not declare spot channel kind=2."
            if len(page.extrasamples) != 2:
                return False, "Expected separate alpha and spot samples in the TIFF."
            return True, "TIFF structure check passed (RGB + alpha + W1 metadata). Verify in RIIN before printing."
    except Exception as exc:
        return False, f"TIFF verification failed: {exc}"
