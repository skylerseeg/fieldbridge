#!/usr/bin/env python3
"""
FieldBridge v1 — Supplier Enrichment Pipeline
M365 Email → Supplier Data + CSI Code Tagging → Vista-ready CSV

CSI codes use VanCon's Vista 4-digit format (e.g. 3217, 3310, 3331)
matching the Seq/DatabaseValue/DisplayValue schema visible in Vista lookups.

Dependencies:
    pip install exchangelib msal python-dotenv rapidfuzz tqdm
"""

import os
import re
import json
import csv
import logging
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, field
from typing import Optional
from dotenv import load_dotenv
from rapidfuzz import fuzz, process
from tqdm import tqdm

try:
    from exchangelib import (
        Credentials, Account, DELEGATE, Configuration, OAuth2Credentials, Identity
    )
    from msal import ConfidentialClientApplication
except ImportError:
    raise SystemExit("Run: pip install exchangelib msal")

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
log = logging.getLogger("fieldbridge")

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────
TENANT_ID      = os.getenv("AZURE_TENANT_ID")
CLIENT_ID      = os.getenv("AZURE_CLIENT_ID")
CLIENT_SECRET  = os.getenv("AZURE_CLIENT_SECRET")
TARGET_MAILBOX = os.getenv("AP_MAILBOX", "ap@vanconinc.com")
LOOKBACK_DAYS  = int(os.getenv("LOOKBACK_DAYS", 365))
OUTPUT_DIR     = os.getenv("OUTPUT_DIR", "./output")
os.makedirs(OUTPUT_DIR, exist_ok=True)


# ─────────────────────────────────────────────
# CSI CODES — 4-DIGIT FORMAT
# Matches VanCon's Vista Seq/DatabaseValue/DisplayValue schema exactly.
# DatabaseValue = "XXXX-Description", DisplayValue = same
# Keys are the 4-digit Seq integer used as the lookup key in Vista.
# ─────────────────────────────────────────────
CSI_CODES: dict[int, str] = {
    # ── SITE & EARTHWORK ──────────────────────
    3100: "Site Clearing",
    3110: "Site Clearing",
    3120: "Earth Moving",
    3130: "Earthwork Methods",
    3140: "Shoring and Underpinning",
    3150: "Excavation Support and Protection",
    3160: "Special Foundations",
    3170: "Tunneling and Mining",

    # ── EXTERIOR IMPROVEMENTS ────────────────
    3210: "Base Courses",
    3211: "Base Courses",
    3212: "Flexible Paving",
    3213: "Rigid Paving",
    3214: "Unit Paving",
    3216: "Curbs and Gutters",
    3217: "Paving Specialties",
    3218: "Sythetic Surfacing",
    3230: "Ext Improv Site Improvements",
    3231: "Fence and Gates",
    3232: "Retaining Walls",
    3234: "Fabricated Bridges",
    3280: "Landscape Irrigation",
    3290: "Landscaping Planting",

    # ── UTILITIES ────────────────────────────
    3305: "Utility Pipe - DI/PVC/WSP",
    3308: "Commision Utilities",
    3310: "Utilities Water",
    3311: "Water Wells/Pumps",
    3312: "Surface Water Source",
    3314: "Water Distribution",
    3316: "Water Storage Tanks",
    3319: "Water Metering",
    3331: "Sanitary Sewer Piping",
    3332: "Sanitary Sewer Equipment",
    3334: "Septic System",
    3336: "Wastewater Tanks",
    3341: "Stormwater Subdrainage",
    3342: "Stormwater Conveyance",
    3370: "Electrical Utilities",

    # ── TRANSPORTATION ────────────────────────
    3470: "Transportation Trucking",

    # ── WATERWAY & MARINE ────────────────────
    3510: "Waterway & Marine Control EQ",

    # ── PROCESS INTEGRATION ──────────────────
    4000: "Process Integration",
    4020: "Liquids Process Piping",
    4023: "WW Water Process Piping",
    4040: "Process Piping & Eq Protect",
    4122: "Cranes and Hoists",
    4342: "Surge Tank",

    # ── WASTEWATER EQUIPMENT ──────────────────
    4605: "WW Water Equipment",
    4621: "Screening Equipment",
    4623: "Grit Removal Equipment",
    4624: "Griding & Shredding Equip",
    4625: "Oil/Grease Seperation Eq",
    4631: "Chem Feed Equipment",
    4640: "WW Water Clarification Equi",
    4650: "Secondary Treatment Eq",
    4661: "Filtration Equipment",
    4810: "Electrical PW Generation",

    # ── CONCRETE ──────────────────────────────
    300:  "Concrete",
    310:  "Concrete Forming and Accessories",
    320:  "Concrete Reinforcing",
    330:  "Cast-in-Place Concrete",
    340:  "Precast Concrete",

    # ── METALS / STRUCTURAL ───────────────────
    500:  "Metals",
    510:  "Structural Metal Framing",
    550:  "Metal Fabrications",

    # ── ELECTRICAL ────────────────────────────
    2600: "Electrical",
    2610: "Medium-Voltage Electrical Distribution",
    2620: "Low-Voltage Electrical Transmission",
    2650: "Lighting",

    # ── MECHANICAL / HVAC ─────────────────────
    2300: "HVAC",
    2310: "Common Work Results for HVAC",
    2200: "Plumbing",
    2210: "Plumbing Piping and Pumps",

    # ── FIRE SUPPRESSION ──────────────────────
    2100: "Fire Suppression",

    # ── COMMUNICATIONS ────────────────────────
    2700: "Communications",
    2710: "Structured Cabling",

    # ── DEMOLITION ────────────────────────────
    241:  "Demolition",
    242:  "Removal and Salvage of Construction Materials",
}


