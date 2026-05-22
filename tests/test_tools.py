from __future__ import annotations

import os

import httpx
import pytest
import respx

from clients.sam import _clean_opportunity, search_opportunities
from clients.usaspending import _fmt_dollars, get_award_history, get_vendor_profile

SAM_URL = "https://api.sam.gov/prod/opportunities/v2/search"
USA_URL = "https://api.usaspending.gov/api/v2/search/spending_by_award/"

MOCK_SAM_RESPONSE = {
    "totalRecords": 2,
    "opportunitiesData": [
        {
            "noticeId": "abc123",
            "solicitationNumber": "W15QKN-26-R-0001",
            "title": "Cybersecurity Support Services",
            "fullParentPathName": "DEPT OF DEFENSE.DEPT OF THE ARMY",
            "organizationName": "PEO C3T",
            "naicsCode": "541512",
            "type": "Solicitation",
            "typeOfSetAside": "SBA",
            "postedDate": "2026-05-01",
            "responseDeadLine": "2026-06-01T17:00:00-04:00",
            "placeOfPerformance": {"city": {"name": "Fort Meade"}},
            "active": "Yes",
            "description": "",
            "award": None,
            "pointOfContact": [],
            "resourceLinks": [],
            "contractType": "",
            "classificationCode": "",
        },
        {
            "noticeId": "def456",
            "solicitationNumber": "70RSAT-26-R-0002",
            "title": "Cloud Infrastructure Modernization",
            "fullParentPathName": "DEPT OF HOMELAND SECURITY.CISA",
            "organizationName": "CISA",
            "naicsCode": "541511",
            "type": "Solicitation",
            "typeOfSetAside": "NONE",
            "postedDate": "2026-05-10",
            "responseDeadLine": "2026-06-15T17:00:00-04:00",
            "placeOfPerformance": {"city": {"name": "Arlington"}},
            "active": "Yes",
            "description": "",
            "award": None,
            "pointOfContact": [],
            "resourceLinks": [],
            "contractType": "",
            "classificationCode": "",
        },
    ],
}

MOCK_USA_AWARDS = {
    "results": [
        {
            "Award ID": "W912DR-24-C-0001",
            "Recipient Name": "ACME Federal Solutions",
            "Award Amount": 5000000,
            "Awarding Agency": "Department of Defense",
            "Awarding Sub Agency": "Army Corps of Engineers",
            "Start Date": "2024-01-15",
            "End Date": "2026-01-14",
            "NAICS Code": "541512",
            "NAICS Description": "Computer Systems Design Services",
            "Description": "IT modernization support",
            "Place of Performance State Code": "VA",
        },
        {
            "Award ID": "70RSAT-24-C-0002",
            "Recipient Name": "ACME Federal Solutions",
            "Award Amount": 2500000,
            "Awarding Agency": "Department of Homeland Security",
            "Awarding Sub Agency": "CISA",
            "Start Date": "2024-03-01",
            "End Date": "2025-02-28",
            "NAICS Code": "541519",
            "NAICS Description": "Other Computer Related Services",
            "Description": "Cybersecurity advisory",
            "Place of Performance State Code": "MD",
        },
    ]
}


@respx.mock
def test_search_opportunities_mock():
    os.environ["SAM_API_KEY"] = "test_key"
    respx.get(SAM_URL).mock(return_value=httpx.Response(200, json=MOCK_SAM_RESPONSE))

    result = search_opportunities(limit=10)

    assert result["total"] == 2
    assert len(result["opportunities"]) == 2
    assert result["opportunities"][0]["title"] == "Cybersecurity Support Services"
    assert "sam.gov" in result["opportunities"][0]["sam_url"]


@respx.mock
def test_search_opportunities_agency_filter():
    os.environ["SAM_API_KEY"] = "test_key"
    respx.get(SAM_URL).mock(return_value=httpx.Response(200, json=MOCK_SAM_RESPONSE))

    result = search_opportunities(agency="homeland security", limit=10)

    assert len(result["opportunities"]) == 1
    assert "HOMELAND" in result["opportunities"][0]["agency"].upper()


@respx.mock
def test_get_award_history_mock():
    respx.post(USA_URL).mock(return_value=httpx.Response(200, json=MOCK_USA_AWARDS))

    result = get_award_history("ACME Federal Solutions")

    assert result["vendor_name"] == "ACME Federal Solutions"
    assert result["total_awards_returned"] == 2
    assert result["awards"][0]["amount"] == 5000000
    assert result["awards"][0]["amount_formatted"] == "$5,000,000"


@respx.mock
def test_vendor_profile_mock():
    respx.post(USA_URL).mock(return_value=httpx.Response(200, json=MOCK_USA_AWARDS))

    result = get_vendor_profile("ACME Federal Solutions")

    assert result["total_value"] == "$7,500,000"
    assert result["largest_award"] == "$5,000,000"
    assert len(result["top_agencies"]) > 0


def test_fmt_dollars():
    assert _fmt_dollars(1_000_000) == "$1,000,000"
    assert _fmt_dollars(0) == "$0"
    assert _fmt_dollars(None) == "$0"
    assert _fmt_dollars(1234567.89) == "$1,234,568"


def test_clean_opportunity():
    raw = MOCK_SAM_RESPONSE["opportunitiesData"][0]
    result = _clean_opportunity(raw)

    assert result["notice_id"] == "abc123"
    assert result["title"] == "Cybersecurity Support Services"
    assert result["naics"] == "541512"
    assert result["set_aside"] == "SBA"
    assert result["sam_url"] == "https://sam.gov/opp/abc123/view"


@pytest.mark.skipif(not os.getenv("SAM_API_KEY"), reason="SAM_API_KEY not set")
def test_live_sam_search():
    from clients.sam import search_opportunities as live_search

    result = live_search(naics="541511", limit=3, days_back=60)
    assert "opportunities" in result
    assert isinstance(result["opportunities"], list)


@pytest.mark.skipif(not os.getenv("SAM_API_KEY"), reason="SAM_API_KEY not set")
def test_live_usaspending_awards():
    from clients.usaspending import get_award_history as live_awards

    result = live_awards("Leidos", limit=5)
    assert len(result["awards"]) > 0
