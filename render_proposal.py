from pathlib import Path
import json
from jinja2 import Environment, FileSystemLoader

BASE_DIR = Path(__file__).resolve().parent

# EDIT THESE TWO to your actual sender identity — shown on every proposal.
SENDER_COMPANY_NAME = "Crework Labs"
SENDER_NAME = "Crework Sales Agent"

PRICED_DEAL_FILE = BASE_DIR / "priced_deal.json"


def load_priced_deal():
    with open(PRICED_DEAL_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def render_proposal():
    priced_deal = load_priced_deal()

    environment = Environment(
        loader=FileSystemLoader(BASE_DIR),
        autoescape=False,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    template = environment.get_template("proposal_template.j2")

    services = [
        {"name": s["name"], "scope": s["scope"]}
        for s in priced_deal["matched_services"]
    ]

    data = {
        "company_name": SENDER_COMPANY_NAME,
        "client_name": priced_deal["client_name"],
        "sender_name": SENDER_NAME,
        "project_summary": priced_deal["rough_scope"],
        "services": services,
        "deliverables": priced_deal["deliverables"],
        "currency": priced_deal["currency"],
        "total_price": priced_deal["total_price"],
        "timeline": priced_deal["timeline"],
    }

    output = template.render(**data)

    output_file = BASE_DIR / "generated_proposal.txt"
    output_file.write_text(output, encoding="utf-8")

    print("=" * 60)
    print("PROPOSAL RENDER")
    print("=" * 60)
    print(f"Deal ID: {priced_deal['deal_id']}")
    print(f"Client: {priced_deal['client_name']}")
    print(f"Selected services: {len(services)}")
    print(f"Total price: {data['currency']} {data['total_price']}")
    print(f"Output: {output_file}")
    print("\nSUCCESS: Proposal generated.")
    print("\n--- PREVIEW ---\n")
    print(output)


if __name__ == "__main__":
    render_proposal()