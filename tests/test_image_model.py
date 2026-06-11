"""Tests for the three-tier image state model (image_model.py)."""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from pxv.enhancements import EnhancementParams
from pxv.image_model import ImageModel

from conftest import BorderedFactory


# --- _has_transparency -------------------------------------------------------


@pytest.mark.parametrize("mode", ["RGBA", "LA", "PA"])
def test_has_transparency_alpha_modes(mode: str) -> None:
    assert ImageModel._has_transparency(Image.new(mode, (1, 1))) is True


def test_has_transparency_palette_with_info() -> None:
    img = Image.new("P", (1, 1))
    img.info["transparency"] = 0
    assert ImageModel._has_transparency(img) is True


@pytest.mark.parametrize("mode", ["RGB", "L"])
def test_has_transparency_opaque_modes(mode: str) -> None:
    assert ImageModel._has_transparency(Image.new(mode, (1, 1))) is False


def test_has_transparency_palette_without_info() -> None:
    assert ImageModel._has_transparency(Image.new("P", (1, 1))) is False


# --- _to_rgb_working (transparent pixels composite onto white) ----------------


def test_to_rgb_working_rgba_composites_onto_white() -> None:
    img = Image.new("RGBA", (2, 1))
    img.putpixel((0, 0), (255, 0, 0, 0))  # transparent over red
    img.putpixel((1, 0), (0, 255, 0, 255))  # opaque green
    out = ImageModel._to_rgb_working(img)
    assert out.mode == "RGB"
    assert out.getpixel((0, 0)) == (255, 255, 255)  # no red leak
    assert out.getpixel((1, 0)) == (0, 255, 0)


def test_to_rgb_working_la_composites_onto_white() -> None:
    img = Image.new("LA", (2, 1))
    img.putpixel((0, 0), (100, 0))  # transparent
    img.putpixel((1, 0), (100, 255))  # opaque
    out = ImageModel._to_rgb_working(img)
    assert out.mode == "RGB"
    assert out.getpixel((0, 0)) == (255, 255, 255)
    assert out.getpixel((1, 0)) == (100, 100, 100)


def test_to_rgb_working_palette_transparency_composites_onto_white() -> None:
    img = Image.new("P", (2, 1))
    img.putpalette([255, 0, 0, 0, 255, 0])  # index 0 red, index 1 green
    img.putpixel((0, 0), 0)
    img.putpixel((1, 0), 1)
    img.info["transparency"] = 0
    out = ImageModel._to_rgb_working(img)
    assert out.mode == "RGB"
    assert out.getpixel((0, 0)) == (255, 255, 255)  # red index was transparent -> white
    assert out.getpixel((1, 0)) == (0, 255, 0)


def test_to_rgb_working_opaque_rgb_returns_copy() -> None:
    img = Image.new("RGB", (2, 1), (1, 2, 3))
    out = ImageModel._to_rgb_working(img)
    assert out.mode == "RGB"
    assert out.getpixel((0, 0)) == (1, 2, 3)
    assert out is not img


# --- load --------------------------------------------------------------------


def test_load_rgba_sets_save_buffer(tmp_path: Path) -> None:
    p = tmp_path / "t.png"
    Image.new("RGBA", (4, 4), (255, 0, 0, 128)).save(p)
    model = ImageModel()
    model.load(p)
    assert model.working_image is not None
    assert model.working_image.mode == "RGB"
    assert model._save_rgba is not None
    assert model._save_rgba.mode == "RGBA"
    assert model.current_path == p


def test_load_opaque_jpeg_has_no_save_buffer(tmp_path: Path) -> None:
    p = tmp_path / "t.jpg"
    Image.new("RGB", (4, 4), (10, 20, 30)).save(p)
    model = ImageModel()
    model.load(p)
    assert model._save_rgba is None
    assert model.working_image is not None
    assert model.working_image.mode == "RGB"


# --- crop --------------------------------------------------------------------


def test_crop_reduces_working_size() -> None:
    model = ImageModel()
    model.working_image = Image.new("RGB", (10, 10), (10, 20, 30))
    model.crop((2, 2, 8, 8))
    assert model.get_working_size() == (6, 6)


def test_crop_applies_to_save_rgba() -> None:
    model = ImageModel()
    model.working_image = Image.new("RGB", (10, 10), (10, 20, 30))
    model._save_rgba = Image.new("RGBA", (10, 10), (10, 20, 30, 255))
    model.crop((1, 1, 6, 6))
    assert model.get_working_size() == (5, 5)
    assert model._save_rgba is not None
    assert model._save_rgba.size == (5, 5)


# --- snapshot_buffers / restore_buffers (undo/redo support) ------------------


def test_snapshot_buffers_returns_independent_copies() -> None:
    model = ImageModel()
    model.working_image = Image.new("RGB", (4, 3), (10, 20, 30))
    model._save_rgba = Image.new("RGBA", (4, 3), (10, 20, 30, 128))
    snap = model.snapshot_buffers()
    assert snap is not None
    working, save_rgba = snap
    assert working is not model.working_image  # a copy, not the live object
    assert working.size == (4, 3)
    assert save_rgba is not None and save_rgba.size == (4, 3)
    # Mutating the model afterward must not disturb the captured snapshot.
    model.working_image = model.working_image.crop((0, 0, 2, 2))
    assert working.size == (4, 3)


