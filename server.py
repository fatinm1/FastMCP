from __future__ import annotations

from dotenv import load_dotenv
from fastmcp import FastMCP

from clients import rag, sam, usaspending

load_dotenv()

mcp = FastMCP(
    name="govcon-mcp",
    instructions=(
        "GovCon MCP server providing real-time U.S. federal contracting intelligence. "
        "Tools: search_opportunities (SAM.gov live solicitations), get_opportunity_detail "
        "(full SAM.gov notice), get_award_history (USASpending vendor contracts), "
        "get_vendor_profile (full vendor 360), search_awards_by_naics (NAICS market intel), "
        "get_agency_spending (agency top recipients), get_incumbent (identify incumbents), "
        "ingest_solicitation (index solicitation PDF for RAG), "
        "search_solicitation_content (semantic search over indexed PDFs), "
        "match_past_performance (match RFP requirements to your past performance corpus)."
    ),
)


@mcp.tool
def search_opportunities(
    naics: str | None = None,
    agency: str | None = None,
    keyword: str | None = None,
    set_aside: str | None = None,
    days_back: int = 30,
    limit: int = 10,
) -> dict:
    """Search active U.S. federal contract opportunities from SAM.gov.

    Queries the SAM.gov Opportunities API v2 for solicitations, pre-solicitations,
    and combined synopses posted within the specified window.

    IMPORTANT limitations:
    - `keyword` searches solicitation TITLES only — not full-text body content.
      Use ingest_solicitation + search_solicitation_content for full-text search.
    - `agency` is filtered client-side on the full parent path (e.g. "DEPT OF DEFENSE").
    - No real-time sub-agency filter on the API; pass broad agency names.

    Args:
        naics: NAICS code to filter by (e.g. "541511" for custom programming,
               "541512" for computer systems design, "336411" for aircraft manufacturing).
        agency: Agency name substring, case-insensitive (e.g. "army", "homeland security",
                "health and human services").
        keyword: Title keyword search (e.g. "cybersecurity", "logistics support").
                 Only matches solicitation titles, not full document text.
        set_aside: Small business set-aside code. Options:
                   "SBA" = Small Business, "8A" = 8(a) Program,
                   "HZC" = HUBZone, "SDVOSBC" = Service-Disabled Veteran-Owned,
                   "WOSB" = Women-Owned Small Business.
        days_back: How many days back to search from today (default 30, max ~365).
        limit: Max results to return (default 10, max 1000).

    Returns:
        dict with keys:
          - total: total matching records on SAM.gov
          - returned: number of records in this response
          - opportunities: list of opportunity dicts with notice_id, title, agency,
            naics, set_aside, posted_date, response_deadline, place_of_performance,
            active, sam_url
    """
    try:
        return sam.search_opportunities(
            naics=naics,
            agency=agency,
            keyword=keyword,
            set_aside=set_aside,
            days_back=days_back,
            limit=limit,
        )
    except Exception as exc:
        return {"error": str(exc)}


@mcp.tool
def get_opportunity_detail(notice_id: str) -> dict:
    """Fetch the full details of a single SAM.gov opportunity by notice ID.

    Retrieves the complete record including description, award information,
    point of contact, resource links (PDF attachments), and contract type.

    Use after search_opportunities to get the full solicitation text and
    attachment URLs. Pass the notice_id from search results.

    NOTE: SAM.gov v2 has no single-notice endpoint. This tool searches by
    noticeid param, then retries with solnum if not found.

    Args:
        notice_id: SAM.gov notice ID (e.g. "abc123def456") from search results.
                   Also accepts solicitation numbers (e.g. "W15QKN-26-R-0001").

    Returns:
        dict with all standard fields plus: description, award, point_of_contact,
        links (PDF attachment URLs), contract_type, classification_code.
        Returns {error: "..."} if not found.
    """
    try:
        return sam.get_opportunity_detail(notice_id)
    except Exception as exc:
        return {"error": str(exc)}


