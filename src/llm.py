import json
import os

from openai import OpenAI
from src.env import load_dotenv_file

OPENAI_API_KEY_HELP = (
    "OPENAI_API_KEY is not set. Add it to .env or set it before running the pipeline, for example:\n"
    "  export OPENAI_API_KEY='your-api-key'\n"
    "  python -m src.run"
)


def has_openai_api_key():
    load_dotenv_file()
    return bool(os.getenv("OPENAI_API_KEY"))


def require_openai_api_key():
    if not has_openai_api_key():
        raise RuntimeError(OPENAI_API_KEY_HELP)


def get_openai_client():
    require_openai_api_key()
    return OpenAI(api_key=os.environ["OPENAI_API_KEY"])


def parse_json_object(response):
    content = response.choices[0].message.content
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Model returned invalid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ValueError("Model response must be a JSON object")
    return parsed