def test_snapshot_buffers_opaque_has_no_save_rgba() -> None:
    model = ImageModel()
    model.working_image = Image.new("RGB", (2, 2), (1, 2, 3))
    snap = model.snapshot_buffers()
    assert snap is not None
    _working, save_rgba = snap
    assert save_rgba is None


def test_snapshot_buffers_none_when_no_image() -> None:
    assert ImageModel().snapshot_buffers() is None


def test_restore_buffers_installs_given_buffers() -> None:
    model = ImageModel()
    model.working_image = Image.new("RGB", (2, 2), (0, 0, 0))
    w = Image.new("RGB", (5, 5), (9, 9, 9))
    rgba = Image.new("RGBA", (5, 5), (9, 9, 9, 200))
    model.restore_buffers(w, rgba)
    assert model.working_image is w
    assert model._save_rgba is rgba


def test_restore_buffers_can_clear_save_rgba() -> None:
    model = ImageModel()
    model.working_image = Image.new("RGB", (2, 2), (0, 0, 0))
    model._save_rgba = Image.new("RGBA", (2, 2), (0, 0, 0, 255))
    model.restore_buffers(Image.new("RGB", (3, 3), (1, 1, 1)), None)
    assert model._save_rgba is None


# --- autocrop ----------------------------------------------------------------


def test_autocrop_rgb_trims_uniform_border(bordered: BorderedFactory) -> None:
    model = ImageModel()
    model.working_image = bordered((20, 20), (255, 255, 255), (255, 0, 0), (5, 5, 15, 15))
    assert model.autocrop() is True
    assert model.get_working_size() == (10, 10)


def test_autocrop_solid_image_returns_false() -> None:
    model = ImageModel()
    model.working_image = Image.new("RGB", (10, 10), (50, 60, 70))
    assert model.autocrop() is False
    assert model.get_working_size() == (10, 10)


def test_autocrop_alpha_trims_transparent_border() -> None:
    model = ImageModel()
    rgba = Image.new("RGBA", (20, 20), (0, 0, 0, 0))
    rgba.paste(Image.new("RGBA", (10, 10), (0, 255, 0, 255)), (5, 5))
    model._save_rgba = rgba
    model.working_image = ImageModel._to_rgb_working(rgba)
    assert model.autocrop() is True
    assert model.get_working_size() == (10, 10)
    assert model._save_rgba is not None
    assert model._save_rgba.size == (10, 10)


# --- rotate / flip / resize keep both buffers in lockstep --------------------


def test_geometry_ops_keep_buffers_in_lockstep() -> None:
    model = ImageModel()
    model.working_image = Image.new("RGB", (4, 2), (10, 20, 30))
    model._save_rgba = Image.new("RGBA", (4, 2), (10, 20, 30, 255))
    model.rotate(90)
    assert model.working_image is not None and model._save_rgba is not None
    assert model.working_image.size == (2, 4)
    assert model._save_rgba.size == (2, 4)
    model.flip_horizontal()
    assert model.working_image.size == (2, 4)
    assert model._save_rgba.size == (2, 4)
    model.resize((8, 8))
    assert model.working_image.size == (8, 8)
    assert model._save_rgba.size == (8, 8)


# --- reset -------------------------------------------------------------------


def test_reset_restores_original_working() -> None:
    model = ImageModel()
    original = Image.new("RGB", (10, 10), (5, 6, 7))
    model.original_image = original
    model.working_image = original.crop((0, 0, 4, 4))
    model.reset()
    assert model.get_working_size() == (10, 10)
    assert model.working_image is not None
    assert model.working_image.getpixel((0, 0)) == (5, 6, 7)


# --- get_save_image (preserve_alpha avoids white fringing) -------------------


def test_get_save_image_preserve_alpha_no_white_fringe() -> None:
    model = ImageModel()
    rgba = Image.new("RGBA", (1, 1), (255, 0, 0, 128))
    model._save_rgba = rgba
    model.working_image = ImageModel._to_rgb_working(rgba)  # ~ (255, 127, 127)
    out = model.get_save_image(EnhancementParams(), preserve_alpha=True)
    assert out is not None
    assert out.mode == "RGBA"
    assert out.getpixel((0, 0)) == (255, 0, 0, 128)  # true RGB preserved, not fringed


def test_get_save_image_opaque_returns_rgb() -> None:
    model = ImageModel()
    model.working_image = Image.new("RGB", (2, 2), (10, 20, 30))
    out = model.get_save_image(EnhancementParams())
    assert out is not None
    assert out.mode == "RGB"
    assert out.getpixel((0, 0)) == (10, 20, 30)


# --- get_display_image -------------------------------------------------------


