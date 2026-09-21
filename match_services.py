"""
Step 5 (part 1): Match deal.json services to rate_card.json deterministically
and compute total price. No LLM involved — exact lookup only, no fuzzy
matching, no invented prices.

Usage:
    python match_services.py
"""

import json
import sys

DEAL_FILE = "deal.json"
RATE_CARD_FILE = "rate_card.json"
OUTPUT_FILE = "priced_deal.json"


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def build_rate_lookup(rate_card: dict) -> dict:
    lookup = {}
    for key, entry in rate_card["services"].items():
        lookup[entry["name"].strip().lower()] = {
            "key": key,
            "name": entry["name"],
            "price": entry["price"],
            "scope": entry["typical_scope"],
        }
    return lookup


def match_services(services_discussed: list, lookup: dict) -> list:
    matched = []
    unmatched = []
    for service in services_discussed:
        hit = lookup.get(service.strip().lower())
        if hit is None:
            unmatched.append(service)
        else:
            matched.append(hit)

    if unmatched:
        available = ", ".join(sorted(v["name"] for v in lookup.values()))
        raise ValueError(
            f"Unmatched service(s) not found in rate_card.json: {unmatched}. "
            f"Available services: {available}"
        )

    return matched


def main():
    deal = load_json(DEAL_FILE)
    rate_card = load_json(RATE_CARD_FILE)

    lookup = build_rate_lookup(rate_card)

    try:
        matched = match_services(deal["services_discussed"], lookup)
    except ValueError as e:
        print("FAILED to match services to rate_card.json.")
        print("Error:", e)
        sys.exit(1)

    total_price = sum(item["price"] for item in matched)

    priced_deal = dict(deal)  # carries forward deal_id, client_name, etc.
    priced_deal["matched_services"] = matched
    priced_deal["currency"] = rate_card["currency"]
    priced_deal["total_price"] = total_price

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(priced_deal, f, indent=2, ensure_ascii=False)

    print("SUCCESS: priced_deal.json written.")
    print(json.dumps(priced_deal, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()