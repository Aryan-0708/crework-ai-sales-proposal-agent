"""
Step 6: Poll envelopes in state.json. For any envelope still unsigned
(not completed/declined/voided) 48+ hours after it was sent, draft a
nudge email to a local file. NEVER sends anything automatically.

Usage:
    python check_nudges.py
"""

import asyncio
import json
import os

from datetime import datetime, timezone
from pathlib import Path

from docusign_mcp_client import DocuSignMCPClient

ACCOUNT_ID = "3e3adb01-d033-4473-8950-1c4f35072a4a"

STATE_FILE = Path("state.json")

# Production default: 48 hours
NUDGE_WINDOW_HOURS = 48

# Optional demo override (in minutes)
demo_minutes = os.getenv("DEMO_NUDGE_WINDOW_MINUTES")

if demo_minutes:
    NUDGE_WINDOW_HOURS = float(demo_minutes) / 60

NUDGE_OUTPUT_DIR = Path("nudge_drafts")

TERMINAL_STATUSES = {"completed", "declined", "voided"}


def load_state() -> dict:
    if not STATE_FILE.exists():
        return {}
    with open(STATE_FILE, "r", encoding="utf-8-sig") as f:
        return json.load(f)


def save_state(state: dict) -> None:
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


def parse_result_json(result) -> dict:
    content = getattr(result, "content", None) or []
    for item in content:
        text = getattr(item, "text", None)
        if text is not None:
            try:
                return json.loads(text)
            except (json.JSONDecodeError, TypeError):
                raise RuntimeError(f"Unexpected non-JSON tool result:\n{text}")
    raise RuntimeError("Tool result had no content to parse.")


def parse_docusign_datetime(value: str) -> datetime:
    """DocuSign returns e.g. '2026-09-18T14:07:19.5600000Z' (7-digit
    fractional seconds), which Python's fromisoformat can't parse directly."""
    value = value.replace("Z", "+00:00")
    if "." in value:
        date_part, rest = value.split(".", 1)
        frac, tz = rest[:-6], rest[-6:]
        value = f"{date_part}.{frac[:6]}{tz}"
    return datetime.fromisoformat(value)


def draft_nudge_email(deal_id: str, record: dict) -> Path:
    NUDGE_OUTPUT_DIR.mkdir(exist_ok=True)
    client_name = record.get("client_name", "")
    client_email = record.get("client_email", "")
    envelope_id = record.get("envelopeId", "")

    subject = f"Following up: Sales Proposal for {client_name}"
    body = (
        f"Hi {client_name},\n\n"
        "Just following up on the proposal we sent over - wanted to check "
        "it reached you okay and see if you have any questions before signing.\n\n"
        f"(DocuSign envelope: {envelope_id})\n\n"
        "Happy to jump on a quick call if anything needs clarifying.\n\n"
        "Thanks,\nCrework Sales Agent"
    )

    # Fixed filename: reruns overwrite the same draft rather than piling up
    # duplicates. This script never sends, so overwriting is harmless.
    draft_path = NUDGE_OUTPUT_DIR / f"{deal_id}_nudge.txt"
    with open(draft_path, "w", encoding="utf-8") as f:
        f.write(f"To: {client_email}\n")
        f.write(f"Subject: {subject}\n\n")
        f.write(body)

    return draft_path


async def run():
    state = load_state()
    if not state:
        print("state.json is empty. Nothing to check.")
        return

    client = DocuSignMCPClient()
    now = datetime.now(timezone.utc)

    for deal_id, record in state.items():
        status = record.get("status")
        envelope_id = record.get("envelopeId")

        if status in TERMINAL_STATUSES:
            print(f"[{deal_id}] status={status} — done, skipping.")
            continue

        if not envelope_id:
            print(f"[{deal_id}] no envelopeId recorded — skipping.")
            continue

        print(f"[{deal_id}] Checking envelope {envelope_id}...")
        result = await client.call_tool(
            "getEnvelope",
            {"accountId": ACCOUNT_ID, "envelopeId": envelope_id},
        )
        data = parse_result_json(result)

        current_status = data.get("status", "unknown")
        record["status"] = current_status  # always sync latest known status

        if current_status in TERMINAL_STATUSES:
            print(f"[{deal_id}] Now '{current_status}' — no nudge needed.")
            continue

        sent_datetime_raw = data.get("sentDateTime")
        if not sent_datetime_raw:
            print(f"[{deal_id}] No sentDateTime on envelope — cannot evaluate window.")
            continue

        sent_dt = parse_docusign_datetime(sent_datetime_raw)
        hours_elapsed = (now - sent_dt).total_seconds() / 3600

        if hours_elapsed >= NUDGE_WINDOW_HOURS:
            draft_path = draft_nudge_email(deal_id, record)
            print(
                f"[{deal_id}] Unsigned for {hours_elapsed:.1f}h "
                f"(>= {NUDGE_WINDOW_HOURS}h). Nudge drafted at: {draft_path}"
            )
            print("This draft was NOT sent. Review and send it manually.")
        else:
            remaining = NUDGE_WINDOW_HOURS - hours_elapsed
            print(
                f"[{deal_id}] Unsigned for {hours_elapsed:.1f}h. "
                f"Nudge window not reached yet ({remaining:.1f}h remaining)."
            )

    save_state(state)
    print("\nstate.json updated with any status changes observed.")


if __name__ == "__main__":
    asyncio.run(run())