def fmt_database_value(seq: int, desc: str) -> str:
    """Format to Vista DatabaseValue style: '3217-Paving Specialties'"""
    return f"{seq}-{desc}"


def fmt_display_value(seq: int, desc: str) -> str:
    """Format to Vista DisplayValue style: '3217-Paving Specialties'"""
    return f"{seq}-{desc}"


# ─────────────────────────────────────────────
# KEYWORD → CSI CODE MAP (4-digit keys)
# ─────────────────────────────────────────────
CSI_KEYWORD_MAP: dict[str, list[int]] = {
    # Earthwork / Site
    "excavat":      [3120, 3150],
    "grading":      [3120],
    "earthwork":    [3120, 3130],
    "clearing":     [3100, 3110],
    "shoring":      [3140],
    "dewater":      [3120],
    "tunnel":       [3170],
    "foundation":   [3160],

    # Paving / Roads
    "paving":       [3212, 3213],
    "asphalt":      [3212],
    "concrete pav": [3213],
    "base course":  [3211],
    "gravel":       [3211],
    "aggregate":    [3211],
    "road":         [3212, 3216],
    "highway":      [3212],
    "curb":         [3216],
    "gutter":       [3216],
    "pavement mark":[3217],
    "striping":     [3217],
    "signage":      [3217],
    "synthetic turf":[3218],
    "bridge":       [3234],
    "retaining wall":[3232],
    "fence":        [3231],
    "gate":         [3231],
    "landscap":     [3290],
    "irrigation":   [3280],

    # Water utilities
    "water main":   [3314, 3305],
    "water distribu":[3314],
    "water tank":   [3316],
    "water storage":[3316],
    "water well":   [3311],
    "water meter":  [3319],
    "surface water":[3312],
    "water utilit": [3310],
    "waterline":    [3314],
    "hydrant":      [3314],
    "water pipe":   [3305],

    # Sewer / wastewater
    "sewer":        [3331, 3332],
    "sanitary":     [3331],
    "wastewater":   [3336, 4605],
    "septic":       [3334],
    "lift station": [3332],
    "pump station": [3332, 3311],

    # Storm drainage
    "storm drain":  [3341, 3342],
    "stormwater":   [3341, 3342],
    "culvert":      [3342],
    "subdrain":     [3341],
    "detention":    [3342],

    # Utilities general
    "utility pipe": [3305],
    "ductile iron": [3305],
    "pvc pipe":     [3305],
    "electrical util":[3370, 2600],
    "power line":   [3370],
    "conduit":      [2620],
    "underground util":[3305, 3370],

    # Transportation
    "trucking":     [3470],
    "hauling":      [3470],
    "transport":    [3470],

    # Marine / waterway
    "marine":       [3510],
    "waterway":     [3510],

    # Concrete
    "concrete":     [330, 320],
    "rebar":        [320],
    "reinforc":     [320],
    "precast":      [340],
    "forming":      [310],

    # Structural / metals
    "steel":        [510, 500],
    "structural":   [510],
    "fabricat":     [550],
    "crane":        [4122],
    "hoist":        [4122],

    # Process / treatment
    "process piping":[4020, 4023],
    "process integr":[4000],
    "surge tank":   [4342],
    "screening":    [4621],
    "grit removal": [4623],
    "shredding":    [4624],
    "grease sep":   [4625],
    "chemical feed":[4631],
    "clarif":       [4640],
    "secondary treat":[4650],
    "filtration":   [4661],
    "generator":    [4810],
    "power generat":[4810],

    # MEP
    "plumbing":     [2200, 2210],
    "hvac":         [2300],
    "mechanical":   [2300],
    "fire suppres": [2100],
    "sprinkler":    [2100],
    "communicat":   [2700],
    "cabling":      [2710],
    "electrical":   [2600, 2620],

    # Demolition
    "demolit":      [241],
    "removal":      [242],
    "salvage":      [242],
}


