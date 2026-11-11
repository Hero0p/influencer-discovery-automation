"""`python -m outreach doctor`: check every credential with one small real call. Prints no secrets."""

import json

from apify_client import ApifyClient

from outreach import sheets, youtube
from outreach.llm import Gemini


def check_youtube(settings):
    youtube.call_api("channels", settings.youtube_api_key, part="id", id="UC_x5XG1OV2P6uZZ5FSM9Ttw")
    return "key accepted"


def check_gemini(settings):
    """Looks up each configured model. This proves the key works without spending the daily request quota."""
    gemini = Gemini(settings)
    for model in gemini.models:
        gemini.client.models.get(model=model)
    return f"key accepted, models found: {', '.join(gemini.models)}"


def check_sheets(settings):
    with open(settings.service_account_file, encoding="utf-8") as file:
        account = json.load(file)["client_email"]
    try:
        book = sheets.open_book(settings)
    except PermissionError as error:
        raise RuntimeError(f"{error.__cause__}. Open the sheet, click Share and add {account} as Editor")
    return f"opened '{book.title}' as {account}"


def check_apify(settings):
    if not settings.apify_token:
        return "skipped (APIFY_TOKEN is empty, Instagram numbers will be 'Not Available')"
    user = ApifyClient(settings.apify_token).user("me").get()
    return f"token accepted for account '{user.username}'"


def run_checks(settings):
    checks = {
        "YouTube Data API": check_youtube,
        "Gemini": check_gemini,
        "Google Sheets": check_sheets,
        "Apify": check_apify,
    }
    for name, check in checks.items():
        try:
            print(f"  OK    {name}: {check(settings)}")
        except Exception as error:
            print(f"  FAIL  {name}: {type(error).__name__}: {str(error)[:300]}")

    target = settings.test_inbox if settings.send_mode == "test" else "the creators' own addresses"
    print(f"  INFO  Send mode: {settings.send_mode}. Emails are addressed to {target}.")
