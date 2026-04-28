"""
Apollo.io API client for contact enrichment.
Finds decision-makers at target heavy civil contractors.

Docs: https://apolloio.github.io/apollo-api-docs/
Requires APOLLO_API_KEY in environment.

Target roles for FieldBridge outreach:
- CEO, President, COO (budget authority)
- CFO, Controller (approves tech spend)
- VP Operations, VP Technology (power users)
- Director of IT (tech evaluator)
"""
import logging
import os
import time
from typing import Optional
import requests

log = logging.getLogger("fieldbridge.apollo")

APOLLO_BASE = "https://api.apollo.io/v1"
API_KEY = os.getenv("APOLLO_API_KEY", "")

# Roles worth enriching — ordered by outreach priority
TARGET_TITLES = [
    "CEO", "President", "Chief Executive Officer",
    "COO", "Chief Operating Officer",
    "CFO", "Chief Financial Officer", "Controller",
    "CTO", "Chief Technology Officer",
    "VP Operations", "Vice President Operations",
    "VP Technology", "Vice President Technology",
    "Director of IT", "Director of Information Technology",
    "Director of Operations",
    "Project Executive",
    "Equipment Manager",
]

SENIORITY_FILTER = ["c_suite", "vp", "director", "manager"]

_SESSION = requests.Session()
_SESSION.headers.update({
    "Content-Type": "application/json",
    "Cache-Control": "no-cache",
})


def _post(endpoint: str, payload: dict) -> dict:
    """POST to Apollo API with key. Raises on non-200."""
    url = f"{APOLLO_BASE}/{endpoint}"
    payload["api_key"] = API_KEY
    resp = _SESSION.post(url, json=payload, timeout=20)
    if resp.status_code == 429:
        log.warning("Apollo rate limit hit — sleeping 60s")
        time.sleep(60)
        resp = _SESSION.post(url, json=payload, timeout=20)
    resp.raise_for_status()
    return resp.json()


def search_org(company_name: str, domain: str = "") -> Optional[dict]:
    """
    Look up an organization in Apollo by name or domain.
    Returns Apollo org record or None.
    """
    try:
        payload: dict = {"q_organization_name": company_name, "page": 1, "per_page": 1}
        if domain:
            payload["q_organization_domains[]"] = [domain]

        data = _post("organizations/search", payload)
        orgs = data.get("organizations") or []
        if orgs:
            org = orgs[0]
            log.debug(f"Found Apollo org: {org.get('name')} (id={org.get('id')})")
            return org
        return None
    except Exception as e:
        log.warning(f"Apollo org search failed for {company_name}: {e}")
        return None


def search_people(
    company_name: str,
    domain: str = "",
    apollo_org_id: str = "",
    max_contacts: int = 5,
) -> list[dict]:
    """
    Find decision-makers at a company via Apollo people search.
    Returns list of contact dicts normalized for our DB.
    """
    try:
        payload: dict = {
            "page": 1,
            "per_page": max_contacts,
            "person_titles[]": TARGET_TITLES[:8],  # API limit on titles filter
            "person_seniorities[]": SENIORITY_FILTER,
            "contact_email_status[]": ["verified", "likely to engage"],
        }

        if apollo_org_id:
            payload["organization_ids[]"] = [apollo_org_id]
        elif domain:
            payload["q_organization_domains[]"] = [domain]
        else:
            payload["q_organization_name"] = company_name

        data = _post("mixed_people/search", payload)
        people = data.get("people") or []
        log.info(f"Apollo found {len(people)} contacts for {company_name}")
        return [_normalize_person(p) for p in people]
    except Exception as e:
        log.warning(f"Apollo people search failed for {company_name}: {e}")
        return []


def _normalize_person(p: dict) -> dict:
    """Map Apollo person record to our ProspectContact schema."""
    org = p.get("organization") or {}
    email = p.get("email") or ""
    email_status = p.get("email_status") or ""

    confidence = 0
    if email_status == "verified":
        confidence = 90
    elif email_status == "likely to engage":
        confidence = 70
    elif email_status == "guessed":
        confidence = 40

    title = p.get("title") or ""
    role_category = _classify_role(title)

    is_dm = role_category in (
        "CEO", "President", "COO", "CFO", "CTO", "VP Operations", "VP Technology"
    )

    return {
        "full_name": p.get("name") or "",
        "title": title,
        "role_category": role_category,
        "email": email,
        "phone": (p.get("phone_numbers") or [{}])[0].get("sanitized_number", ""),
        "linkedin_url": p.get("linkedin_url") or "",
        "apollo_person_id": p.get("id") or "",
        "email_confidence": confidence,
        "is_decision_maker": is_dm,
        "is_primary_contact": False,  # caller sets one contact as primary
        "source": "apollo",
    }


def _classify_role(title: str) -> str:
    """Map free-form title to ContactRole enum value."""
    t = title.lower()
    if any(x in t for x in ["chief executive", " ceo"]):
        return "CEO"
    if "president" in t and "vice" not in t:
        return "President"
    if any(x in t for x in ["chief operating", " coo"]):
        return "COO"
    if any(x in t for x in ["chief financial", " cfo"]):
        return "CFO"
    if any(x in t for x in ["chief technology", " cto", "chief information", " cio"]):
        return "CTO"
    if "controller" in t:
        return "CFO"
    if "vp" in t and "operation" in t:
        return "VP Operations"
    if "vice president" in t and "operation" in t:
        return "VP Operations"
    if "vp" in t and ("tech" in t or "it" in t):
        return "VP Technology"
    if "director" in t and ("it" in t or "information" in t or "technology" in t):
        return "Director of IT"
    if "equipment manager" in t:
        return "Equipment Manager"
    if "project executive" in t:
        return "Project Executive"
    return "Other"


def enrich_prospect(
    company_name: str,
    website: str = "",
    existing_apollo_org_id: str = "",
) -> dict:
    """
    Full enrichment pass: find org, then pull decision-maker contacts.
    Returns dict with keys: apollo_org_id, contacts (list), enrichment_notes
    """
    from urllib.parse import urlparse

    domain = ""
    if website:
        parsed = urlparse(website if website.startswith("http") else f"https://{website}")
        domain = parsed.netloc.lstrip("www.")

    apollo_org_id = existing_apollo_org_id
    org_data = {}

    if not apollo_org_id:
        org = search_org(company_name, domain)
        if org:
            apollo_org_id = org.get("id", "")
            org_data = {
                "apollo_employee_count": org.get("num_employees"),
                "apollo_revenue": org.get("annual_revenue"),
                "apollo_linkedin": org.get("linkedin_url"),
            }

    contacts = search_people(
        company_name=company_name,
        domain=domain,
        apollo_org_id=apollo_org_id,
        max_contacts=5,
    )

    # Flag the highest-ranking contact as primary
    if contacts:
        contacts[0]["is_primary_contact"] = True

    return {
        "apollo_org_id": apollo_org_id,
        "contacts": contacts,
        "org_data": org_data,
        "contacts_found": len(contacts),
    }