# ─────────────────────────────────────────────
# DATA MODEL
# ─────────────────────────────────────────────
@dataclass
class Supplier:
    vendor_name: str = ""
    vendor_email: str = ""
    phone: str = ""
    address_line1: str = ""
    city: str = ""
    state: str = ""
    zip_code: str = ""
    website: str = ""
    contact_name: str = ""
    contact_title: str = ""
    # Vista CSI fields — stored as list of ints (4-digit seq)
    csi_seq_list: list = field(default_factory=list)
    source_email_count: int = 0
    confidence_score: float = 0.0
    needs_review: bool = True


# ─────────────────────────────────────────────
# M365 OAuth2 CONNECTION
# ─────────────────────────────────────────────
def get_m365_account() -> Account:
    app = ConfidentialClientApplication(
        client_id=CLIENT_ID,
        client_credential=CLIENT_SECRET,
        authority=f"https://login.microsoftonline.com/{TENANT_ID}"
    )
    token = app.acquire_token_for_client(
        scopes=["https://outlook.office365.com/.default"]
    )
    if "access_token" not in token:
        raise RuntimeError(f"M365 auth failed: {token.get('error_description')}")

    creds = OAuth2Credentials(
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        tenant_id=TENANT_ID,
        identity=Identity(primary_smtp_address=TARGET_MAILBOX)
    )
    config = Configuration(credentials=creds, auth_type="OAuth2")
    return Account(
        primary_smtp_address=TARGET_MAILBOX,
        config=config,
        autodiscover=False,
        access_type=DELEGATE
    )


# ─────────────────────────────────────────────
# FIELD EXTRACTION
# ─────────────────────────────────────────────
PATTERNS = {
    "phone":   re.compile(r'(\(?\d{3}\)?[\s.\-]?\d{3}[\s.\-]?\d{4})'),
    "email":   re.compile(r'[\w.+\-]+@[\w\-]+\.[a-zA-Z]{2,6}'),
    "website": re.compile(r'https?://[\w.\-/]+|www\.[\w.\-/]+'),
    "zip":     re.compile(r'\b(\d{5})(?:-\d{4})?\b'),
    "state":   re.compile(
        r'\b(AL|AK|AZ|AR|CA|CO|CT|DE|FL|GA|HI|ID|IL|IN|IA|KS|KY|LA|'
        r'ME|MD|MA|MI|MN|MS|MO|MT|NE|NV|NH|NJ|NM|NY|NC|ND|OH|OK|OR|'
        r'PA|RI|SC|SD|TN|TX|UT|VA|WA|WV|WI|WY|DC)\b'
    ),
    "address": re.compile(
        r'\d{1,5}\s+\w[\w\s]{3,40}(?:St|Ave|Blvd|Dr|Rd|Way|Ln|Pkwy|Hwy|Ct|Pl)\b',
        re.IGNORECASE
    ),
    "title": re.compile(
        r'\b(President|CEO|CFO|COO|VP|Director|Manager|Estimator|'
        r'Superintendent|Owner|Principal|Controller|Foreman)\b',
        re.IGNORECASE
    ),
}


