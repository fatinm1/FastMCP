from __future__ import annotations

import os
from datetime import datetime, timezone

import httpx
from dotenv import load_dotenv

load_dotenv()

SAM_BASE_URL = "https://api.sam.gov/prod/opportunities/v2/search"


def _api_key() -> str:
    key = os.getenv("SAM_API_KEY", "")
    if not key:
        raise RuntimeError(
            "SAM_API_KEY is not set. Get a free key at https://sam.gov/profile/details"
        )
    return key


def _default_date_range(days_back: int = 30) -> tuple[str, str]:
    now = datetime.now(timezone.utc)
    from datetime import timedelta

    posted_from = now - timedelta(days=days_back)
    return (
        posted_from.strftime("%m/%d/%Y"),
        now.strftime("%m/%d/%Y"),
    )


def _clean_opportunity(raw: dict, full: bool = False) -> dict:
    pop = raw.get("placeOfPerformance") or {}
    city = (pop.get("city") or {}).get("name", "")

    result: dict = {
        "notice_id": raw.get("noticeId", ""),
        "solicitation_number": raw.get("solicitationNumber", ""),
        "title": raw.get("title", ""),
        "agency": raw.get("fullParentPathName", ""),
        "office": raw.get("organizationName", ""),
        "naics": raw.get("naicsCode", ""),
        "type": raw.get("type", ""),
        "set_aside": raw.get("typeOfSetAside", ""),
        "posted_date": raw.get("postedDate", ""),
        "response_deadline": raw.get("responseDeadLine", ""),
        "place_of_performance": city,
        "active": raw.get("active", ""),
        "sam_url": f"https://sam.gov/opp/{raw.get('noticeId', '')}/view",
    }

    if full:
        result["description"] = raw.get("description", "")
        result["award"] = raw.get("award")
        result["point_of_contact"] = raw.get("pointOfContact")
        result["links"] = raw.get("resourceLinks", [])
        result["contract_type"] = raw.get("contractType", "")
        result["classification_code"] = raw.get("classificationCode", "")

    return result


def search_opportunities(
    naics: str | None = None,
    agency: str | None = None,
    keyword: str | None = None,
    set_aside: str | None = None,
    days_back: int = 30,
    limit: int = 10,
    active_only: bool = True,
) -> dict:
    api_key = _api_key()
    posted_from, posted_to = _default_date_range(days_back)

    params: dict = {
        "api_key": api_key,
        "limit": limit,
        "postedFrom": posted_from,
        "postedTo": posted_to,
        "ptype": "o,p,k",
    }

    if naics:
        params["naics"] = naics
    if keyword:
        params["title"] = keyword
    if set_aside:
        params["typeOfSetAside"] = set_aside
    if active_only:
        params["active"] = "Yes"

    try:
        with httpx.Client(timeout=30) as client:
            resp = client.get(SAM_BASE_URL, params=params)
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPStatusError as exc:
        return {"error": f"SAM.gov API error: {exc.response.status_code} {exc.response.text[:200]}"}
    except httpx.TimeoutException:
        return {"error": "SAM.gov API request timed out"}
    except httpx.HTTPError as exc:
        return {"error": f"SAM.gov HTTP error: {exc}"}

    opportunities = data.get("opportunitiesData", [])

    if agency:
        agency_lower = agency.lower()
        opportunities = [
            opp for opp in opportunities
            if agency_lower in (opp.get("fullParentPathName") or "").lower()
        ]

    cleaned = [_clean_opportunity(opp) for opp in opportunities]

    return {
        "total": data.get("totalRecords", 0),
        "returned": len(cleaned),
        "opportunities": cleaned,
    }


def get_opportunity_detail(notice_id: str) -> dict:
    api_key = _api_key()

    try:
        with httpx.Client(timeout=30) as client:
            resp = client.get(SAM_BASE_URL, params={"api_key": api_key, "noticeid": notice_id})
            resp.raise_for_status()
            data = resp.json()

            opportunities = data.get("opportunitiesData", [])

            if not opportunities:
                resp2 = client.get(SAM_BASE_URL, params={"api_key": api_key, "solnum": notice_id})
                resp2.raise_for_status()
                data2 = resp2.json()
                opportunities = data2.get("opportunitiesData", [])

    except httpx.HTTPStatusError as exc:
        return {"error": f"SAM.gov API error: {exc.response.status_code}"}
    except httpx.TimeoutException:
        return {"error": "SAM.gov API request timed out"}
    except httpx.HTTPError as exc:
        return {"error": f"SAM.gov HTTP error: {exc}"}

    if not opportunities:
        return {"error": f"No opportunity found for notice_id: {notice_id}"}

    return _clean_opportunity(opportunities[0], full=True)
