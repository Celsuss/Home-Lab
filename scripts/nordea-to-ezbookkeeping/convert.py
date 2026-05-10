#!/usr/bin/env python3
"""
Nordea CSV → ezbookkeeping CSV converter.

Usage:
    python convert.py nordea_export.csv output.csv
    python convert.py nordea_export.csv output.csv --categories categories.yaml

The output CSV can be imported via ezbookkeeping UI:
    Settings → Import → CSV → map columns as prompted.

Column mapping for ezbookkeeping UI import:
    Time          → Transaction Time
    Type          → Transaction Type
    Category      → Category
    Sub Category  → Sub Category
    Account       → Account
    Amount        → Amount
    Comment       → Comment / Description
"""

import argparse
import csv
import re
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path

import yaml


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def load_categories(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    # Provide safe defaults for missing keys
    data.setdefault("rules", [])
    data.setdefault("default_category", "Uncategorized")
    data.setdefault("default_sub_category", "")
    data.setdefault("account_name", "Nordea Checking")
    return data


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def parse_amount(raw: str) -> Decimal:
    """Parse Swedish number format: '−1 234,56' or '1 234,56' → Decimal."""
    # Replace non-breaking spaces and regular spaces (thousands separator)
    cleaned = raw.strip().replace(" ", "").replace(" ", "")
    # Swedish decimal comma → dot
    cleaned = cleaned.replace(",", ".")
    # Handle minus sign variants (e.g. Unicode minus U+2212)
    cleaned = cleaned.replace("−", "-")
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        raise ValueError(f"Cannot parse amount: {raw!r}")


def determine_type(amount: Decimal) -> str:
    return "Income" if amount >= 0 else "Expense"


def build_comment(row: dict) -> str:
    """Combine Namn and Rubrik into a readable comment, skipping empty values."""
    parts = [row.get("Namn", ""), row.get("Rubrik", "")]
    non_empty = [p.strip() for p in parts if p.strip()]
    return " - ".join(non_empty)


# ---------------------------------------------------------------------------
# Category matching
# ---------------------------------------------------------------------------

def _field_value(row: dict, field: str) -> str:
    """Return the value of the requested Nordea field (lowercased for matching)."""
    mapping = {
        "namn": row.get("Namn", ""),
        "mottagare": row.get("Mottagare", ""),
        "rubrik": row.get("Rubrik", ""),
        "avsändare": row.get("Avsändare", ""),
    }
    return mapping.get(field.lower(), "").lower()


def _matches(rule: dict, row: dict) -> bool:
    pattern = rule.get("pattern", "")
    use_regex = rule.get("regex", False)
    match_field = rule.get("match_field", "any").lower()

    if match_field == "any":
        fields_to_check = ["namn", "mottagare", "rubrik", "avsändare"]
    else:
        fields_to_check = [match_field]

    for field in fields_to_check:
        value = _field_value(row, field)
        if use_regex:
            if re.search(pattern, value, re.IGNORECASE):
                return True
        else:
            if pattern.lower() in value:
                return True
    return False


def apply_rules(rules: list, row: dict) -> tuple[str, str]:
    """Return (category, sub_category) for the first matching rule."""
    for rule in rules:
        if _matches(rule, row):
            return rule.get("category", ""), rule.get("sub_category", "")
    return "", ""


# ---------------------------------------------------------------------------
# Conversion
# ---------------------------------------------------------------------------

def convert(input_path: Path, output_path: Path, categories_path: Path) -> None:
    config = load_categories(categories_path)
    rules = config["rules"]
    default_category = config["default_category"]
    default_sub_category = config["default_sub_category"]
    account_name = config["account_name"]

    output_rows = []
    skipped = 0

    with open(input_path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f, delimiter=";")

        # Strip whitespace from header names (Nordea sometimes pads them)
        reader.fieldnames = [h.strip() for h in reader.fieldnames] if reader.fieldnames else []

        for line_num, row in enumerate(reader, start=2):
            # Skip completely empty rows
            if not any(v.strip() for v in row.values()):
                skipped += 1
                continue

            raw_amount = row.get("Belopp", "").strip()
            if not raw_amount:
                print(f"  Warning: line {line_num} has no amount, skipping.", file=sys.stderr)
                skipped += 1
                continue

            try:
                amount = parse_amount(raw_amount)
            except ValueError as e:
                print(f"  Warning: line {line_num}: {e}, skipping.", file=sys.stderr)
                skipped += 1
                continue

            transaction_type = determine_type(amount)
            comment = build_comment(row)
            category, sub_category = apply_rules(rules, row)

            if not category:
                category = default_category
                sub_category = default_sub_category

            output_rows.append({
                "Time": row.get("Bokföringsdag", "").strip(),
                "Type": transaction_type,
                "Category": category,
                "Sub Category": sub_category,
                "Account": account_name,
                "Amount": str(abs(amount)),
                "Comment": comment,
            })

    with open(output_path, "w", encoding="utf-8", newline="") as f:
        fieldnames = ["Time", "Type", "Category", "Sub Category", "Account", "Amount", "Comment"]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(output_rows)

    uncategorized = sum(1 for r in output_rows if r["Category"] == default_category)
    print(f"Converted {len(output_rows)} transactions → {output_path}")
    if skipped:
        print(f"  Skipped: {skipped} rows (empty or unparseable)")
    if uncategorized:
        print(f"  Uncategorized: {uncategorized} rows — update categories.yaml to reduce this")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Convert Nordea CSV export to ezbookkeeping import CSV."
    )
    parser.add_argument("input", type=Path, help="Nordea export (.csv, semicolon-delimited)")
    parser.add_argument("output", type=Path, help="Output CSV for ezbookkeeping import")
    parser.add_argument(
        "--categories",
        type=Path,
        default=Path(__file__).parent / "categories.yaml",
        help="Path to categories.yaml (default: same directory as this script)",
    )
    args = parser.parse_args()

    if not args.input.exists():
        print(f"Error: input file not found: {args.input}", file=sys.stderr)
        sys.exit(1)
    if not args.categories.exists():
        print(f"Error: categories file not found: {args.categories}", file=sys.stderr)
        sys.exit(1)

    convert(args.input, args.output, args.categories)


if __name__ == "__main__":
    main()