@mcp.tool
def get_award_history(
    vendor_name: str,
    limit: int = 10,
    award_type: str = "contracts",
) -> dict:
    """Retrieve federal contract award history for a specific vendor from USASpending.gov.

    Searches by recipient name — partial matches work (e.g. "Leidos" matches
    "Leidos Inc", "Leidos Innovations Corporation"). No API key required.

    Args:
        vendor_name: Company name to search (e.g. "Booz Allen Hamilton", "Leidos",
                     "SAIC", "General Dynamics").
        limit: Max awards to return (default 10, max 100).
        award_type: Type of awards to retrieve:
                    "contracts" (default) — federal contracts (types A/B/C/D),
                    "grants" — federal grants,
                    "all" — contracts and grants combined.

    Returns:
        dict with keys:
          - vendor_name: searched name
          - total_awards_returned: count in this response
          - total_value_in_results: sum of award amounts formatted as "$X,XXX,XXX"
          - awards: list of award dicts with award_id, recipient, amount,
            amount_formatted, start_date, end_date, awarding_agency, sub_agency,
            naics_code, naics_description, description, state
    """
    try:
        return usaspending.get_award_history(vendor_name, limit=limit, award_type=award_type)
    except Exception as exc:
        return {"error": str(exc)}


@mcp.tool
def get_vendor_profile(vendor_name: str) -> dict:
    """Build a comprehensive 360-degree profile of a federal contractor.

    Fetches up to 100 most recent awards and aggregates: total contract value,
    average award size, largest single award, top 5 agencies by spend, top 5
    NAICS codes by frequency, and top 5 individual contracts by value.

    Use for competitive intelligence: understanding a competitor's agency
    relationships, revenue concentration, and contract history.

    Args:
        vendor_name: Company name (e.g. "CACI International", "ManTech", "Peraton").

    Returns:
        dict with keys:
          - vendor_name, total_value, total_awards, average_award, largest_award
          - top_agencies: [{agency, total}] top 5 by spend
          - top_naics: [{naics (code – description), count}] top 5 by frequency
          - top_contracts: top 5 contracts by amount
        Returns {vendor_name, error: "..."} if no awards found.
    """
    try:
        return usaspending.get_vendor_profile(vendor_name)
    except Exception as exc:
        return {"error": str(exc)}


@mcp.tool
def search_awards_by_naics(
    naics_code: str,
    fiscal_year: int = 2024,
    limit: int = 15,
    min_amount: float | None = None,
) -> dict:
    """Search USASpending.gov for federal contract awards by NAICS code.

    Returns awards in a given fiscal year for a specific NAICS, with market
    intelligence including top vendors by total value and unique competitor count.

    Fiscal years run Oct 1 – Sep 30 (FY2024 = Oct 1 2023 – Sep 30 2024).

    Args:
        naics_code: 6-digit NAICS code (e.g. "541511", "541512", "518210").
        fiscal_year: Federal fiscal year (e.g. 2024). Default 2024.
        limit: Max awards to return (default 15).
        min_amount: Optional minimum award amount filter in dollars
                    (e.g. 1000000 for awards >= $1M).

    Returns:
        dict with keys:
          - naics_code, fiscal_year, awards_returned, total_value_in_results
          - unique_vendors_in_results: distinct vendor count
          - top_vendors_by_value: [{vendor, total}] top 5
          - awards: full award list
    """
    try:
        return usaspending.search_awards_by_naics(
            naics_code, fiscal_year=fiscal_year, limit=limit, min_amount=min_amount
        )
    except Exception as exc:
        return {"error": str(exc)}


@mcp.tool
def get_agency_spending(
    agency_name: str,
    fiscal_year: int = 2024,
    limit: int = 10,
) -> dict:
    """Get top contract recipients for a federal agency in a given fiscal year.

    Useful for understanding which vendors dominate a target agency's spend,
    identifying potential teaming partners, and sizing the market.

    Args:
        agency_name: Agency name as it appears in USASpending.gov
                     (e.g. "Department of Defense", "Department of Homeland Security",
                     "Department of Health and Human Services").
        fiscal_year: Federal fiscal year (default 2024).
        limit: Max awards to return (default 10).

    Returns:
        dict with keys:
          - agency, fiscal_year, top_recipients_returned, total_value_in_results
          - top_recipients: [{recipient, amount, amount_formatted, sub_agency,
            naics, description}]
    """
    try:
        return usaspending.get_agency_spending(agency_name, fiscal_year=fiscal_year, limit=limit)
    except Exception as exc:
        return {"error": str(exc)}


