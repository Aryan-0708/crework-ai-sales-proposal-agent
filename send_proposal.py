"""
Step 5c: Create, populate, verify, and send the DocuSign envelope
from priced_deal.json.

Order:
1. Read deal_id
2. Check state.json for an existing attempt/sent deal
3. Validate client_email is non-empty
4. Create draft envelope from reusable template
5. Discover this envelope's recipient and textTabs
6. Populate the six fields
7. Verify the populated values
8. Record send_attempted BEFORE the external send
9. Send with updateEnvelope status=sent
10. Record final envelopeId/status in state.json

Usage:
    python send_proposal.py
"""

import asyncio
import json
import sys
from pathlib import Path

from docusign_mcp_client import DocuSignMCPClient


# ============================================================
# CONFIGURATION
# ============================================================

ACCOUNT_ID = "3e3adb01-d033-4473-8950-1c4f35072a4a"

TEMPLATE_ID = "5af5487f-76e8-4562-ac89-e4585f66e50f"

ROLE_NAME = "Client"

EMAIL_SUBJECT = "Sales Proposal - Please Review and Sign"

PRICED_DEAL_FILE = Path("priced_deal.json")
STATE_FILE = Path("state.json")


REQUIRED_TAB_LABELS = [
    "ClientName",
    "ProjectOverview",
    "Scope",
    "Deliverables",
    "Timeline",
    "TotalFee",
]


# ============================================================
# FILE HELPERS
# ============================================================

def load_json(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"Required file not found: {path}")

    with open(path, "r", encoding="utf-8-sig") as f:
        return json.load(f)


def load_state() -> dict:
    if not STATE_FILE.exists():
        return {}

    with open(STATE_FILE, "r", encoding="utf-8-sig") as f:
        return json.load(f)


def save_state(state: dict) -> None:
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(
            state,
            f,
            indent=2,
            ensure_ascii=False,
        )


# ============================================================
# MCP RESPONSE HELPERS
# ============================================================

def parse_result_json(result) -> dict:
    """
    Extract and parse the JSON text payload from an MCP call_tool result.
    """
    content = getattr(result, "content", None) or []

    for item in content:
        text = getattr(item, "text", None)

        if text is not None:
            try:
                return json.loads(text)
            except (json.JSONDecodeError, TypeError):
                raise RuntimeError(
                    f"Unexpected non-JSON tool result:\n{text}"
                )

    raise RuntimeError("Tool result had no content to parse.")


# ============================================================
# FIELD VALUE BUILDING
# ============================================================

def build_field_values(priced_deal: dict) -> dict:
    matched_services = priced_deal.get("matched_services", [])

    if not matched_services:
        raise ValueError("priced_deal.json contains no matched_services.")

    scope_text = "\n".join(
        f"{service['name']}: {service['scope']}"
        for service in matched_services
    )

    deliverables = priced_deal.get("deliverables", [])

    if not deliverables:
        raise ValueError("priced_deal.json contains no deliverables.")

    deliverables_text = ", ".join(deliverables)

    total_fee_text = (
        f"{priced_deal['currency']} "
        f"{priced_deal['total_price']}"
    )

    return {
        "ClientName": priced_deal["client_name"],
        "ProjectOverview": priced_deal["rough_scope"],
        "Scope": scope_text,
        "Deliverables": deliverables_text,
        "Timeline": priced_deal["timeline"],
        "TotalFee": total_fee_text,
    }


# ============================================================
# TAB DISCOVERY
# ============================================================

def find_client_signer(signers: list) -> dict:
    """
    Find the recipient assigned to the Client role.
    """
    signer = next(
        (
            signer
            for signer in signers
            if signer.get("roleName") == ROLE_NAME
        ),
        None,
    )

    if not signer:
        raise RuntimeError(
            f"Could not find recipient with roleName='{ROLE_NAME}'."
        )

    return signer


def build_tab_map(signer: dict) -> dict:
    """
    Build:
        tabLabel -> tabId

    Tab IDs are envelope-specific, so this is rebuilt for every envelope.
    """
    tabs = signer.get("tabs", {})
    text_tabs = tabs.get("textTabs", [])

    tab_id_by_label = {}

    for tab in text_tabs:
        label = tab.get("tabLabel")
        tab_id = tab.get("tabId")

        if not label or not tab_id:
            continue

        tab_id_by_label[label] = tab_id

    missing = [
        label
        for label in REQUIRED_TAB_LABELS
        if label not in tab_id_by_label
    ]

    if missing:
        available_labels = sorted(tab_id_by_label.keys())

        raise RuntimeError(
            "Missing expected tab labels on this envelope.\n"
            f"Missing: {missing}\n"
            f"Available textTab labels: {available_labels}\n"
        )

    return tab_id_by_label


# ============================================================
# TAB VERIFICATION
# ============================================================

