import importlib.util
import json
from pathlib import Path


MODULE = Path(__file__).parents[2] / "scripts" / "nest" / "pack_manifest.py"
SPEC = importlib.util.spec_from_file_location("pack_manifest", MODULE)
assert SPEC and SPEC.loader
pack_manifest = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pack_manifest)


def test_hash_and_verify_round_trip(tmp_path, capsys):
    (tmp_path / "source").mkdir()
    (tmp_path / "source" / "frame.jpg").write_bytes(b"hibiscus")
    args = type("Args", (), {
        "root": tmp_path, "pack_id": "hibiscus-v1",
        "asset_type": "gaussian", "dataset_ref": "gdrive:ada-nest/x",
        "path_id": "original-v1", "privacy": "private",
    })()
    assert pack_manifest.init_pack(args) == 0
    assert pack_manifest.hash_pack(args) == 0
    capsys.readouterr()
    assert pack_manifest.verify_pack(args) == 0
    result = json.loads(capsys.readouterr().out)
    assert result == {"ok": True, "missing": [], "changed": [], "files": 1}
