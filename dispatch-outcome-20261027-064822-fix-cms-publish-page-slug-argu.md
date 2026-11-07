# Outcome — fix cms_publish_page slug argument (KNB-0624)

## Root cause

`cms_publish_page`'s declaration required `slug`, but the model often
calls it with `title`+`content` only. The lazy-schema validator
(`tool_runner/common.py::_validate_call_args`) answered
`SchemaError: missing required 'slug'` and the call died BEFORE the
confirm handshake — exactly the "slug argument not found" failure the
session audit kept flagging. The title already implies the page id, so
the right fix is derivation, not a louder error.

## Fix (staged as ada-voice Drop 16)

All changes live in one patch —
`integrations/ada-voice/backend/cms-slug-derivation.patch` — verified
`git apply --check` CLEAN against ada-voice `main` @ `56c67c1`:

- `backend/tool_runner/cms.py` — new `CmsMixin._cms_slugify` (free
  text → `_SLUG_RE`-legal hyphenated slug, accent strip, 60-char word
  cut); `cms_publish_page`'s `slug`/`title`/`content` gain `""`
  defaults; empty slug falls back to `slugify(title)`; a title with no
  Latin letters raises a plain ValueError naming the fix.
- `backend/tool_runner/__init__.py` — pending-confirm key derives the
  slug the same way (`slug or slugify(title)`), so a no-slug register
  call and its confirmed resubmit share the key.
- `backend/realtime_provider.py` — `slug` leaves the declaration's
  `required` list; description/tool blurb say "omit to derive from the
  title". Report meta contract (summary/domain/fresh_for/confidence)
  still required.
- `backend/tool_guide.yml` — guide entry documents the optional slug.
- `tests/test_cms_slug_derivation.py` — new ada-voice suite (also
  copied to `integrations/ada-voice/tests/`): slugify shapes,
  derive+pending-key match, explicit slug wins, Thai-only error.

Chaba side: `tests/ada/test_cms_slug_derivation_drop.py` guards the
artifacts + applyability; job record
`docs/ssot/jobs/ada/2026-10-27-cms-publish-slug-derivation.yml`; README
lists Drop 16. Committed on `dispatch/20261027-064822-…` as `52089345e`;
card commented via board-api.

## Verify

- `git apply --check` vs ada-voice `main` @ `56c67c1`: APPLIES-CLEAN.
- `py_compile` clean on every touched backend file + staged test.
- Could NOT run pytest here (no venv/pip on tony-macbook) — the
  ada-voice suite runs at the deploy gate (`deploy-ada.sh` →
  tool-lint + `pytest tests/`).

## To land it

On tony-dell (`~/CascadeProjects/ada-voice`):
`git apply <chaba>/integrations/ada-voice/backend/cms-slug-derivation.patch`
then `~/.local/bin/deploy-ada.sh` (gates + restart). After deploy: a
`cms_publish_page` call with `title` and no `slug` should publish to
the derived slug instead of SchemaError.