def extract_current_text_tabs(signer: dict) -> dict:
    """
    Return:
        tabLabel -> current value
    """
    tabs = signer.get("tabs", {})
    text_tabs = tabs.get("textTabs", [])

    values = {}

    for tab in text_tabs:
        label = tab.get("tabLabel")

        if label:
            values[label] = tab.get("value", "")

    return values


def verify_field_values(
    signer: dict,
    expected_values: dict,
) -> None:
    """
    Confirm every expected field has the expected value.
    """
    actual_values = extract_current_text_tabs(signer)

    mismatches = []

    for label, expected in expected_values.items():
        actual = actual_values.get(label)

        if actual != expected:
            mismatches.append(
                {
                    "label": label,
                    "expected": expected,
                    "actual": actual,
                }
            )

    if mismatches:
        raise RuntimeError(
            "Tab verification failed:\n"
            + json.dumps(
                mismatches,
                indent=2,
                ensure_ascii=False,
            )
        )

    print("TAB VERIFICATION: PASSED")


# ============================================================
# MAIN FLOW
# ============================================================

async def run():
    print("=" * 60)
    print("CREWORK SALES PROPOSAL AGENT")
    print("STEP 5c - DOCUSIGN SEND")
    print("=" * 60)

    # --------------------------------------------------------
    # Load priced deal
    # --------------------------------------------------------

    priced_deal = load_json(PRICED_DEAL_FILE)

    # --------------------------------------------------------
    # 1. Read deal_id
    # --------------------------------------------------------

    deal_id = priced_deal.get("deal_id")

    if not deal_id:
        raise ValueError(
            "priced_deal.json is missing deal_id."
        )

    print(f"\nDeal ID: {deal_id}")

    # --------------------------------------------------------
    # 2. Idempotency guard
    # --------------------------------------------------------

    print("\nIDEMPOTENCY CHECK")

    state = load_state()

    existing = state.get(deal_id)

    if existing:
        print(
            "\nBLOCKED: This deal_id already exists in state.json."
        )
        print(
            "Refusing to create or send another envelope "
            "to prevent duplicates."
        )
        print(
            json.dumps(
                existing,
                indent=2,
                ensure_ascii=False,
            )
        )
        sys.exit(1)

    print("No previous send attempt found. Continuing.")

    # --------------------------------------------------------
    # 3. Validate client_email
    # --------------------------------------------------------

    client_email = (
        priced_deal.get("client_email") or ""
    ).strip()

    if not client_email:
        print(
            "\nFAILED: client_email is empty in priced_deal.json."
        )
        print(
            "Refusing to send."
        )
        print(
            "Add the real client email to deal.json and rerun "
            "match_services.py before running this script again."
        )
        sys.exit(1)

    client_name = (
        priced_deal.get("client_name") or ""
    ).strip()

    if not client_name:
        raise ValueError(
            "priced_deal.json is missing client_name."
        )

    # --------------------------------------------------------
    # Build field values before making DocuSign calls
    # --------------------------------------------------------

    field_values = build_field_values(priced_deal)

    print("\nFIELD VALUES")
    print(
        json.dumps(
            field_values,
            indent=2,
            ensure_ascii=False,
        )
    )

    client = DocuSignMCPClient()

    envelope_id = None

    try:
        # ----------------------------------------------------
        # 4. Create draft envelope
        # ----------------------------------------------------

        print("\nCREATING DRAFT ENVELOPE...")

        create_result = await client.call_tool(
            "createEnvelope",
            {
                "accountId": ACCOUNT_ID,
                "envelopeDefinition": {
                    "status": "created",
                    "templateId": TEMPLATE_ID,
                    "templateRoles": [
                        {
                            "roleName": ROLE_NAME,
                            "name": client_name,
                            "email": client_email,
                        }
                    ],
                    "emailSubject": EMAIL_SUBJECT,
                },
            },
        )

        create_data = parse_result_json(create_result)

        envelope_id = create_data.get("envelopeId")

        if not envelope_id:
            raise RuntimeError(
                "createEnvelope did not return an envelopeId.\n"
                + json.dumps(
                    create_data,
                    indent=2,
                    ensure_ascii=False,
                )
            )

        print(
            f"DRAFT CREATED: {envelope_id}"
        )

        # ----------------------------------------------------
        # 5. Discover this envelope's recipient + textTabs
        # ----------------------------------------------------

        print("\nDISCOVERING RECIPIENT TABS...")

        list_result = await client.call_tool(
            "listRecipients",
            {
                "accountId": ACCOUNT_ID,
                "envelopeId": envelope_id,
                "include_tabs": "true",
            },
        )

        recipients_data = parse_result_json(list_result)

        signers = recipients_data.get("signers", [])

        if not signers:
            raise RuntimeError(
                "No signers found on the draft envelope."
            )

        signer = find_client_signer(signers)

        recipient_id = signer.get("recipientId")

        if not recipient_id:
            raise RuntimeError(
                "Client recipient has no recipientId."
            )

        tab_id_by_label = build_tab_map(signer)

        print(
            f"CLIENT RECIPIENT ID: {recipient_id}"
        )

        print("\nDISCOVERED TAB IDS:")

        for label in REQUIRED_TAB_LABELS:
            print(
                f"  {label} -> {tab_id_by_label[label]}"
            )

        # ----------------------------------------------------
        # 6. Populate the six fields
        # ----------------------------------------------------

        update_tabs = {
            "textTabs": [
                {
                    "tabId": tab_id_by_label[label],
                    "tabLabel": label,
                    "value": value,
                }
                for label, value in field_values.items()
            ]
        }

        print("\nPOPULATING FIELDS...")

        update_result = await client.call_tool(
            "updateEnvelopeTabs",
            {
                "accountId": ACCOUNT_ID,
                "envelopeId": envelope_id,
                "recipientId": recipient_id,
                "tabs": update_tabs,
            },
        )

        parse_result_json(update_result)

        print("TABS POPULATED.")

        # ----------------------------------------------------
        # 7. Verify populated values
        # ----------------------------------------------------

        print("\nVERIFYING POPULATED FIELDS...")

        verify_result = await client.call_tool(
            "listRecipients",
            {
                "accountId": ACCOUNT_ID,
                "envelopeId": envelope_id,
                "include_tabs": "true",
            },
        )

        verify_data = parse_result_json(verify_result)

        verify_signers = verify_data.get("signers", [])

        if not verify_signers:
            raise RuntimeError(
                "Could not retrieve signers during verification."
            )

        verify_signer = find_client_signer(verify_signers)

        verify_field_values(
            verify_signer,
            field_values,
        )

        # ----------------------------------------------------
        # 8. Record send_attempted BEFORE actual send
        # ----------------------------------------------------

        print("\nRECORDING SEND ATTEMPT...")

        state[deal_id] = {
            "envelopeId": envelope_id,
            "status": "send_attempted",
            "client_name": client_name,
            "client_email": client_email,
        }

        save_state(state)

        print(
            "state.json updated with status=send_attempted"
        )

        # ----------------------------------------------------
        # 9. Send envelope
        # ----------------------------------------------------

        print("\nSENDING ENVELOPE...")

        send_result = await client.call_tool(
            "updateEnvelope",
            {
                "accountId": ACCOUNT_ID,
                "envelopeId": envelope_id,
                "envelopeUpdate": {
                    "status": "sent"
                },
            },
        )

        parse_result_json(send_result)  # confirms the send call itself didn't error

        print(
            f"ENVELOPE SEND CALL COMPLETED: {envelope_id}"
        )

        # ----------------------------------------------------
        # 10. Get the authoritative status directly from DocuSign
        #     instead of trusting updateEnvelope's response shape
        # ----------------------------------------------------

        print("\nVERIFYING SEND WITH getEnvelope...")

        get_envelope_result = await client.call_tool(
            "getEnvelope",
            {
                "accountId": ACCOUNT_ID,
                "envelopeId": envelope_id,
            },
        )

        get_envelope_data = parse_result_json(get_envelope_result)

        final_status = get_envelope_data.get("status", "unknown")

        print(
            f"AUTHORITATIVE STATUS (getEnvelope): {final_status}"
        )

        state[deal_id] = {
            "envelopeId": envelope_id,
            "status": final_status,
            "client_name": client_name,
            "client_email": client_email,
        }

        save_state(state)

        print(
            f"\nSTATE SAVED: {deal_id}"
        )

        print("\n" + "=" * 60)
        print("SUCCESS")
        print("=" * 60)

    except Exception as exc:
        print("\n" + "=" * 60)
        print("FAILED")
        print("=" * 60)
        print(f"{type(exc).__name__}: {exc}")

        # If the envelope was created and send_attempted was already
        # written, DO NOT overwrite it. This preserves the duplicate-
        # protection state for ambiguous send failures.
        if envelope_id and state.get(deal_id, {}).get("status") == "send_attempted":
            print(
                "\nIMPORTANT:"
            )
            print(
                "The envelope was marked send_attempted before "
                "the send call."
            )
            print(
                f"Envelope ID: {envelope_id}"
            )
            print(
                "Do NOT rerun automatically. Verify the envelope "
                "status in DocuSign first."
            )

        sys.exit(1)


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    try:
        asyncio.run(run())

    except FileNotFoundError as e:
        print(f"FAILED: {e}")
        sys.exit(1)

    except KeyError as e:
        print(
            "FAILED: priced_deal.json is missing an expected field:"
            f" {e}"
        )
        sys.exit(1)

    except json.JSONDecodeError as e:
        print(
            "FAILED: Invalid JSON file:"
            f" {e}"
        )
        sys.exit(1)

    except Exception as e:
        print(
            f"FAILED: {type(e).__name__}: {e}"
        )
        sys.exit(1)