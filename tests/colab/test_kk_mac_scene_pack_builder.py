import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

import yaml


REPO = Path(__file__).resolve().parents[2]
BUILDER = REPO / "scripts/colab/build-kk-mac-scene-packs.py"


def load_module():
    spec = importlib.util.spec_from_file_location("kk_mac_scene_pack_builder", BUILDER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class KkMacScenePackBuilderTest(unittest.TestCase):
    def test_builds_private_review_gated_one_shot_pack_from_audit_bound_inputs(self):
        builder = load_module()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            images = root / "images"
            embeds = root / "embeds"
            output = root / "packs"
            images.mkdir()
            embeds.mkdir()
            output.mkdir()
            image_bytes = b"audited page 15 image"
            embed_bytes = b"shot03 embedding"
            image = images / "image-008.jpg"
            embed = embeds / "shot03.pt"
            image.write_bytes(image_bytes)
            embed.write_bytes(embed_bytes)
            audit = root / "audit.json"
            audit.write_text(json.dumps({
                "sources": [{
                    "label": "v1_01",
                    "sha256": builder.SOURCE_SHA256,
                    "image_rows": [{"page": 15}],
                    "extracted_files": [{
                        "path": "v1_01/images/image-008.jpg",
                        "bytes": len(image_bytes),
                        "sha256": hashlib.sha256(image_bytes).hexdigest(),
                    }],
                }]
            }))
            scene_map = root / "scene-map.yml"
            scene_map.write_text(yaml.safe_dump({
                "project_id": builder.PROJECT,
                "visibility": "private",
                "source": {"sha256": builder.SOURCE_SHA256},
                "shots": [{
                    "shot": 3,
                    "storyboard_page": 15,
                    "storyboard_image": "image-008",
                }],
            }))
            runner = root / "runner.py"
            runner.write_text("print('test runner')\n")
            args = type("Args", (), {
                "scene_map": scene_map,
                "audit": audit,
                "images_dir": images,
                "embeds_dir": embeds,
                "runner": runner,
                "output_root": output,
                "first_shot": 3,
                "last_shot": 3,
            })()
            [pack_dir] = builder.build(args)
            pack = yaml.safe_load((pack_dir / "pack.yml").read_text())
            shot_map = yaml.safe_load(
                (pack_dir / "inputs/scene-map.yml").read_text())
            self.assertEqual(pack["name"], "kk-mac-storyboard-i2v-shot03-20261030")
            self.assertIn(
                "kk-mac-storyboard-i2v-visual-review-approved-20261030",
                pack["requires"])
            self.assertEqual(shot_map["shot"]["storyboard_page"], 15)
            self.assertEqual(
                shot_map["shot"]["image_sha256"],
                hashlib.sha256(image_bytes).hexdigest())
            self.assertEqual(
                shot_map["shot"]["embedding_sha256"],
                hashlib.sha256(embed_bytes).hexdigest())

    def test_refuses_to_overwrite_a_versioned_pack(self):
        builder = load_module()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            image_dir = root / "images"
            embed_dir = root / "embeds"
            output = root / "packs"
            image_dir.mkdir()
            embed_dir.mkdir()
            output.mkdir()
            (output / "kk-mac-storyboard-i2v-shot03-20261030").mkdir()
            image = image_dir / "image-008.jpg"
            embed = embed_dir / "shot03.pt"
            image.write_bytes(b"image")
            embed.write_bytes(b"embedding")
            audit = root / "audit.json"
            audit.write_text(json.dumps({
                "sources": [{
                    "label": "v1_01",
                    "sha256": builder.SOURCE_SHA256,
                    "image_rows": [{"page": 15}],
                    "extracted_files": [{
                        "path": "v1_01/images/image-008.jpg",
                        "bytes": 5,
                        "sha256": hashlib.sha256(b"image").hexdigest(),
                    }],
                }]
            }))
            scene_map = root / "scene-map.yml"
            scene_map.write_text(yaml.safe_dump({
                "project_id": builder.PROJECT,
                "visibility": "private",
                "source": {"sha256": builder.SOURCE_SHA256},
                "shots": [{
                    "shot": 3,
                    "storyboard_page": 15,
                    "storyboard_image": "image-008",
                }],
            }))
            runner = root / "runner.py"
            runner.write_text("pass\n")
            args = type("Args", (), {
                "scene_map": scene_map,
                "audit": audit,
                "images_dir": image_dir,
                "embeds_dir": embed_dir,
                "runner": runner,
                "output_root": output,
                "first_shot": 3,
                "last_shot": 3,
            })()
            with self.assertRaises(FileExistsError):
                builder.build(args)


if __name__ == "__main__":
    unittest.main()