@mcp.tool
def get_incumbent(
    agency: str,
    naics_code: str,
    keyword: str | None = None,
    fiscal_year: int = 2024,
) -> dict:
    """Identify likely incumbent contractors at an agency for a given NAICS code.

    Fetches up to 50 awards for the NAICS/fiscal year, then filters client-side
    by agency name and optional keyword in award description. Deduplicates by vendor
    and returns the top 10 by total contract value with contract count and latest
    end date — a strong signal for who holds the current contract.

    Args:
        agency: Agency or sub-agency name substring, case-insensitive
                (e.g. "army corps", "CISA", "naval air systems").
        naics_code: 6-digit NAICS code (e.g. "541511").
        keyword: Optional keyword to filter award descriptions
                 (e.g. "cybersecurity", "logistics").
        fiscal_year: Federal fiscal year (default 2024).

    Returns:
        dict with key "incumbents": list of up to 10 vendors, each with:
          - vendor, total_value, contract_count, latest_contract_end,
            contracts (top 3 individual contracts)
    """
    try:
        raw = usaspending.search_awards_by_naics(naics_code, fiscal_year=fiscal_year, limit=50)
        if "error" in raw:
            return raw

        awards = raw.get("awards", [])
        agency_lower = agency.lower()
        keyword_lower = keyword.lower() if keyword else None

        filtered = []
        for a in awards:
            agency_match = (
                agency_lower in (a.get("awarding_agency") or "").lower()
                or agency_lower in (a.get("sub_agency") or "").lower()
            )
            if not agency_match:
                continue
            if keyword_lower and keyword_lower not in (a.get("description") or "").lower():
                continue
            filtered.append(a)

        vendor_map: dict[str, dict] = {}
        for a in filtered:
            name = a["recipient"]
            if name not in vendor_map:
                vendor_map[name] = {
                    "vendor": name,
                    "total_value": 0,
                    "contract_count": 0,
                    "latest_contract_end": "",
                    "_contracts": [],
                }
            entry = vendor_map[name]
            entry["total_value"] += a["amount"]
            entry["contract_count"] += 1
            if a["end_date"] and a["end_date"] > entry["latest_contract_end"]:
                entry["latest_contract_end"] = a["end_date"]
            entry["_contracts"].append(a)

        top10 = sorted(vendor_map.values(), key=lambda x: x["total_value"], reverse=True)[:10]

        incumbents = []
        for entry in top10:
            top3 = sorted(entry["_contracts"], key=lambda x: x["amount"], reverse=True)[:3]
            incumbents.append(
                {
                    "vendor": entry["vendor"],
                    "total_value": usaspending._fmt_dollars(entry["total_value"]),
                    "contract_count": entry["contract_count"],
                    "latest_contract_end": entry["latest_contract_end"],
                    "contracts": top3,
                }
            )

        return {"incumbents": incumbents}
    except Exception as exc:
        return {"error": str(exc)}


