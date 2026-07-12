import json

from tests.fakes import FakeLLMClient

ARTICLE = {
    "id": "article-abc123",
    "story_id": 42,
    "source": "Reuters",
    "title": "Iran offers uranium deal",
    "description": "Iran proposed capping enrichment at 3.67%. Officials confirmed the offer.",
    "url": "https://reuters.com/iran",
    "published_at": "Fri, 1 May 2026 12:00:00 GMT",
}
CLAIM_RESPONSE = {
    "claims": [
        {
            "claim_text": "Iran proposed capping enrichment at 3.67%.",
            "claim_type": "number",
            "entities": ["Iran"],
            "evidence_span": "Iran proposed capping enrichment at 3.67%.",
            "confidence": 0.95,
        },
        {
            "claim_text": "Officials confirmed the offer.",
            "claim_type": "fact",
            "entities": [],
            "evidence_span": "Officials confirmed the offer.",
            "confidence": 0.8,
        },
    ]
}

def _fake_client(response_content):
    return FakeLLMClient(response_content)

def _fake_response(response_content):
    class Message:
        content = json.dumps(response_content)

    class Choice:
        message = Message()

    class Response:
        choices = [Choice()]

    return Response()
