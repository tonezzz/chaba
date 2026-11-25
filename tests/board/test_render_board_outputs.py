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


def _dispatch_card(**kw):
    card = {"id": "card-x", "column": "done",
            "action": {"type": "dispatch", "status": "done"}}
    card.update(kw)
    return card


def test_task_id_for_prefers_action_task_id():
    card = _dispatch_card(
        action={"type": "dispatch", "status": "done",
                "task_id": "20990101-000000-legacy"},
        comms=[{"text": "started devin-task-20990102-000000-newer on h"}])
    assert render_board._task_id_for(card) == "20990101-000000-legacy"


def test_task_id_for_claim_session_before_comms():
    card = _dispatch_card(
        claim={"session": "20990101-000000-claim-sess"},
        comms=[{"text": "started devin-task-20990102-000000-newer on h"}])
    assert render_board._task_id_for(card) == "20990101-000000-claim-sess"


def test_task_id_for_comms_newest_first():
    # a retried card's comms carry every attempt — the newest devin-task
    # line is the live session (merge-sweep.task_id_for parity)
    card = _dispatch_card(comms=[
        {"text": "started devin-task-20990101-000000-old-attempt on h"},
        {"text": "unrelated comms"},
        {"text": "started devin-task-20990102-000000-new-attempt on h"}])
    assert render_board._task_id_for(card) == "20990102-000000-new-attempt"


def test_task_id_for_comms_extends_truncated_newest():
    # finish/sweep comms truncate embedded ids — the newest mention can
    # be a prefix of the same run's full id on the 'started' line
    # (seen live: ada-session-summary-inflow-stalled recovered
    # '...found-while-shi' instead of '...found-while-shipping-memory-ex')
    card = _dispatch_card(comms=[
        {"text": "started devin-task-20261125-150157-found-while-"
                 "shipping-memory-ex on tony-dell (dispatch)"},
        {"text": "merge-sweep: can't land devin-task-20261125-150157-"
                 "found-while-shi"}])
    assert render_board._task_id_for(card) == \
        "20261125-150157-found-while-shipping-memory-ex"


def test_task_id_for_heuristics_skip_non_dispatch():
    # a manual/script card mentioning devin-task-<id> in comms is talking
    # ABOUT a run — recovering it would borrow that run's chips
    card = {"id": "manual-card",
            "action": {"type": "manual", "status": "done"},
            "comms": [{"text": "started devin-task-20990101-000000-x on h"}]}
    assert render_board._task_id_for(card) == ""
    # explicit fields still win regardless of type (legacy parity)
    card["action"]["task_id"] = "20990101-000000-explicit"
    assert render_board._task_id_for(card) == "20990101-000000-explicit"


def test_task_id_for_result_fallback_and_opencode_tid():
    # opencode/kk_mac lanes name tids <card-id>-<epoch>; action.result
    # is the last card-local leg when comms never recorded a start
    card = _dispatch_card(action={
        "type": "dispatch", "status": "done",
        "result": "exit=0 ... | devin-task-card-x-1794223099.service: "
                  "Consumed 1s CPU"})
    assert render_board._task_id_for(card) == "card-x-1794223099"


def test_task_id_for_empty_when_no_evidence():
    assert render_board._task_id_for(_dispatch_card()) == ""
    assert render_board._task_id_for({"id": "plain"}) == ""


def test_runs_for_slug_prefix_match_only_when_unambiguous():
    runs_by_slug = {"real-run-slug": ["dispatch/20990101-000000-real-run-slug"],
                    "real-run-slug-extra": ["dispatch/20990102-000000-real-run-slug-extra"]}
    # truncated result tid -> prefix of the true slug; two candidate
    # keys -> ambiguous, must not borrow either run's chips
    assert render_board._runs_for_slug(runs_by_slug, "real-run") == []
    only = {"real-run-slug": runs_by_slug["real-run-slug"]}
    assert render_board._runs_for_slug(only, "real-run") == \
        ["dispatch/20990101-000000-real-run-slug"]
    assert render_board._runs_for_slug(only, "real-run-slug") == \
        ["dispatch/20990101-000000-real-run-slug"]
    assert render_board._runs_for_slug(only, "") == []


def test_compute_checks_recovers_code_chip_from_comms():
    # the dead-path regression: runner-era cards carry no task_id — the
    # comms 'started devin-task-<id>' line must still reach the git chips
    tid = "20990101-000000-some-run-slug"
    slug = "some-run-slug"
    branch = f"dispatch/{tid}"
    card = _dispatch_card(comms=[
        {"text": f"started devin-task-{tid} on mn01 (dispatch)"}])
    orig = render_board._branch_merged
    render_board._branch_merged = lambda b: b == branch
    try:
        checks = render_board.compute_checks(
            card, {slug: [branch]}, {})
    finally:
        render_board._branch_merged = orig
    code = [k for k in checks if k["k"] == "code"]
    assert code and code[0]["ok"] is True
    assert branch in code[0]["how"]
