# Crework Sales Proposal Agent

Turns a sales call transcript into a sent-and-tracked DocuSign proposal — using local AI and no paid LLM APIs.

## Problem

Proposals take days to reach a prospect after a good sales call, and momentum dies in the gap. This agent closes that gap: it reads the call transcript locally, prices the deal against a fixed rate card, fills a reusable DocuSign template, and sends it for signature through DocuSign MCP — with no paid LLM API cost.

## Pipeline

```
Sales call transcript
  -> Local Ollama (qwen3:1.7b) extraction         [extract_deal.py]
  -> Deterministic service matching + pricing      [match_services.py]
  -> priced_deal.json
  -> Local proposal preview (audit artifact)        [render_proposal.py]
  -> DocuSign MCP: create draft envelope from template
  -> Discover this envelope's tabIds (per-envelope, not fixed on the template)
  -> Populate the six template fields
  -> Verify populated values
  -> Record "send_attempted" (idempotency guard, BEFORE the real send)
  -> Send envelope
  -> getEnvelope for authoritative status           [send_proposal.py]
  -> Poll for 48h+ unsigned envelopes
  -> Draft (never auto-send) a nudge email          [check_nudges.py]
```

## Why these technical choices

- **Local LLM (Ollama, qwen3:1.7b)** instead of a paid LLM API: zero LLM API cost, no external LLM service dependency, and transcript data stays on the local machine. The model is used only for structured deal extraction; pricing remains deterministic. Runs CPU-only on the development machine.
- **Deterministic pricing**: the LLM only extracts *which* services were discussed — it never sees or computes price. All pricing comes from `rate_card.json` via exact (case-insensitive) name matching. A service name that doesn't match the rate card fails loudly instead of guessing.
- **`deal_id`** is a SHA-256 hash of the normalized transcript (first 12 hex chars) combined with a slug of the client name, computed in Python — not by the LLM — so it is deterministic and reproducible for the same input.
- **DocuSign template, not a generated file**: the MCP workflow used for this project does not expose the template-creation operations we needed, so the reusable template was created manually in the DocuSign console. The implemented send path uses that template and populates classic recipient text tabs at runtime.

## One-time manual setup (not scriptable — see Known DocuSign MCP Limitations below)

1. Create a DocuSign template named `Sales Proposal Template` in the DocuSign console.
2. Add one recipient role: `Client`, with **name/email left blank** (placeholder role, filled per-deal).
3. Add a `Signature` and `Date Signed` field, assigned to `Client`.
4. Add six **Text** fields, all assigned to `Client` (not "Sender" — see limitations below), with these exact labels:
   `ClientName`, `ProjectOverview`, `Scope`, `Deliverables`, `Timeline`, `TotalFee`
5. Save. Get the `templateId` via `getTemplates`.

## Setup

```powershell
ollama pull qwen3:1.7b
python get_docusign_token.py
```

`.env` needs `DOCUSIGN_ACCESS_TOKEN` (written by `get_docusign_token.py`) — demo tokens expire and need refreshing periodically.

## Running the pipeline

```powershell
python extract_deal.py transcript.txt      # -> deal.json
python match_services.py                   # -> priced_deal.json
python render_proposal.py                  # -> generated_proposal.txt (local preview only)
python send_proposal.py                    # creates, fills, and sends the DocuSign envelope
python check_nudges.py                     # run periodically; drafts nudges for 48h+ unsigned envelopes
```

## Safety guarantees

- **No duplicate sends**: `state.json` is checked by `deal_id` before any DocuSign call. A `send_attempted` marker is written *before* the actual send so an ambiguous failure mid-send is never silently retried.
- **No invented data**: empty transcript fields stay empty (never guessed). A missing `client_email` hard-blocks sending — no placeholder or invented email is ever used.
- **No auto-sent nudges**: `check_nudges.py` only ever writes a local draft file. There is no email-sending code path in the script at all.

## Known DocuSign MCP limitations (discovered during build)

- No `createTemplate` tool exists — templates must be built manually in the DocuSign console.
- The "Document Generation / Sender Fields" feature (curly-brace merge fields in a DOCX, via the newer template editor) is **not reachable** through this MCP server — its required endpoints (`getEnvelopeDocGenFormFields` / `updateEnvelopeDocGenFormFields`) aren't among the exposed tools. Fields must instead be classic recipient text tabs (assigned to `Client`), filled via `updateEnvelopeTabs`.
- Several tools (e.g. `getDraftSenderView`) are listed but return `Method not found` when called.
- Some parameters must be passed as strings even when boolean/typed values seem correct (e.g. `include_tabs: "true"`, not `true`).
- `tabId`s are per-envelope, not fixed on the template — they must be rediscovered via `listRecipients` after every new envelope is created.

## Explored but not built (mention-only, per project scope)

- DocuSign MCP + client onboarding
- Stateless MCP + rate-limited internal tool lookup
- Meta Muse + WhatsApp DM response

## Environment

Windows, Python 3.11, 8 GB RAM, Intel UHD integrated graphics, no paid LLM API cost.