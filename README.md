# govcon-mcp

> **Real-time U.S. federal contracting intelligence for AI agents** — SAM.gov + USASpending.gov + RAG

![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)
![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)
![MCP](https://img.shields.io/badge/MCP-FastMCP%202.x-purple.svg)

---

## What this is

Government contracting (GovCon) business development teams spend hours every week
manually searching SAM.gov for new opportunities, cross-referencing USASpending.gov
to understand the competitive landscape, and sifting through solicitation PDFs to
extract requirements buried in hundreds of pages. This work is repetitive, time-consuming,
and poorly suited to human cognition — but ideal for AI agents.

**govcon-mcp** is a production-ready Model Context Protocol (MCP) server that wraps
the two most important free public U.S. federal contracting APIs — SAM.gov and
USASpending.gov — into clean, agent-callable tools. Any AI agent that speaks MCP
(Claude Desktop, Cursor, LangGraph, CrewAI) can immediately answer capture questions
like "Who holds the incumbent contract?" or "What's DHS spending in our NAICS?"
without any custom integration work.

The server also includes a RAG (Retrieval-Augmented Generation) layer backed by
ChromaDB and sentence-transformers. This lets agents semantically search the actual
text of solicitation PDFs and your firm's past performance write-ups — the unstructured
content that no API filter can reach. Ask "What are the security clearance requirements?"
and get the exact paragraph from the PWS.

---

## Tools

| Tool | Type | Data Source | What it does |
|------|------|-------------|--------------|
| `search_opportunities` | Live API | SAM.gov | Search active solicitations, pre-solicitations, and combined synopses by NAICS, agency, keyword, and set-aside code |
| `get_opportunity_detail` | Live API | SAM.gov | Fetch full details of a specific notice including description, POC, and PDF attachment links |
| `get_award_history` | Live API | USASpending.gov | Retrieve contract award history for a named vendor, sorted by value |
| `get_vendor_profile` | Live API | USASpending.gov | 360° competitive profile: total value, top agencies, top NAICS, top contracts |
| `search_awards_by_naics` | Live API | USASpending.gov | Market intelligence for a NAICS code: top vendors, total spend, unique competitors |
| `get_agency_spending` | Live API | USASpending.gov | Top contract recipients for an agency in a given fiscal year |
| `get_incumbent` | Live API | USASpending.gov | Identify likely incumbent contractors at an agency for a NAICS code |
| `ingest_solicitation` | RAG | SAM.gov PDFs | Download and index solicitation PDF attachments into ChromaDB for semantic search |
| `search_solicitation_content` | RAG | ChromaDB | Semantically search indexed solicitation text for specific requirements |
| `match_past_performance` | RAG | ChromaDB | Match RFP requirements to your firm's indexed past performance narratives |

---

## RAG Features

### What gets indexed

Two ChromaDB collections store your GovCon intelligence corpus:

- **`solicitations`** — Text extracted from SAM.gov solicitation PDFs (PWS, SOW, Section L/M). Indexed after calling `ingest_solicitation`.
- **`past_performance`** — Your firm's past performance narratives and CPARS write-ups. Indexed via the offline `ingest_past_performance()` Python function.

### Embedding model

`all-MiniLM-L6-v2` from sentence-transformers — fast, accurate, runs locally, no API key required. Loaded once at module startup.

### End-to-end workflow example

1. **Discover** — `search_opportunities(naics="541511", agency="army")` → find relevant solicitations
2. **Detail** — `get_opportunity_detail("abc123")` → get full record with PDF links
3. **Ingest** — `ingest_solicitation("abc123")` → download + index solicitation PDFs
4. **Search** — `search_solicitation_content("security clearance requirements", notice_id="abc123")` → find exact requirements
5. **Match** — `match_past_performance("cloud infrastructure modernization for DoD")` → surface your best past performance

---

## Quickstart

### 1. Get a SAM.gov API key

Register for a free key at [sam.gov/profile/details](https://sam.gov/profile/details).
USASpending.gov requires no key.

### 2. Install

```bash
# With uv (recommended)
uv pip install -e ".[dev]"

# Or with pip
pip install -e ".[dev]"
```

### 3. Configure environment

```bash
cp .env.example .env
# Edit .env and add your SAM_API_KEY
```

### 4. Run the server

```bash
# stdio (default — for Claude Desktop / MCP clients)
python server.py

# Or via installed script
govcon-mcp
```

---

## Claude Desktop Integration

Add to `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "govcon-mcp": {
      "command": "python",
      "args": ["/absolute/path/to/FastMCP/server.py"],
      "env": {
        "SAM_API_KEY": "your_sam_gov_api_key_here"
      }
    }
  }
}
```

---

## Example agent queries

1. "Find active cybersecurity solicitations at DHS posted in the last 30 days."
2. "Who are the top 5 vendors for NAICS 541512 at the Department of Defense in FY2024?"
3. "Show me Leidos's full federal contract profile — agencies, NAICS, and top awards."
4. "Who is the likely incumbent on IT support services (NAICS 541513) at the Army Corps of Engineers?"
5. "Search the indexed solicitation for 'period of performance' and 'option years'."
6. "What security clearance level is required in this RFP?"
7. "Match this SOW to our past performance: 'cloud migration and DevSecOps support for a federal civilian agency.'"
8. "What is DHS spending on professional services (541600) this fiscal year and who are the top recipients?"

---

## Data Sources

| Source | Coverage | Auth Required | Rate Limit | Notes |
|--------|----------|---------------|-----------|-------|
| SAM.gov Opportunities API v2 | All federal solicitations, pre-solicitations, combined synopses | Free API key | 1,000 req/day | Title-only keyword search; no `/id` endpoint |
| USASpending.gov API v2 | All USAspending contract awards FY2008–present | None | None published | Fiscal year = Oct 1 – Sep 30 |
| ChromaDB (local) | Your indexed PDFs and past performance | None | N/A | Stored at `./.chroma` |

---

## Architecture

```
FastMCP/
├── server.py                  # FastMCP server — all 10 tool definitions
├── clients/
│   ├── __init__.py
│   ├── sam.py                 # SAM.gov API v2 wrapper with client-side agency filtering
│   ├── usaspending.py         # USASpending.gov API wrapper with dollar formatting helpers
│   └── rag.py                 # ChromaDB + sentence-transformers RAG client
├── tests/
│   ├── __init__.py
│   ├── test_tools.py          # Unit + integration tests for SAM/USASpending (respx mocks)
│   └── test_rag.py            # RAG unit tests using EphemeralClient
├── .env.example               # Environment variable template
├── .gitignore
├── pyproject.toml             # Project metadata and dependencies
└── README.md
```

**Two-layer architecture:**

- **Live API layer** (`clients/sam.py`, `clients/usaspending.py`) — synchronous httpx wrappers around public government APIs. No caching, no async, no external services beyond the APIs themselves.
- **RAG layer** (`clients/rag.py`) — local ChromaDB vector store with sentence-transformer embeddings. All computation runs on-device; no external ML API calls.

---

## Transport Options

| Transport | Use Case | Command |
|-----------|----------|---------|
| `stdio` | Claude Desktop, Cursor, most MCP clients | `python server.py` |
| `streamable-http` | Web agents, LangGraph, custom integrations | `python server.py --transport streamable-http --port 8000` |
| `sse` | Server-Sent Events streaming clients | `python server.py --transport sse --port 8000` |

---

## Ingesting Past Performance

Past performance ingestion is an **offline step** — not exposed as an MCP tool because
past performance narratives are sensitive proprietary data that BD teams control directly.

```python
from clients.rag import ingest_past_performance, init_collections

# Optional: call with no args to use the default PersistentClient at ./.chroma
init_collections()

# Ingest a past performance write-up
result = ingest_past_performance(
    text="""
    Delivered a zero-downtime cloud migration of 47 legacy applications to AWS GovCloud
    for a DHS component agency. Leveraged AWS Migration Hub, Terraform IaC, and a
    DevSecOps pipeline (GitLab CI/CD + Prisma Cloud) to achieve FedRAMP High authorization.
    Performance period: 24 months. Final cost: $4.2M against a $4.5M ceiling.
    """,
    project_name="DHS Cloud Migration",
    metadata={
        "contract_number": "70RSAT-22-C-0001",
        "agency": "Department of Homeland Security",
        "period": "2022-2024",
        "naics": "518210",
    },
)

print(result)
# {'project_name': 'DHS Cloud Migration', 'chunks_ingested': 1}
```

Once ingested, call `match_past_performance` from any MCP client to surface relevant narratives.

---

## Roadmap

1. **FPDS bulk data** — nightly sync of Federal Procurement Data System for complete award history
2. **CPARS lookup** — automated contractor performance rating retrieval
3. **Teaming partner finder** — identify small businesses with complementary NAICS in target agencies
4. **Fit scorer** — score a solicitation against your firm's past performance portfolio (0–100)
5. **Redis caching** — cache SAM.gov and USASpending responses to reduce API calls
6. **GSA eBuy** — add GSA eBuy RFQ monitoring for schedule holders
7. **Automated PP ingestion** — watch a folder for new past performance PDFs and auto-ingest
8. **Section L/M compliance matrix** — extract evaluation criteria and auto-generate a compliance matrix

---

## License

MIT — see [LICENSE](LICENSE) file.
