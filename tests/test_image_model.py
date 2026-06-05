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


# --- crop / uncrop -----------------------------------------------------------


def test_crop_then_uncrop_restores_one_level() -> None:
    model = ImageModel()
    model.working_image = Image.new("RGB", (10, 10), (10, 20, 30))
    model.crop((2, 2, 8, 8))
    assert model.get_working_size() == (6, 6)
    assert model.uncrop() is True
    assert model.get_working_size() == (10, 10)
    assert model.uncrop() is False  # only one level of undo


def test_crop_applies_to_save_rgba() -> None:
    model = ImageModel()
    model.working_image = Image.new("RGB", (10, 10), (10, 20, 30))
    model._save_rgba = Image.new("RGBA", (10, 10), (10, 20, 30, 255))
    model.crop((1, 1, 6, 6))
    assert model.get_working_size() == (5, 5)
    assert model._save_rgba is not None
    assert model._save_rgba.size == (5, 5)
    model.uncrop()
    assert model._save_rgba is not None
    assert model._save_rgba.size == (10, 10)


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
