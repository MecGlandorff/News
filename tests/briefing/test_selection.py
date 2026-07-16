
from src.briefing import build_briefing_markdown
from tests.briefing.support import _briefing_article


def _briefings(stories):
    return {story["canonical_label"]: "Briefing text." for story in stories}


def test_briefing_uses_editorial_sections_and_scraps_sports():
    markdown = build_briefing_markdown([
        _briefing_article(1, "Geopolitics & War", "Hormuz Strait", 5),
        _briefing_article(2, "USA Politics", "US Congress", 4),
        _briefing_article(3, "Dutch Politics", "Dutch Cabinet", 4),
        _briefing_article(4, "Economy", "Oil Prices", 4),
        _briefing_article(5, "Other", "Kinahan Arrest", 3),
        _briefing_article(9, "USA Politics", "US Courts", 3),
        _briefing_article(10, "Dutch Politics", "Dutch Budget", 3),
        _briefing_article(11, "Economy", "China Sanctions", 3),
        _briefing_article(12, "Other", "Celebrity Video", 4),
        _briefing_article(6, "Sports", "Korfball Title", 5),
        _briefing_article(7, "Tech", "AI Opinion Piece", 4),
        _briefing_article(8, "Science", "Minor Health Story", 4),
    ], n=3, briefing_provider=_briefings)

    assert markdown.startswith("# Top Developments")
    assert "# Politics" in markdown
    assert "# Economy" in markdown
    assert "# Other Important Stories" in markdown
    assert "# Sports" not in markdown
    assert "Korfball Title" not in markdown
    assert "AI Opinion Piece" not in markdown
    assert "Minor Health Story" not in markdown
    assert "Celebrity Video" not in markdown
    assert "Kinahan Arrest" in markdown


def test_briefing_can_show_high_signal_penalized_themes():
    articles = [_briefing_article(1, "USA Politics", "US Budget Vote", 4)]
    for index in range(4):
        articles.append(_briefing_article(10 + index, "Tech", "AI Safety Lawsuit", 4, source=f"Tech Source {index}"))
        articles.append(_briefing_article(20 + index, "Science", "Ebola Outbreak", 4, source=f"Science Source {index}"))
    for index in range(10):
        articles.append(_briefing_article(30 + index, "Sports", "Olympic Corruption Probe", 5, source=f"Sports Source {index}"))

    markdown = build_briefing_markdown(articles, n=3, briefing_provider=_briefings)

    assert "AI Safety Lawsuit" in markdown
    assert "Ebola Outbreak" in markdown
    assert "Olympic Corruption Probe" in markdown


def test_briefing_does_not_show_ordinary_sports_even_when_slate_is_thin():
    markdown = build_briefing_markdown([
        _briefing_article(1, "Sports", "Regular League Result", 5),
    ], n=3, briefing_provider=_briefings)

    assert "No tracked stories found." not in markdown
    assert "Regular League Result" not in markdown
    assert "# Top Developments" in markdown


def test_briefing_does_not_suppress_hard_news_for_video_format():
    articles = [
        _briefing_article(1, "Other", "Modena Car Attack", 4, source="NOS"),
        _briefing_article(2, "Other", "Modena Car Attack", 4, source="BBC News"),
        _briefing_article(3, "Other", "Modena Car Attack", 4, source="The Guardian"),
        _briefing_article(4, "Other", "Modena Car Attack", 4, source="NYT"),
    ]
    articles[0]["title"] = "Video | Beveiligingscamera filmt hoe auto inrijdt op mensen in Modena"

    markdown = build_briefing_markdown(articles, n=3, briefing_provider=_briefings)

    assert "Modena Car Attack" in markdown
    assert "Beveiligingscamera filmt hoe auto inrijdt op mensen in Modena" in markdown


def test_briefing_does_not_suppress_hard_news_for_tv_channel_reference():
    articles = [
        _briefing_article(1, "Other", "San Diego Mosque Shooting", 5, source="NOS"),
        _briefing_article(2, "Other", "San Diego Mosque Shooting", 5, source="The Guardian"),
        _briefing_article(3, "Other", "San Diego Mosque Shooting", 5, source="Al Jazeera"),
    ]
    articles[0]["description"] = "According to the imam, witnesses told a TV channel what happened."

    markdown = build_briefing_markdown(articles, n=3, briefing_provider=_briefings)

    assert "San Diego Mosque Shooting" in markdown
    assert "Briefing text." in markdown


def test_briefing_deduplicates_story_across_themes():
    markdown = build_briefing_markdown([
        _briefing_article(1, "Geopolitics & War", "Iran War", 5, source="Source A"),
        _briefing_article(2, "Economy", "Iran War", 4, source="Source B"),
        _briefing_article(3, "USA Politics", "Iran War", 4, source="Source C"),
    ], n=3, briefing_provider=_briefings)

    assert markdown.count("## 1. NEW STORY Iran War") == 1
    assert "Geopolitics & War / USA Politics / Economy" in markdown
