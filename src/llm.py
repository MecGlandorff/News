import json
import os
import time

from openai import OpenAI
from src.env import load_dotenv_file
from src import observability

OPENAI_API_KEY_HELP = (
    "OPENAI_API_KEY is not set. Add it to .env or set it before running the pipeline, for example:\n"
    "  export OPENAI_API_KEY='your-api-key'\n"
    "  python -m src.run"
)

_RESPONSE_CALL_IDS = {}


def has_openai_api_key():
    load_dotenv_file()
    return bool(os.getenv("OPENAI_API_KEY"))


def require_openai_api_key():
    if not has_openai_api_key():
        raise RuntimeError(OPENAI_API_KEY_HELP)


def get_openai_client():
    require_openai_api_key()
    return OpenAI(api_key=os.environ["OPENAI_API_KEY"])


def create_chat_completion(
    client,
    *,
    model,
    messages,
    purpose,
    prompt_version=None,
    response_format=None,
    **kwargs,
):
    started = time.perf_counter()
    call_kwargs = {
        "model": model,
        "messages": messages,
        **kwargs,
    }
    if response_format is not None:
        call_kwargs["response_format"] = response_format

    try:
        response = client.chat.completions.create(**call_kwargs)
    except Exception as exc:
        latency_ms = int((time.perf_counter() - started) * 1000)
        observability.record_llm_call(
            model=model,
            purpose=purpose,
            prompt_version=prompt_version,
            latency_ms=latency_ms,
            error_type=type(exc).__name__,
            error_message=str(exc),
        )
        raise

    latency_ms = int((time.perf_counter() - started) * 1000)
    call_id = observability.record_llm_call(
        model=model,
        purpose=purpose,
        prompt_version=prompt_version,
        latency_ms=latency_ms,
        usage=getattr(response, "usage", None),
    )
    if call_id is not None:
        _RESPONSE_CALL_IDS[id(response)] = call_id
    return response


def mark_schema_failure(error_message=None, response=None):
    if response is not None:
        observability.mark_call_schema_failure(_RESPONSE_CALL_IDS.get(id(response)), error_message)
        return
    observability.mark_last_call_schema_failure(error_message)


def parse_json_object(response):
    content = response.choices[0].message.content
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as exc:
        mark_schema_failure(f"Model returned invalid JSON: {exc}", response=response)
        raise ValueError(f"Model returned invalid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        mark_schema_failure("Model response must be a JSON object", response=response)
        raise ValueError("Model response must be a JSON object")
    return parsed
