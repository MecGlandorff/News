def _briefing_article(article_id, theme, label, importance=3, source=None):
    return {
        "id": article_id,
        "source": source or f"Source {article_id}",
        "language": "en",
        "title": f"{label} title",
        "description": "Description",
        "url": f"https://example.com/{article_id}",
        "published_at": "Sat, 18 Apr 2026 12:30:00 GMT",
        "text": "",
        "theme": theme,
        "story_label": label,
        "canonical_label": label,
        "importance": importance,
        "trend": "new",
    }
