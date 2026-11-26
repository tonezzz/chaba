"""Unit tests for the inpaint-lane helpers (mask builder + local-file
landing). No network — PIL is required for mask tests and skipped if absent."""
import importlib.util
import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent.parent / "scripts" / "adobe-stock"


def load(name: str):
    spec = importlib.util.spec_from_file_location(
        name.replace("-", "_"), SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def png_file(tmp_path):
    p = tmp_path / "img.png"
    try:
        from PIL import Image
        Image.new("RGB", (64, 64), (10, 20, 30)).save(p)
    except ImportError:
        pytest.skip("Pillow not installed")
    return p


def test_mask_box_region(png_file, tmp_path):
    mask_mod = load("inpaint-mask")
    out = tmp_path / "m.png"
    sys.argv = ["inpaint-mask.py", "--image", str(png_file),
                "--box", "10,10,20,20", "--feather", "0",
                "--out", str(out)]
    assert mask_mod.main() == 0
    from PIL import Image
    m = Image.open(out)
    assert m.size == (64, 64)
    assert m.getpixel((15, 15)) == 255
    assert m.getpixel((0, 0)) == 0
    assert m.getpixel((40, 40)) == 0


def test_mask_polygon(png_file, tmp_path):
    mask_mod = load("inpaint-mask")
    out = tmp_path / "m.png"
    sys.argv = ["inpaint-mask.py", "--image", str(png_file),
                "--poly", "0,0;32,0;0,32", "--feather", "0",
                "--out", str(out)]
    assert mask_mod.main() == 0
    from PIL import Image
    m = Image.open(out)
    assert m.getpixel((5, 5)) == 255
    assert m.getpixel((50, 50)) == 0


def test_mask_requires_region(png_file, tmp_path):
    mask_mod = load("inpaint-mask")
    sys.argv = ["inpaint-mask.py", "--image", str(png_file),
                "--out", str(tmp_path / "m.png")]
    with pytest.raises(SystemExit):
        mask_mod.main()


def test_local_file_lane(tmp_path):
    land = load("land-render")
    png = tmp_path / "out.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 64)
    res = land.fetch_local_file(str(png))
    assert res["status"] == "completed"
    assert res["png_bytes"].startswith(b"\x89PNG")
    res = land.fetch_local_file(str(tmp_path / "missing.png"))
    assert res["status"] == "failed"
