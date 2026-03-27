"""Unit tests for jarvis-backend: news_search and skills_router modules."""

from __future__ import annotations

import sys
import os

# Allow importing from the same directory without installation
sys.path.insert(0, os.path.dirname(__file__))

import pytest

from news_search import extract_keywords, parse_rss, score_article, _validate_feed_url
from skills_router import SKILL_PATTERNS, is_routing_enabled, route

# ---------------------------------------------------------------------------
# news_search – extract_keywords
# ---------------------------------------------------------------------------


class TestExtractKeywords:
    def test_prefix_หาข่าวที่เกี่ยวกับ(self):
        kws = extract_keywords("หาข่าวที่เกี่ยวกับราคาทองคำ")
        assert "ราคาทองคำ" in kws

    def test_prefix_หาข่าวเกี่ยวกับ(self):
        kws = extract_keywords("หาข่าวเกี่ยวกับหุ้น")
        assert "หุ้น" in kws

    def test_prefix_หาข่าว_bare(self):
        kws = extract_keywords("หาข่าวราคาน้ำมัน")
        # After stripping หาข่าว the remainder is ราคาน้ำมัน
        assert any("ราคาน้ำมัน" in k for k in kws)

    def test_prefix_ค้นข่าว(self):
        kws = extract_keywords("ค้นข่าวเกี่ยวกับอุณหภูมิ")
        assert any(k for k in kws)

    def test_prefix_ข่าวเกี่ยวกับ(self):
        kws = extract_keywords("ข่าวเกี่ยวกับสภาพอากาศ")
        assert "สภาพอากาศ" in kws

    def test_empty_query_returns_empty(self):
        assert extract_keywords("") == []

    def test_no_prefix_returns_whole_query(self):
        kws = extract_keywords("ราคาทองคำ")
        assert "ราคาทองคำ" in kws

    def test_multiword_query_splits(self):
        kws = extract_keywords("หาข่าวเกี่ยวกับ gold price")
        assert "gold" in kws or "gold price" in kws


# ---------------------------------------------------------------------------
# news_search – parse_rss
# ---------------------------------------------------------------------------

_SAMPLE_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Test Feed</title>
    <item>
      <title>ราคาทองคำพุ่งสูง</title>
      <link>https://example.com/gold-news</link>
      <description>ราคาทองคำวันนี้พุ่งสูงเป็นประวัติการณ์</description>
      <pubDate>Fri, 27 Mar 2026 06:00:00 +0000</pubDate>
    </item>
    <item>
      <title>ข่าวกีฬา</title>
      <link>https://example.com/sports</link>
      <description>ผลการแข่งขันฟุตบอล</description>
    </item>
  </channel>
