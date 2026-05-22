from __future__ import annotations

import io
from unittest.mock import MagicMock, patch

import chromadb
import httpx
import pytest
import respx

import clients.rag as rag


@pytest.fixture(autouse=True)
def ephemeral_rag():
    rag.init_collections(chromadb.EphemeralClient())
    yield


def _words(n: int) -> str:
    return " ".join(f"word{i}" for i in range(n))


def test_chunk_text_basic():
    text = _words(500)
    chunks = rag._chunk_text(text, chunk_size=400, overlap=50)
    assert len(chunks) > 1
    for chunk in chunks:
        assert len(chunk.split()) <= 400
    words0 = set(chunks[0].split()[-50:])
    words1 = set(chunks[1].split()[:50])
    assert len(words0 & words1) > 0


def test_chunk_text_short():
    text = _words(10)
    chunks = rag._chunk_text(text, chunk_size=400, overlap=50)
    assert chunks == [text]


def test_ingest_and_search():
    rag.ingest_past_performance(
        "network security firewall intrusion detection SIEM monitoring",
        "Cybersecurity Operations",
        {"contract_number": "CYB-001", "agency": "DHS"},
    )
    rag.ingest_past_performance(
        "supply chain logistics warehouse inventory transportation management",
        "Logistics Support",
        {"contract_number": "LOG-002", "agency": "Army"},
    )
    rag.ingest_past_performance(
        "cloud migration AWS Azure infrastructure DevOps kubernetes containers",
        "Cloud Modernization",
        {"contract_number": "CLD-003", "agency": "GSA"},
    )

    results = rag.search_past_performance("network security", n_results=3)
    assert len(results) > 0
    top = results[0]["project_name"]
    assert top == "Cybersecurity Operations"


def test_match_rfp_to_past_performance():
    rag.ingest_past_performance(
        "software engineering application development agile scrum python java REST APIs microservices",
        "Software Development Program",
        {"contract_number": "SW-001", "agency": "DoD"},
    )
    rag.ingest_past_performance(
        "physical security guard services access control surveillance cameras badge",
        "Physical Security Services",
        {"contract_number": "SEC-002", "agency": "DHS"},
    )

    result = rag.match_rfp_to_past_performance(
        "software engineering and application development", top_k=2
    )
    matches = result["matches"]
    assert len(matches) > 0
    assert matches[0]["project_name"] == "Software Development Program"
    for m in matches:
        assert 0 <= m["relevance_score"] <= 100


def test_collection_stats():
    rag.ingest_past_performance(
        "test past performance narrative content here",
        "Test Project",
        {"contract_number": "TST-001", "agency": "Test Agency"},
    )

    stats = rag.get_collection_stats()
    assert "solicitations" in stats
    assert "past_performance" in stats
    assert stats["past_performance"]["count"] >= 1


@respx.mock
def test_ingest_empty_pdf_text():
    pdf_url = "https://example.gov/solicitation.pdf"
    respx.get(pdf_url).mock(return_value=httpx.Response(200, content=b"%PDF-1.4 empty"))

    mock_reader = MagicMock()
    mock_reader.pages = []

    with patch("clients.rag.PdfReader", return_value=mock_reader):
        result = rag.ingest_solicitation_pdf(
            pdf_url, "test123", {"title": "Test", "agency": "Test Agency"}
        )

    assert "error" in result
