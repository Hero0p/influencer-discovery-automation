"""Command line entry point: python -m outreach <command>"""

import argparse
import sys

from outreach import classify, db, discovery, doctor, enrichment, export, filtering, messages, sending, youtube
from outreach.config import load_settings
from outreach.llm import LLMQuotaExhausted

# command -> (what it does, function). Listed in pipeline order.
STAGES = {
    "discover": ("search YouTube and store the channels found", lambda s, c, n: discovery.discover(s, c)),
    "measure": ("fetch recent videos and compute engagement", discovery.measure),
    "filter": ("apply the pass/fail rules", lambda s, c, n: filtering.apply_filters(s, c)),
    "classify": ("AI niche and brand-fit classification", classify.classify),
    "enrich": ("find contact email, website and social handles", enrichment.enrich),
    "messages": ("generate the email pitch and Instagram DM", messages.write_messages),
    "export": ("write the CSV files in data/", lambda s, c, n: export.export_csv(s, c)),
    "queue": ("add shortlisted creators to the Google Sheet queues", lambda s, c, n: sending.queue(s, c)),
    "sync": ("read send results from the sheet and refresh the tracker", lambda s, c, n: sending.sync(s, c)),
}
# `filter` runs twice in a full run: once before the AI stage and once after it.
FULL_RUN = ["discover", "measure", "filter", "classify", "filter", "enrich", "messages", "export", "queue", "sync"]


def run_stage(name, settings, conn, limit):
    """Run one stage. A used-up quota stops that stage only; everything done so far is saved."""
    print(f"[{name}]")
    try:
        STAGES[name][1](settings, conn, limit)
    except youtube.QuotaExceeded:
        print("  YouTube quota is used up for today. Run the same command again tomorrow to continue.")
    except LLMQuotaExhausted:
        print("  Gemini quota is used up for now. Run the same command again later to continue.")
    except PermissionError:
        print("  Google Sheets refused access. Run 'python -m outreach doctor' to see what to fix.")


def show_status(conn):
    """Print how many creators have reached each stage."""
    counts = {
        "discovered": "name IS NOT NULL",
        "measured": "measured_at IS NOT NULL",
        "classified by AI": "classified_at IS NOT NULL",
        "PASS (shortlisted)": "status = 'PASS'",
        "FAIL": "status = 'FAIL'",
        "shortlisted with an email": "status = 'PASS' AND email IS NOT NULL",
        "messages accepted": "message_status = 'OK'",
        "queued for sending": "queued_at IS NOT NULL",
        "sent": "sent = 'Yes'",
    }
    for label, where in counts.items():
        print(f"  {len(db.get_creators(conn, where)):>5}  {label}")


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # channel names can contain any character

    stage_help = "\n".join(f"  {name:<9} {text}" for name, (text, _) in STAGES.items())
    parser = argparse.ArgumentParser(
        prog="python -m outreach",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="Micro-influencer discovery and outreach pipeline.",
        epilog=f"commands:\n  doctor    check every API key\n  run       run all stages in order\n"
               f"  status    show progress\n{stage_help}",
    )
    parser.add_argument("command", choices=["doctor", "run", "status", *STAGES])
    parser.add_argument("--limit", type=int, help="process at most this many creators (measure, classify, enrich, messages)")
    args = parser.parse_args()

    settings = load_settings()
    conn = db.connect()

    if args.command == "doctor":
        doctor.run_checks(settings)
    elif args.command == "status":
        show_status(conn)
    elif args.command == "run":
        for name in FULL_RUN:
            run_stage(name, settings, conn, args.limit)
        show_status(conn)
    else:
        run_stage(args.command, settings, conn, args.limit)