</rss>"""


class TestParseRss:
    def test_returns_two_articles(self):
        arts = parse_rss(_SAMPLE_RSS)
        assert len(arts) == 2

    def test_first_article_fields(self):
        arts = parse_rss(_SAMPLE_RSS)
        assert arts[0]["title"] == "ราคาทองคำพุ่งสูง"
        assert arts[0]["link"] == "https://example.com/gold-news"
        assert "ราคาทองคำ" in arts[0]["description"]

    def test_malformed_xml_returns_empty(self):
        arts = parse_rss("this is not xml")
        assert arts == []

    def test_html_stripped_from_title(self):
        xml = _SAMPLE_RSS.replace("ราคาทองคำพุ่งสูง", "<b>ราคาทองคำพุ่งสูง</b>")
        arts = parse_rss(xml)
        assert "<b>" not in arts[0]["title"]


# ---------------------------------------------------------------------------
# news_search – score_article
# ---------------------------------------------------------------------------


class TestScoreArticle:
    def test_exact_keyword_match(self):
        a = {"title": "ราคาทองคำพุ่งสูง", "description": ""}
        assert score_article(a, ["ราคาทองคำ"]) == 1

    def test_multiple_keyword_hits(self):
        a = {"title": "ราคาทองคำ", "description": "ราคาทองคำวันนี้"}
        # both keywords match the same article text
        assert score_article(a, ["ราคาทองคำ", "ทองคำ"]) == 2

    def test_no_match(self):
        a = {"title": "ข่าวกีฬา", "description": "บอลไทย"}
        assert score_article(a, ["ราคาทองคำ"]) == 0

    def test_case_insensitive_english(self):
        a = {"title": "Gold Price Rises", "description": ""}
        assert score_article(a, ["gold"]) == 1


# ---------------------------------------------------------------------------
# news_search – search_news (async, no real HTTP)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_news_no_keywords():
    from news_search import search_news

    result = await search_news("หาข่าว", feeds=[])
    # Empty query after stripping prefix, or no feeds – returns helpful message
    assert "brief" in result
    assert result["sources"] == []


@pytest.mark.asyncio
async def test_search_news_no_results_message(monkeypatch):
    """When feeds are empty, returns the no-match message."""
    from news_search import search_news

    result = await search_news("หาข่าวเกี่ยวกับราคาทองคำ", feeds=[])
    assert "brief" in result
    assert "ราคาทองคำ" in result["brief"] or "ไม่พบ" in result["brief"]
    assert result["articles"] == []


@pytest.mark.asyncio
async def test_search_news_with_mock_feed(monkeypatch):
    """search_news returns matching articles when feed returns relevant XML."""
    from news_search import search_news

    async def _fake_fetch(url: str) -> list:
        return parse_rss(_SAMPLE_RSS)

    import news_search as ns_module

    monkeypatch.setattr(ns_module, "_fetch_rss", _fake_fetch)

    result = await search_news(
        "หาข่าวเกี่ยวกับราคาทองคำ",
        feeds=["https://fake.example.com/feed"],
    )
    assert result["articles"], "Expected at least one matching article"
    assert "ราคาทองคำ" in result["brief"]
    assert result["sources"]  # at least one URL


# ---------------------------------------------------------------------------
# skills_router
# ---------------------------------------------------------------------------


class TestIsRoutingEnabled:
    def test_enabled_true(self, monkeypatch):
        monkeypatch.setenv("SKILLS_ROUTING_ENABLED", "true")
        assert is_routing_enabled() is True

    def test_enabled_1(self, monkeypatch):
        monkeypatch.setenv("SKILLS_ROUTING_ENABLED", "1")
        assert is_routing_enabled() is True

    def test_disabled_false(self, monkeypatch):
        monkeypatch.setenv("SKILLS_ROUTING_ENABLED", "false")
        assert is_routing_enabled() is False

    def test_disabled_empty(self, monkeypatch):
        monkeypatch.delenv("SKILLS_ROUTING_ENABLED", raising=False)
        assert is_routing_enabled() is False


class TestRoute:
    def test_หาข่าว_matches_news_search(self, monkeypatch):
        monkeypatch.setenv("SKILLS_ROUTING_ENABLED", "true")
        assert route("หาข่าวที่เกี่ยวกับราคาทองคำ") == "news_search"

    def test_ค้นข่าว_matches_news_search(self, monkeypatch):
        monkeypatch.setenv("SKILLS_ROUTING_ENABLED", "true")
        assert route("ค้นข่าวเกี่ยวกับหุ้น") == "news_search"

    def test_ข่าวเกี่ยวกับ_matches_news_search(self, monkeypatch):
        monkeypatch.setenv("SKILLS_ROUTING_ENABLED", "true")
        assert route("ข่าวเกี่ยวกับสภาพอากาศ") == "news_search"

    def test_unmatched_returns_none(self, monkeypatch):
        monkeypatch.setenv("SKILLS_ROUTING_ENABLED", "true")
        assert route("เล่นเพลงสวัสดี") is None

    def test_routing_disabled_returns_none(self, monkeypatch):
        monkeypatch.setenv("SKILLS_ROUTING_ENABLED", "false")
        assert route("หาข่าวราคาทองคำ") is None

    def test_english_find_news(self, monkeypatch):
        monkeypatch.setenv("SKILLS_ROUTING_ENABLED", "true")
        assert route("find news about gold") == "news_search"

    def test_english_news_about(self, monkeypatch):
        monkeypatch.setenv("SKILLS_ROUTING_ENABLED", "true")
        assert route("news about inflation") == "news_search"


class TestValidateFeedUrl:
    def test_valid_https_url_passes(self):
        _validate_feed_url("https://feeds.bbci.co.uk/thai/rss.xml")  # should not raise

    def test_valid_http_url_passes(self):
        _validate_feed_url("http://feeds.bbci.co.uk/thai/rss.xml")  # should not raise

    def test_localhost_blocked(self):
        with pytest.raises(ValueError):
            _validate_feed_url("http://localhost:8080/feed")

    def test_127_0_0_1_blocked(self):
        with pytest.raises(ValueError):
            _validate_feed_url("http://127.0.0.1/feed")

    def test_private_ip_blocked(self):
        with pytest.raises(ValueError):
            _validate_feed_url("http://192.168.1.1/feed")

    def test_link_local_blocked(self):
        with pytest.raises(ValueError):
            _validate_feed_url("http://169.254.169.254/latest/meta-data/")

    def test_ftp_scheme_blocked(self):
        with pytest.raises(ValueError):
            _validate_feed_url("ftp://example.com/feed.xml")



    def test_at_least_three_thai_news_patterns(self):
        thai_news = [
            (p, s)
            for p, s in SKILL_PATTERNS
            if s == "news_search" and any(ord(c) > 0x0E00 for c in p)
        ]
        assert len(thai_news) >= 3, "Expected ≥3 Thai patterns for news_search"