def extract_fields(text: str, sender_email: str) -> dict:
    result = {"vendor_email": sender_email}
    lines = [l.strip() for l in text.splitlines() if l.strip()]

    for key, pattern in PATTERNS.items():
        match = pattern.search(text)
        if match:
            result[key] = match.group(0).strip()

    for i, line in enumerate(lines):
        if PATTERNS["title"].search(line):
            result["contact_title"] = PATTERNS["title"].search(line).group(0)
            if i > 0:
                result["contact_name"] = lines[i - 1]
            if i + 1 < len(lines):
                result["vendor_name"] = lines[i + 1]
            break

    if "address" in result:
        result["address_line1"] = result.pop("address")

    return result


def infer_csi_codes(text: str) -> list[int]:
    """
    Match email body/signature against keyword map.
    Returns sorted list of 4-digit CSI seq integers.
    """
    text_lower = text.lower()
    matched: set[int] = set()

    for keyword, codes in CSI_KEYWORD_MAP.items():
        if keyword in text_lower:
            matched.update(codes)

    return sorted(matched)


# ─────────────────────────────────────────────
# DEDUPLICATION
# ─────────────────────────────────────────────
def deduplicate(suppliers: list[Supplier]) -> list[Supplier]:
    merged: dict[str, Supplier] = {}
    for s in suppliers:
        if not s.vendor_name:
            continue
        match = process.extractOne(
            s.vendor_name,
            merged.keys(),
            scorer=fuzz.token_sort_ratio,
            score_cutoff=88
        )
        if match:
            existing = merged[match[0]]
            existing.csi_seq_list = sorted(
                set(existing.csi_seq_list + s.csi_seq_list)
            )
            existing.source_email_count += s.source_email_count
            for fname in ["phone", "address_line1", "city", "state",
                          "zip_code", "website", "contact_name"]:
                if not getattr(existing, fname) and getattr(s, fname):
                    setattr(existing, fname, getattr(s, fname))
        else:
            merged[s.vendor_name] = s

    return list(merged.values())


# ─────────────────────────────────────────────
# CSV EXPORTS
# ─────────────────────────────────────────────

def write_vendor_csv(suppliers: list[Supplier], path: str):
    """
    Vista AP Vendor import format.
    CSI codes stored as pipe-delimited DatabaseValues matching Vista format.
    """
    fields = [
        "vendor_name", "vendor_email", "phone",
        "address_line1", "city", "state", "zip_code",
        "website", "contact_name", "contact_title",
        "csi_database_values",   # pipe-delimited: "3217-Paving Specialties|3231-Fence and Gates"
        "csi_display_values",    # same format, matches Vista DisplayValue column
        "source_email_count", "confidence_score", "needs_review"
    ]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for s in suppliers:
            db_vals = "|".join(
                fmt_database_value(seq, CSI_CODES[seq])
                for seq in s.csi_seq_list
                if seq in CSI_CODES
            )
            disp_vals = "|".join(
                fmt_display_value(seq, CSI_CODES[seq])
                for seq in s.csi_seq_list
                if seq in CSI_CODES
            )
            writer.writerow({
                "vendor_name":          s.vendor_name,
                "vendor_email":         s.vendor_email,
                "phone":                s.phone,
                "address_line1":        s.address_line1,
                "city":                 s.city,
                "state":                s.state,
                "zip_code":             s.zip_code,
                "website":              s.website,
                "contact_name":         s.contact_name,
                "contact_title":        s.contact_title,
                "csi_database_values":  db_vals,
                "csi_display_values":   disp_vals,
                "source_email_count":   s.source_email_count,
                "confidence_score":     s.confidence_score,
                "needs_review":         s.needs_review,
            })
    log.info(f"Vendor CSV: {path} ({len(suppliers)} records)")


def write_csi_lookup_csv(path: str):
    """
    Full CSI lookup table in Vista's exact 3-column format:
        Seq | DatabaseValue | DisplayValue
    Import this into Vista's CSI code lookup table directly.
    """
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["Seq", "DatabaseValue", "DisplayValue"])
        writer.writeheader()
        for seq in sorted(CSI_CODES.keys()):
            desc = CSI_CODES[seq]
            writer.writerow({
                "Seq":           seq,
                "DatabaseValue": fmt_database_value(seq, desc),
                "DisplayValue":  fmt_display_value(seq, desc),
            })
    log.info(f"CSI lookup CSV: {path} ({len(CSI_CODES)} codes)")


