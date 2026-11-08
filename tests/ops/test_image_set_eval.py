import importlib.util
from pathlib import Path

from PIL import Image

SCRIPT = Path(__file__).parents[2] / "scripts/gs/image_set_eval.py"
SPEC = importlib.util.spec_from_file_location("image_set_eval", SCRIPT)
mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)


def test_evaluator_accepts_same_size_images(tmp_path):
    for i in range(3):
        image = Image.new("RGB", (64, 64), (30 + i * 40, 80, 120))
        for x in range(0, 64, 4):
            for y in range(0, 64, 4):
                image.putpixel((x, y), (255, 255, 255))
        image.save(tmp_path / f"frame-{i}.png")
    result = mod.evaluate(tmp_path)
    assert result["images"] == 3
    assert result["gates"]["same_dimensions"]
    assert result["recommendation"] == "train_baseline_then_review_masks"


def test_evaluator_flags_mixed_dimensions(tmp_path):
    Image.new("RGB", (64, 64), "red").save(tmp_path / "a.png")
    Image.new("RGB", (32, 64), "blue").save(tmp_path / "b.png")
    result = mod.evaluate(tmp_path)
    assert not result["gates"]["same_dimensions"]
    assert result["recommendation"] == "normalize_dimensions_then_retry"
