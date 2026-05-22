from __future__ import annotations

from collections import defaultdict

import httpx

USA_BASE_URL = "https://api.usaspending.gov/api/v2"

CONTRACT_AWARD_TYPES = ["A", "B", "C", "D"]
GRANT_AWARD_TYPES = ["02", "03", "04", "05"]

AWARD_FIELDS = [
    "Award ID",
    "Recipient Name",
    "Award Amount",
    "Awarding Agency",
    "Awarding Sub Agency",
    "Start Date",
    "End Date",
    "NAICS Code",
    "NAICS Description",
    "Description",
    "Place of Performance State Code",
]


def _fmt_dollars(amount) -> str:
    if amount is None:
        return "$0"
    try:
        return f"${int(round(float(amount))):,}"
    except (TypeError, ValueError):
        return "$0"


def _fiscal_year_dates(fiscal_year: int) -> tuple[str, str]:
    return (f"{fiscal_year - 1}-10-01", f"{fiscal_year}-09-30")


def _build_award_record(row: dict) -> dict:
    amount = row.get("Award Amount", 0) or 0
    return {
        "award_id": row.get("Award ID", ""),
        "recipient": row.get("Recipient Name", ""),
        "amount": amount,
        "amount_formatted": _fmt_dollars(amount),
        "start_date": row.get("Start Date", ""),
        "end_date": row.get("End Date", ""),
        "awarding_agency": row.get("Awarding Agency", ""),
        "sub_agency": row.get("Awarding Sub Agency", ""),
        "naics_code": row.get("NAICS Code", ""),
        "naics_description": row.get("NAICS Description", ""),
        "description": row.get("Description", ""),
        "state": row.get("Place of Performance State Code", ""),
    }


def _post_awards(payload: dict) -> list[dict]:
    try:
        with httpx.Client(timeout=30) as client:
            resp = client.post(f"{USA_BASE_URL}/search/spending_by_award/", json=payload)
            resp.raise_for_status()
            return resp.json().get("results", [])
    except httpx.HTTPStatusError as exc:
        raise RuntimeError(f"USASpending API error: {exc.response.status_code}") from exc
    except httpx.TimeoutException as exc:
        raise RuntimeError("USASpending API request timed out") from exc
    except httpx.HTTPError as exc:
        raise RuntimeError(f"USASpending HTTP error: {exc}") from exc


def get_award_history(
    vendor_name: str,
    limit: int = 10,
    award_type: str = "contracts",
) -> dict:
    if award_type == "contracts":
        types = CONTRACT_AWARD_TYPES
    elif award_type == "grants":
        types = GRANT_AWARD_TYPES
    else:
        types = CONTRACT_AWARD_TYPES + GRANT_AWARD_TYPES

    payload = {
        "filters": {
            "award_type_codes": types,
            "recipient_search_text": [vendor_name],
        },
        "fields": AWARD_FIELDS,
        "sort": "Award Amount",
        "order": "desc",
        "limit": limit,
    }

    try:
        results = _post_awards(payload)
    except RuntimeError as exc:
        return {"error": str(exc)}

    awards = [_build_award_record(r) for r in results]
    total_value = sum(a["amount"] for a in awards)

    return {
        "vendor_name": vendor_name,
        "total_awards_returned": len(awards),
        "total_value_in_results": _fmt_dollars(total_value),
        "awards": awards,
    }


def get_agency_spending(
    agency_name: str,
    fiscal_year: int = 2024,
    limit: int = 10,
) -> dict:
    start, end = _fiscal_year_dates(fiscal_year)

    payload = {
        "filters": {
            "award_type_codes": CONTRACT_AWARD_TYPES,
            "awarding_agency_names": [agency_name],
            "time_period": [{"start_date": start, "end_date": end}],
        },
        "fields": AWARD_FIELDS,
        "sort": "Award Amount",
        "order": "desc",
        "limit": limit,
    }

    try:
        results = _post_awards(payload)
    except RuntimeError as exc:
        return {"error": str(exc)}

    awards = [_build_award_record(r) for r in results]
    total_value = sum(a["amount"] for a in awards)

    recipients: dict[str, dict] = {}
    for a in awards:
        name = a["recipient"]
        if name not in recipients:
            recipients[name] = {
                "recipient": name,
                "amount": 0,
                "sub_agency": a["sub_agency"],
                "naics": a["naics_code"],
                "description": a["description"],
            }
        recipients[name]["amount"] += a["amount"]

    top = sorted(recipients.values(), key=lambda x: x["amount"], reverse=True)
    for r in top:
        r["amount_formatted"] = _fmt_dollars(r["amount"])

    return {
        "agency": agency_name,
        "fiscal_year": fiscal_year,
        "top_recipients_returned": len(top),
        "total_value_in_results": _fmt_dollars(total_value),
        "top_recipients": top,
    }


