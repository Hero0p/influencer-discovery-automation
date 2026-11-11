"""Settings: API keys from .env, niche and brand definitions from config/*.yaml."""

import os
from dataclasses import dataclass
from pathlib import Path

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "outreach.db"

# Labels written to the outputs whenever a value could not be collected.
# The pipeline never guesses a missing value.
NOT_FOUND = "Not Found"
NOT_AVAILABLE = "Not Available"


@dataclass
class Settings:
    youtube_api_key: str
    gemini_api_key: str
    gemini_model: str
    gemini_fallback_model: str
    gemini_min_seconds: float
    service_account_file: Path
    sheet_id: str
    apify_token: str
    send_mode: str
    test_inbox: str
    auto_approve: bool
    niche: dict
    brand: dict


def load_yaml(name):
    with open(ROOT / "config" / name, encoding="utf-8") as file:
        return yaml.safe_load(file)


def load_settings():
    """Read .env and the YAML files, and stop early if the sending setup is unsafe."""
    load_dotenv(ROOT / ".env")
    env = os.environ.get

    settings = Settings(
        youtube_api_key=env("YOUTUBE_API_KEY", "").strip(),
        gemini_api_key=env("GEMINI_API_KEY", "").strip(),
        gemini_model=env("GEMINI_MODEL", "gemini-3.8-flash").strip(),
        gemini_fallback_model=env("GEMINI_FALLBACK_MODEL", "").strip(),
        gemini_min_seconds=float(env("GEMINI_MIN_SECONDS_BETWEEN_CALLS", "7")),
        service_account_file=ROOT / env("GOOGLE_SERVICE_ACCOUNT_FILE", "credentials/service-account.json"),
        sheet_id=env("SHEET_ID", "").strip(),
        apify_token=env("APIFY_TOKEN", "").strip(),
        send_mode=env("SEND_MODE", "test").strip().lower(),
        test_inbox=env("TEST_INBOX", "").strip(),
        auto_approve=env("AUTO_APPROVE", "false").strip().lower() == "true",
        niche=load_yaml("niche.yaml"),
        brand=load_yaml("brand.yaml"),
    )

    if settings.send_mode not in ("test", "live"):
        raise SystemExit("SEND_MODE in .env must be 'test' or 'live'.")
    if settings.send_mode == "test" and not settings.test_inbox:
        raise SystemExit("SEND_MODE=test needs TEST_INBOX in .env (the inbox that receives every demo email).")
    if settings.send_mode == "live" and settings.brand.get("is_demo"):
        raise SystemExit(
            "SEND_MODE=live is blocked because config/brand.yaml describes a demo brand (is_demo: true). "
            "Real creators must not be emailed on behalf of a fictional brand."
        )
    return settings
