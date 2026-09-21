"""
Step 4: Extract structured deal data from a sales call transcript
using a LOCAL Ollama model (qwen3:1.7b). No paid APIs used.

Usage:
    python extract_deal.py transcript.txt
"""

import hashlib
import json
import re
import sys
import urllib.request

OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL = "qwen3:1.7b"

REQUIRED_KEYS = [
    "client_name",
    "client_email",
    "services_discussed",
    "rough_scope",
    "deliverables",
    "timeline",
]

SYSTEM_PROMPT = """
You are a precise sales-call data extraction system.

Read the ENTIRE transcript before producing the JSON.

Your job is to extract facts explicitly present in the transcript.

IMPORTANT EXTRACTION RULES:

1. CLIENT NAME
- Find the customer/company/client name anywhere in the transcript.
- Check the title, heading, introduction, and speaker dialogue.
- A company name in the transcript heading is valid evidence.
- Never leave client_name empty if an explicit company/client name appears.

2. CLIENT EMAIL
- Extract the email only if explicitly stated.
- If no email appears, use "".

3. SERVICES DISCUSSED
- List the actual services/solutions discussed.
- Prefer the canonical service names where the transcript clearly maps to them.
- For example:
  "RAG-based assistant" → "RAG Knowledge Assistant"
  "AI agent workflow" → "AI Agent Development"
- Do not invent services.

4. ROUGH SCOPE
- Summarize the project scope using only facts stated in the transcript.
- Keep it concise.

5. DELIVERABLES
- Extract concrete outputs that were explicitly discussed or clearly agreed.
- Statements such as "we'd scope the RAG assistant, the AI agent workflow,
  deployment, and documentation" are deliverables/scope items and should
  be included.
- Do NOT return [] when explicit deliverables are present.

6. TIMELINE
- Extract the stated timeline.
- Preserve its meaning.

7. PRICING
- NEVER calculate, estimate, or invent pricing.
- Do not include prices in any field.

8. OUTPUT
Return exactly one JSON object matching the supplied schema.
Do not return markdown, explanation, or code fences.

Before finalizing, mentally verify:
- Did I find the client name?
- Did I capture every explicitly discussed service?
- Did I capture the explicit deliverables?
- Did I preserve the stated timeline?
"""


def call_ollama(transcript: str) -> str:
    payload = {
        "model": MODEL,
        "prompt": SYSTEM_PROMPT + "\n\nTRANSCRIPT:\n" + transcript,
        "stream": False,
        "think": False,
        "options": {"temperature": 0},
    }
    req = urllib.request.Request(
        OLLAMA_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=300) as resp:
        body = json.loads(resp.read().decode("utf-8"))

    text = body.get("response", "") or ""
    if not text.strip():
        # Some Ollama versions still route content into "thinking"
        # even with think disabled — fall back to it if response is empty.
        text = body.get("thinking", "") or ""
    return text


def extract_json(raw: str) -> dict:
    raw = raw.strip()
    raw = re.sub(r"^```(json)?", "", raw).strip()
    raw = re.sub(r"```$", "", raw).strip()

    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        raise ValueError("No JSON object found in model output.")
    return json.loads(match.group(0))


def validate(data: dict) -> dict:
    clean = {}
    for key in REQUIRED_KEYS:
        if key not in data:
            raise ValueError(f"Missing required key: {key}")
        clean[key] = data[key]

    if not isinstance(clean["services_discussed"], list):
        raise ValueError("services_discussed must be a list")
    if not isinstance(clean["deliverables"], list):
        raise ValueError("deliverables must be a list")
    for key in ["client_name", "client_email", "rough_scope", "timeline"]:
        if not isinstance(clean[key], str):
            raise ValueError(f"{key} must be a string")

    if not clean["client_name"].strip():
        raise ValueError(
            "client_name is empty. The transcript should contain an explicit client name."
        )

    if not clean["deliverables"]:
        raise ValueError(
            "deliverables is empty. Check whether the transcript contains explicit deliverables."
        )

    return clean


def slugify(name: str) -> str:
    slug = name.strip().lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    return slug.strip("-")


def normalize_transcript(transcript: str) -> str:
    # Normalize line endings and trim outer whitespace so the same
    # transcript content always hashes the same way.
    normalized = transcript.replace("\r\n", "\n").replace("\r", "\n")
    return normalized.strip()


def compute_deal_id(client_name: str, transcript: str) -> str:
    normalized = normalize_transcript(transcript)
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:12]
    return f"{slugify(client_name)}-{digest}"


def main():
    if len(sys.argv) != 2:
        print("Usage: python extract_deal.py <transcript.txt>")
        sys.exit(1)

    transcript_path = sys.argv[1]
    with open(transcript_path, "r", encoding="utf-8") as f:
        transcript = f.read()

    print("Calling local Ollama model:", MODEL)
    raw_output = call_ollama(transcript)

    try:
        data = extract_json(raw_output)
        clean = validate(data)
    except Exception as e:
        print("FAILED to parse valid deal JSON.")
        print("Error:", e)
        print("Raw model output was:")
        print(raw_output)
        sys.exit(1)

    deal_id = compute_deal_id(clean["client_name"], transcript)
    result = {"deal_id": deal_id}
    result.update(clean)

    with open("deal.json", "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    print("SUCCESS: deal.json written.")
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()