def test_get_display_image_scales_by_zoom() -> None:
    model = ImageModel()
    model.working_image = Image.new("RGB", (10, 10), (10, 20, 30))
    out = model.get_display_image(zoom=0.5, params=EnhancementParams())
    assert out is not None
    assert out.size == (5, 5)


def test_get_display_image_dark_background_recomposites() -> None:
    model = ImageModel()
    rgba = Image.new("RGBA", (1, 1), (0, 0, 0, 0))  # fully transparent
    model._save_rgba = rgba
    model.working_image = ImageModel._to_rgb_working(rgba)  # white
    out = model.get_display_image(zoom=1.0, params=EnhancementParams(), bg_color=(0, 0, 0))
    assert out is not None
    assert out.getpixel((0, 0)) == (0, 0, 0)  # transparent shown on black background


def test_load_captures_metadata(exif_jpeg: object) -> None:
    from pxv.image_model import ImageModel

    model = ImageModel()
    model.load(exif_jpeg())  # type: ignore[operator]
    assert model.metadata is not None
    assert model.metadata.exif.get(0x010E) == "orig desc"
    assert model.keep_metadata is False


def test_reset_restores_metadata_and_keep_flag(exif_jpeg: object) -> None:
    from pxv.image_model import ImageModel

    model = ImageModel()
    model.load(exif_jpeg())  # type: ignore[operator]
    assert model.metadata is not None
    model.metadata.exif[0x010E] = "edited"
    model.keep_metadata = True
    model.reset()
    assert model.metadata.exif.get(0x010E) == "orig desc"
    assert model.keep_metadata is False


# --- apply_overlay (annotation bake) ------------------------------------------


def _dot_overlay(size: tuple[int, int]) -> Image.Image:
    """Transparent RGBA overlay with one opaque and one half-alpha red pixel."""
    overlay = Image.new("RGBA", size, (0, 0, 0, 0))
    overlay.putpixel((1, 1), (255, 0, 0, 255))
    overlay.putpixel((2, 1), (255, 0, 0, 128))
    return overlay


def test_apply_overlay_paints_working_image() -> None:
    model = ImageModel()
    model.working_image = Image.new("RGB", (4, 4), (0, 0, 255))
    model.apply_overlay(_dot_overlay((4, 4)))
    assert model.working_image is not None
    assert model.working_image.getpixel((1, 1)) == (255, 0, 0)  # opaque replaces
    r, g, b = model.working_image.getpixel((2, 1))  # type: ignore[misc]
    assert 126 <= r <= 130 and g == 0 and 124 <= b <= 129  # ~50% red over blue
    assert model.working_image.getpixel((0, 0)) == (0, 0, 255)  # untouched elsewhere


def test_apply_overlay_keeps_buffers_in_lockstep() -> None:
    model = ImageModel()
    model.working_image = Image.new("RGB", (4, 4), (0, 0, 255))
    model._save_rgba = Image.new("RGBA", (4, 4), (0, 0, 255, 200))
    model.apply_overlay(_dot_overlay((4, 4)))
    assert model._save_rgba is not None
    assert model._save_rgba.getpixel((1, 1)) == (255, 0, 0, 255)
    assert model._save_rgba.getpixel((0, 0)) == (0, 0, 255, 200)  # alpha intact


def test_apply_overlay_opaque_image_keeps_no_save_rgba() -> None:
    model = ImageModel()
    model.working_image = Image.new("RGB", (4, 4), (0, 0, 255))
    model.apply_overlay(_dot_overlay((4, 4)))
    assert model._save_rgba is None


def test_apply_overlay_replaces_buffer_objects() -> None:
    # Consumers key caches on working_image object identity (enhancement-dialog
    # input histograms, the annotation stale-image guard) — see the method note.
    model = ImageModel()
    working_before = Image.new("RGB", (4, 4), (0, 0, 255))
    rgba_before = Image.new("RGBA", (4, 4), (0, 0, 255, 255))
    model.working_image = working_before
    model._save_rgba = rgba_before
    model.apply_overlay(_dot_overlay((4, 4)))
    assert model.working_image is not working_before
    assert model._save_rgba is not rgba_before


def test_apply_overlay_no_image_is_noop() -> None:
    model = ImageModel()
    model.apply_overlay(Image.new("RGBA", (4, 4), (0, 0, 0, 0)))
    assert model.working_image is None


def test_apply_overlay_size_mismatch_raises_and_leaves_buffers_untouched() -> None:
    """A mismatched overlay raises ValueError and leaves BOTH buffers unchanged."""
    model = ImageModel()
    working_before = Image.new("RGB", (4, 4), (0, 0, 255))
    rgba_before = Image.new("RGBA", (4, 4), (0, 0, 255, 200))
    model.working_image = working_before
    model._save_rgba = rgba_before
    bad_overlay = Image.new("RGBA", (8, 8), (255, 0, 0, 255))  # wrong size
    with pytest.raises(ValueError, match="overlay size"):
        model.apply_overlay(bad_overlay)
    # Both buffers must be completely untouched.
    assert model.working_image is working_before
    assert model._save_rgba is rgba_before
