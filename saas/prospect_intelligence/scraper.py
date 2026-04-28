"""
Website Intelligence Scraper
Visits each prospect's website and extracts sales intelligence:
- What they do (work types)
- How big they are (project values, fleet mentions)
- Technology stack signals (Vista, Viewpoint, Trimble mentions)
- Pain point signals (language around efficiency, manual processes)
- Key projects to reference in outreach
"""
import re
import json
import logging
import time
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse
from typing import Optional
import anthropic
import requests
from bs4 import BeautifulSoup

log = logging.getLogger("fieldbridge.scraper")

client = anthropic.Anthropic()
MODEL = "claude-sonnet-4-20250514"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; FieldBridge-Research/1.0; "
        "+https://vancontechnologies.com)"
    )
}
TIMEOUT = 15
MAX_PAGES = 5  # about, services, projects, equipment, contact

_SYSTEM_PROMPT = """
You are a sales intelligence analyst for VANCON Technologies, a construction
technology company selling FieldBridge — an AI-powered Vista ERP integration
platform for heavy civil contractors.

Analyze scraped website content and extract actionable sales intelligence.
Focus on:
1. Confirming they are a heavy civil contractor (not residential or commercial GC)
2. Identifying technology signals (Vista/Viewpoint/Trimble mentions = high value)
3. Estimating company scale (fleet size, revenue indicators, employee count)
4. Finding pain point language (manual, paperwork, efficiency, tracking)
5. Identifying best project examples to reference in outreach

Heavy civil = utilities, earthwork, paving, water/wastewater, bridges, site development.
These companies all face the same Vista data-entry pain. That's your angle.
"""

_INTEL_TOOL = {
    "name": "extract_sales_intel",
    "description": "Extract structured sales intelligence from website content",
    "input_schema": {
        "type": "object",
        "properties": {
            "is_heavy_civil": {"type": "boolean"},
            "company_description": {"type": "string", "maxLength": 300},
            "work_types": {
                "type": "array",
                "items": {"type": "string",
                          "enum": ["earthwork", "utilities", "paving", "bridges",
                                   "water", "wastewater", "site_development",
                                   "concrete", "marine", "demolition", "other"]},
            },
            "estimated_fleet_size": {"type": "string",
                                      "enum": ["<25", "25-75", "75-150", "150+", "unknown"]},
            "revenue_signals": {"type": "string", "maxLength": 200},
            "technology_mentions": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Any software/tech mentioned: Vista, Viewpoint, Trimble, etc.",
            },
            "vista_confirmed": {"type": "boolean"},
            "pain_point_signals": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Quotes or phrases suggesting manual processes, tracking pain",
            },
            "notable_projects": {
                "type": "array",
                "items": {"type": "string"},
                "maxItems": 3,
            },
            "key_clients": {
                "type": "array",
                "items": {"type": "string"},
                "description": "DOTs, municipalities, agencies they work for",
            },
            "outreach_angle": {"type": "string", "maxLength": 400,
                                "description": "Suggested personalized opening for Buck's outreach"},
            "fit_score": {"type": "integer", "minimum": 0, "maximum": 100,
                          "description": "Overall fit for FieldBridge (100 = perfect)"},
            "disqualified": {"type": "boolean"},
            "disqualify_reason": {"type": "string"},
        },
        "required": ["is_heavy_civil", "work_types", "fit_score",
                     "outreach_angle", "disqualified"],
    },
}


def _safe_get(url: str) -> Optional[str]:
    """Fetch a URL and return cleaned text. Returns None on failure."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        # Remove nav, footer, scripts, styles
        for tag in soup(["script", "style", "nav", "footer", "header",
                          "noscript", "iframe"]):
            tag.decompose()

        text = soup.get_text(separator=" ", strip=True)
        # Collapse whitespace
        text = re.sub(r'\s+', ' ', text)
        return text[:8000]  # cap at 8K chars per page
    except Exception as e:
        log.debug(f"Failed to fetch {url}: {e}")
        return None


def _discover_pages(base_url: str) -> list[str]:
    """Find the most useful pages to scrape (about, services, projects, equipment)."""
    try:
        resp = requests.get(base_url, headers=HEADERS, timeout=TIMEOUT)
        soup = BeautifulSoup(resp.text, "html.parser")
        links = set()

        target_keywords = ["about", "services", "project", "work", "equipment",
                           "fleet", "capabilities", "what-we-do", "history"]

        for a in soup.find_all("a", href=True):
            href = a["href"].lower()
            if any(kw in href for kw in target_keywords):
                full_url = urljoin(base_url, a["href"])
                # Only same domain
                if urlparse(full_url).netloc == urlparse(base_url).netloc:
                    links.add(full_url)

        return list(links)[:MAX_PAGES]
    except Exception:
        return []


def scrape_company(website: str, company_name: str) -> dict:
    """
    Scrape a company website and return structured sales intelligence.
    Calls Claude to analyze and score the content.
    """
    if not website.startswith("http"):
        website = f"https://{website}"

    log.info(f"Scraping: {company_name} ({website})")

    # Gather content from homepage + key pages
    pages_content = []
    homepage = _safe_get(website)
    if homepage:
        pages_content.append(f"[HOMEPAGE]\n{homepage}")

    sub_pages = _discover_pages(website)
    for url in sub_pages:
        content = _safe_get(url)
        if content:
            page_name = url.replace(website, "").strip("/") or "page"
            pages_content.append(f"[{page_name.upper()}]\n{content}")
        time.sleep(0.5)  # polite crawl delay

    if not pages_content:
        return {
            "error": "Could not fetch website",
            "fit_score": 0,
            "disqualified": True,
            "disqualify_reason": "Website unreachable",
        }

    combined = "\n\n".join(pages_content)[:20000]  # cap total

    # Claude analysis
    response = client.messages.create(
        model=MODEL,
        max_tokens=1500,
        system=[{"type": "text", "text": _SYSTEM_PROMPT,
                 "cache_control": {"type": "ephemeral"}}],
        tools=[_INTEL_TOOL],
        tool_choice={"type": "tool", "name": "extract_sales_intel"},
        messages=[{
            "role": "user",
            "content": (
                f"Company: {company_name}\n"
                f"Website: {website}\n\n"
                f"Scraped content:\n{combined}"
            ),
        }],
    )

    for block in response.content:
        if block.type == "tool_use" and block.name == "extract_sales_intel":
            result = block.input
            result["website"] = website
            result["company_name"] = company_name
            result["scraped_at"] = datetime.now(timezone.utc).isoformat()
            result["pages_scraped"] = len(pages_content)
            return result

    return {
        "error": "Analysis failed",
        "fit_score": 0,
        "disqualified": False,
        "website": website,
    }


def batch_scrape(prospects: list[dict],
                 delay_seconds: float = 2.0) -> list[dict]:
    """
    Scrape a list of prospects.
    Each dict: {company_name, website}
    Returns list of intel dicts.
    """
    results = []
    total = len(prospects)
    for i, p in enumerate(prospects):
        log.info(f"[{i+1}/{total}] {p['company_name']}")
        intel = scrape_company(p["website"], p["company_name"])
        intel["original"] = p
        results.append(intel)
        time.sleep(delay_seconds)
    return results
