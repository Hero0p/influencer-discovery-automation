"""Gemini wrapper: send a prompt, get back a validated Pydantic object.

Uses the Interactions API of the google-genai SDK.
Docs: https://aistudio.google.com/docs

The free tier allows only a few requests per day for each model (20 when this
was written), so callers send creators in batches and this wrapper moves on to
the next model as soon as one reports that its daily limit is reached.
"""

import time

from google import genai
from google.genai import types
from pydantic import ValidationError


class LLMQuotaExhausted(Exception):
    """Every configured model is rate limited or overloaded. Progress is saved, so run the stage again later."""


class Gemini:
    def __init__(self, settings):
        # The SDK's own retries are switched off: retrying and model fallback are handled below,
        # where the behaviour is easy to see.
        no_retries = types.HttpOptions(retry_options=types.HttpRetryOptions(attempts=1))
        self.client = genai.Client(api_key=settings.gemini_api_key, http_options=no_retries)
        # Main model first, then the fallbacks (comma-separated in .env).
        fallbacks = [name.strip() for name in settings.gemini_fallback_model.split(",") if name.strip()]
        self.models = [settings.gemini_model, *fallbacks]
        self.min_seconds = settings.gemini_min_seconds
        self.last_call = 0.0

    @property
    def model(self):
        """The model currently in use."""
        return self.models[0]

    def ask(self, prompt, schema, system):
        """Return the model's answer parsed into `schema` (a Pydantic model class).

        Tries the main model first. When a model is rate limited (429) or
        overloaded (5xx) and stays that way, the next model takes over for the
        rest of the run.
        """
        while self.models:
            answer = self._ask_model(self.model, prompt, schema, system)
            if answer is not None:
                return answer
            self.models.pop(0)
            if self.models:
                print(f"  switching to {self.model}")
        raise LLMQuotaExhausted("No Gemini model is available right now.")

    def _ask_model(self, model, prompt, schema, system):
        """Up to three attempts on one model. Returns None when the model is unavailable."""
        # Seconds to wait after a failed attempt. None marks the last attempt.
        for wait in (20, 60, None):
            self._wait_between_calls()
            try:
                reply = self.client.interactions.create(
                    model=model,
                    system_instruction=system,
                    input=prompt,
                    generation_config={"thinking_level": "low"},
                    response_format={
                        "type": "text",
                        "mime_type": "application/json",
                        "schema": schema.model_json_schema(),
                    },
                    store=False,  # do not keep the conversation on Google's servers
                    timeout=180,
                )
                return schema.model_validate_json(reply.output_text or "")
            except ValidationError:
                if wait is None:
                    raise  # the answer never matched the schema; the caller skips this batch
            except Exception as error:
                status = getattr(error, "status_code", None)
                if status != 429 and (status or 0) < 500:
                    raise  # bad key, bad request and similar: retrying will not help
                asked_to_wait = retry_after_seconds(error)
                if asked_to_wait > 120:
                    print(f"  {model}: daily free-tier limit reached")
                    return None
                print(f"  {model}: HTTP {status}, temporarily rate limited or overloaded")
                if wait:
                    time.sleep(max(wait, asked_to_wait))
        return None

    def _wait_between_calls(self):
        """Keep a minimum gap between requests so the per-minute limit is not hit."""
        wait = self.min_seconds - (time.monotonic() - self.last_call)
        if wait > 0:
            time.sleep(wait)
        self.last_call = time.monotonic()


def retry_after_seconds(error):
    """How long the API asks us to wait (its Retry-After header), or 0 when it does not say.

    A daily limit answers with many hours; a per-minute limit with a few seconds.
    """
    try:
        return int(error.response.headers.get("retry-after", 0))
    except (AttributeError, ValueError):
        return 0