def search_awards_by_naics(
    naics_code: str,
    fiscal_year: int = 2024,
    limit: int = 15,
    min_amount: float | None = None,
) -> dict:
    start, end = _fiscal_year_dates(fiscal_year)

    filters: dict = {
        "award_type_codes": CONTRACT_AWARD_TYPES,
        "naics_codes": {"require": [naics_code]},
        "time_period": [{"start_date": start, "end_date": end}],
    }
    if min_amount is not None:
        filters["award_amounts"] = [{"lower_bound": min_amount}]

    payload = {
        "filters": filters,
        "fields": AWARD_FIELDS,
        "sort": "Award Amount",
        "order": "desc",
        "limit": limit,
    }

    try:
        results = _post_awards(payload)
    except RuntimeError as exc:
        return {"error": str(exc)}

    awards = [_build_award_record(r) for r in results]
    total_value = sum(a["amount"] for a in awards)

    vendor_totals: dict[str, float] = defaultdict(float)
    for a in awards:
        vendor_totals[a["recipient"]] += a["amount"]

    top_vendors = sorted(vendor_totals.items(), key=lambda x: x[1], reverse=True)[:5]

    return {
        "naics_code": naics_code,
        "fiscal_year": fiscal_year,
        "awards_returned": len(awards),
        "total_value_in_results": _fmt_dollars(total_value),
        "unique_vendors_in_results": len(vendor_totals),
        "top_vendors_by_value": [
            {"vendor": v, "total": _fmt_dollars(t)} for v, t in top_vendors
        ],
        "awards": awards,
    }


def get_vendor_profile(vendor_name: str) -> dict:
    payload = {
        "filters": {
            "award_type_codes": CONTRACT_AWARD_TYPES + GRANT_AWARD_TYPES,
            "recipient_search_text": [vendor_name],
        },
        "fields": AWARD_FIELDS,
        "sort": "Award Amount",
        "order": "desc",
        "limit": 100,
    }

    try:
        results = _post_awards(payload)
    except RuntimeError as exc:
        return {"error": str(exc)}

    if not results:
        return {"vendor_name": vendor_name, "error": "No awards found for this vendor."}

    awards = [_build_award_record(r) for r in results]
    amounts = [a["amount"] for a in awards]
    total_value = sum(amounts)
    avg_award = total_value / len(awards) if awards else 0
    largest = max(amounts) if amounts else 0

    agency_totals: dict[str, float] = defaultdict(float)
    for a in awards:
        agency_totals[a["awarding_agency"]] += a["amount"]
    top_agencies = sorted(agency_totals.items(), key=lambda x: x[1], reverse=True)[:5]

    naics_counts: dict[str, int] = defaultdict(int)
    naics_labels: dict[str, str] = {}
    for a in awards:
        code = a["naics_code"]
        if code:
            naics_counts[code] += 1
            if code not in naics_labels and a["naics_description"]:
                naics_labels[code] = f"{code} – {a['naics_description']}"
    top_naics = sorted(naics_counts.items(), key=lambda x: x[1], reverse=True)[:5]

    top_contracts = sorted(awards, key=lambda x: x["amount"], reverse=True)[:5]

    return {
        "vendor_name": vendor_name,
        "total_value": _fmt_dollars(total_value),
        "total_awards": len(awards),
        "average_award": _fmt_dollars(avg_award),
        "largest_award": _fmt_dollars(largest),
        "top_agencies": [
            {"agency": a, "total": _fmt_dollars(t)} for a, t in top_agencies
        ],
        "top_naics": [
            {"naics": naics_labels.get(code, code), "count": cnt}
            for code, cnt in top_naics
        ],
        "top_contracts": top_contracts,
    }