def write_vendor_csi_mapping_csv(suppliers: list[Supplier], path: str):
    """
    Flat vendor ↔ CSI mapping table — one row per vendor-code pair.
    Easier to import into Vista as a vendor category/trade association table.
    Format: vendor_name | vendor_email | Seq | DatabaseValue | DisplayValue
    """
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f, fieldnames=["vendor_name", "vendor_email", "Seq", "DatabaseValue", "DisplayValue"]
        )
        writer.writeheader()
        for s in suppliers:
            for seq in s.csi_seq_list:
                if seq not in CSI_CODES:
                    continue
                desc = CSI_CODES[seq]
                writer.writerow({
                    "vendor_name":    s.vendor_name,
                    "vendor_email":   s.vendor_email,
                    "Seq":            seq,
                    "DatabaseValue":  fmt_database_value(seq, desc),
                    "DisplayValue":   fmt_display_value(seq, desc),
                })
    log.info(f"Vendor-CSI mapping CSV: {path}")


# ─────────────────────────────────────────────
# MAIN PIPELINE
# ─────────────────────────────────────────────
def run():
    log.info(f"FieldBridge v1 | Mailbox: {TARGET_MAILBOX} | Lookback: {LOOKBACK_DAYS}d")

    account = get_m365_account()
    cutoff  = datetime.now(tz=timezone.utc) - timedelta(days=LOOKBACK_DAYS)

    log.info("Scanning inbox...")
    emails = list(account.inbox.filter(datetime_received__gte=cutoff))
    log.info(f"{len(emails)} emails in range")

    suppliers_raw: list[Supplier] = []

    for item in tqdm(emails, desc="Processing"):
        try:
            body         = item.body or ""
            sender_email = item.sender.email_address if item.sender else ""
            sender_name  = item.sender.name if item.sender else ""

            if not sender_email or "vanconinc.com" in sender_email.lower():
                continue

            fields    = extract_fields(body, sender_email)
            csi_seqs  = infer_csi_codes(body)

            s = Supplier(
                vendor_name       = fields.get("vendor_name", sender_name),
                vendor_email      = sender_email,
                phone             = fields.get("phone", ""),
                address_line1     = fields.get("address_line1", ""),
                state             = fields.get("state", ""),
                zip_code          = fields.get("zip", ""),
                website           = fields.get("website", ""),
                contact_name      = fields.get("contact_name", sender_name),
                contact_title     = fields.get("contact_title", ""),
                csi_seq_list      = csi_seqs,
                source_email_count= 1,
                confidence_score  = round(min(len(csi_seqs) / 5 * 100, 100), 1),
                needs_review      = True,
            )
            suppliers_raw.append(s)

        except Exception as e:
            log.warning(f"Failed on email: {e}")

    log.info(f"Raw records: {len(suppliers_raw)}")
    suppliers = deduplicate(suppliers_raw)
    log.info(f"After dedup: {len(suppliers)} unique vendors")

    ts = datetime.now().strftime("%Y%m%d_%H%M")
    write_vendor_csv(suppliers,              f"{OUTPUT_DIR}/vista_vendors_{ts}.csv")
    write_vendor_csi_mapping_csv(suppliers,  f"{OUTPUT_DIR}/vista_vendor_csi_map_{ts}.csv")
    write_csi_lookup_csv(                    f"{OUTPUT_DIR}/vista_csi_lookup_full.csv")

    log.info("Done. Review needs_review=True records before Vista import.")


# ─────────────────────────────────────────────
# STANDALONE: EXPORT JUST THE CSI LOOKUP TABLE
# Run: python fieldbridge_supplier_enrichment.py --csi-only
# ─────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    if "--csi-only" in sys.argv:
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        write_csi_lookup_csv(f"{OUTPUT_DIR}/vista_csi_lookup_full.csv")
        log.info("CSI lookup table exported. Ready for Vista import.")
    else:
        run()
