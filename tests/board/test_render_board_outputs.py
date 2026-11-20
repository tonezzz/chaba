import importlib.util
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "render_board", REPO / "scripts/render-board.py"
)
render_board = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(render_board)


def test_classic_page_is_saved_beside_default_redirect(tmp_path):
    index_path = tmp_path / "board" / "index.html"
    index_path.parent.mkdir()
    classic_page = "<!doctype html><title>Classic Board</title>"

    classic_path = render_board.write_board_pages(index_path, classic_page)

    assert classic_path == index_path.with_name("classic.html")
    assert classic_path.read_text(encoding="utf-8") == classic_page
    assert "/apps/board2/" in index_path.read_text(encoding="utf-8")
    assert "location.replace" in index_path.read_text(encoding="utf-8")