@mcp.tool
def ingest_solicitation(notice_id: str) -> dict:
    """Download and index PDF attachments from a SAM.gov solicitation for semantic search.

    Fetches the full opportunity detail, finds PDF resource links, downloads each
    PDF (up to 3), extracts text with pypdf, chunks it, and stores embeddings in
    ChromaDB. After ingestion, use search_solicitation_content to query the text.

    This is the first step in the RAG workflow for solicitation analysis.

    Args:
        notice_id: SAM.gov notice ID from search_opportunities results.

    Returns:
        dict with notice_id, title, pdfs_processed, total_chunks_ingested, results.
        If no PDFs found, returns a message explaining the limitation.
        Returns {error: "..."} if the notice is not found.
    """
    try:
        detail = sam.get_opportunity_detail(notice_id)
        if "error" in detail:
            return detail

        links = detail.get("links") or []
        pdf_links = [url for url in links if isinstance(url, str) and url.lower().endswith(".pdf")]

        if not pdf_links:
            return {
                "notice_id": notice_id,
                "message": (
                    "No PDF attachments found on this solicitation. "
                    "Not all SAM.gov notices include attached documents."
                ),
            }

        meta = {
            "solicitation_number": detail.get("solicitation_number", ""),
            "title": detail.get("title", ""),
            "agency": detail.get("agency", ""),
        }

        results = []
        total_chunks = 0
        for url in pdf_links[:3]:
            result = rag.ingest_solicitation_pdf(url, notice_id, meta)
            results.append(result)
            total_chunks += result.get("chunks_ingested", 0)

        return {
            "notice_id": notice_id,
            "title": detail.get("title", ""),
            "pdfs_processed": len(results),
            "total_chunks_ingested": total_chunks,
            "results": results,
        }
    except Exception as exc:
        return {"error": str(exc)}


@mcp.tool
def search_solicitation_content(
    query: str,
    notice_id: str | None = None,
    n_results: int = 5,
) -> dict:
    """Semantically search the text of indexed solicitation PDFs.

    Requires prior ingestion via ingest_solicitation. Uses sentence-transformer
    embeddings and ChromaDB cosine similarity to find the most relevant passages.

    Use for: finding specific requirements, evaluation criteria, scope of work,
    period of performance, security clearance requirements, and other details
    buried in solicitation documents.

    Args:
        query: Natural language question or keyword phrase
               (e.g. "security clearance requirements",
                "period of performance duration",
                "small business subcontracting plan").
        notice_id: Optional — filter to a specific solicitation's indexed content.
                   If None, searches across all indexed solicitations.
        n_results: Number of top matching passages to return (default 5).

    Returns:
        dict with query and results list. Each result has: text (the matching
        passage), notice_id, title, agency, distance (lower = more similar),
        chunk_index.
        If nothing indexed, returns a helpful message to run ingest_solicitation first.
    """
    try:
        results = rag.search_solicitations(query, n_results=n_results, notice_id_filter=notice_id)
        if not results:
            return {
                "query": query,
                "results": [],
                "message": "No matching content found. Use ingest_solicitation first.",
            }
        return {"query": query, "results": results}
    except Exception as exc:
        return {"error": str(exc)}


@mcp.tool
def match_past_performance(
    rfp_requirements: str,
    top_k: int = 3,
) -> dict:
    """Match RFP requirements against your indexed past performance narratives.

    Uses semantic similarity to find your most relevant past performance write-ups
    for a given RFP or solicitation. Returns the top matching projects with
    relevance scores and the best matching excerpt.

    NOTE: ingest_past_performance is NOT exposed as an MCP tool.
    # Design rationale: past performance narratives are sensitive proprietary data.
    # Ingestion is a deliberate offline step — BD teams run it directly in Python
    # using clients.rag.ingest_past_performance() before querying via this tool.

    Args:
        rfp_requirements: The RFP requirements text or scope of work description
                          to match against (paste directly from Section C or L/M).
        top_k: Number of top matching past performance projects to return (default 3).

    Returns:
        dict with matches list. Each match has: project_name, contract_number,
        agency, relevance_score (0-100, higher is better), best_matching_excerpt.
        If no past performance is indexed, returns a helpful message with
        instructions to run ingest_past_performance() offline.
    """
    try:
        result = rag.match_rfp_to_past_performance(rfp_requirements, top_k=top_k)
        if not result.get("matches"):
            return {
                "message": (
                    "No past performance narratives indexed. "
                    "Use ingest_past_performance() directly to add your corpus."
                )
            }
        return result
    except Exception as exc:
        return {"error": str(exc)}


if __name__ == "__main__":
    mcp.run()
