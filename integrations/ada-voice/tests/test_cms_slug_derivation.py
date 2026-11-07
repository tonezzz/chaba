"""Slug derivation for cms_publish_page (card
fix-cms-publish-page-slug-argument, 2026-10-27).

Ada hit 'missing required slug' SchemaErrors: the model sends
title+content and no slug. slug= is now optional — the tool derives it
from the title (_cms_slugify) and the pending-confirm key uses the same
derivation so register/confirm stay matched. A title with no Latin
letters still errors plainly.
"""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock

from backend.tool_runner import ToolRunner
from backend.tool_runner.cms import CmsMixin


_PAGE_META = {"summary": "Pool status brief", "domain": "home",
              "fresh_for": "6h", "confidence": "high"}


class SlugifyTest(unittest.TestCase):

    def test_basic_title(self):
        self.assertEqual(CmsMixin._cms_slugify("Pool Notes 2026!"),
                         "pool-notes-2026")

    def test_accents_and_dashes(self):
        self.assertTrue(CmsMixin._cms_slugify(
            "Relatório de Cheias — Rio Tietê").startswith("relat-rio"))

    def test_thai_only_yields_empty(self):
        self.assertEqual(CmsMixin._cms_slugify("การบ้าน"), "")

    def test_long_title_truncates_on_word_cut(self):
        s = CmsMixin._cms_slugify("x " * 60 + "tail")
        self.assertLessEqual(len(s), 60)
        self.assertFalse(s.endswith("-"))


class CmsPublishSlugDerivationTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.ha_client = AsyncMock()
        self.ha_client.base_url = "http://test:8123"
        self.ha_client._states.return_value = []
        self.ha_client.sensors.return_value = []
        self.runner = ToolRunner(self.ha_client, instance_id="test")
        self.runner.mddb = AsyncMock()
        self.runner.mddb.search_documents.return_value = []
        self.runner.mddb.add_document.return_value = {"status": "ok"}
        self.runner.mddb.get_document.return_value = None

    async def test_no_slug_derives_from_title(self):
        # The register call carries no slug — the pending key uses the
        # derived slug too, so the confirmed resubmit matches.
        with self.assertRaises(PermissionError):
            await self.runner.execute(
                "cms_publish_page",
                {"title": "Pool Notes", "content": "# Pool\npH 7.4",
                 **_PAGE_META})
        result = await self.runner.execute(
            "cms_publish_page",
            {"title": "Pool Notes", "content": "# Pool\npH 7.4",
             "confirmed": True, **_PAGE_META})
        self.assertEqual(result["status"], "published")
        self.assertEqual(result["slug"], "pool-notes")
        for c in self.runner.mddb.add_document.call_args_list:
            if len(c.args) > 1 and c.args[1] == "pool-notes":
                self.assertEqual(c.kwargs["meta"]["slug"], ["pool-notes"])
                break
        else:
            self.fail("no add_document call for derived slug")

    async def test_explicit_slug_still_wins(self):
        with self.assertRaises(PermissionError):
            await self.runner.execute(
                "cms_publish_page",
                {"slug": "custom-id", "title": "Pool Notes",
                 "content": "# x", **_PAGE_META})
        result = await self.runner.execute(
            "cms_publish_page",
            {"slug": "custom-id", "title": "Pool Notes",
             "content": "# x", "confirmed": True, **_PAGE_META})
        self.assertEqual(result["slug"], "custom-id")

    async def test_thai_title_without_slug_errors_plainly(self):
        with self.assertRaises(PermissionError):
            # pending registers (no slug needed for the key)
            await self.runner.execute(
                "cms_publish_page",
                {"title": "การบ้าน", "content": "# x", **_PAGE_META})
        out = await self.runner.execute(
            "cms_publish_page",
            {"title": "การบ้าน", "content": "# x",
             "confirmed": True, **_PAGE_META})
        self.assertFalse(out["ok"])
        self.assertIn("slug", out["error"])


if __name__ == "__main__":
    unittest.main()
