from tests.fakes import FakeLLMClient


def _article(article_id, title, story_label="Test Story"):
    return {
        "id": article_id,
        "source": "Test Source",
        "language": "en",
        "title": title,
        "description": "Description",
        "url": f"https://example.com/{article_id}",
        "published_at": "Sat, 18 Apr 2026 12:00:00 GMT",
        "text": "",
        "theme": "Tech",
        "story_label": story_label,
        "importance": 3,
    }


def _fake_tracker_client(payload):
    return FakeLLMClient(payload)


def _fake_tracker_client_sequence(payloads, captured=None):
    return FakeLLMClient(payloads, capture=captured)
