"""
extractor.py — Coventry University Course Scraper
Fetches a single course page via Playwright+stealth, detects page type
(CPD or PG), and extracts exactly 26 schema fields into a Python dict.

Public interface:
    extract_course(url: str) -> dict

Run standalone test:
    python scraper/extractor.py
"""

from __future__ import annotations

import io
import logging
import sys
from typing import Callable

from bs4 import BeautifulSoup, NavigableString, Tag
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

# ── Force UTF-8 output on Windows ─────────────────────────────
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

logging.basicConfig(level=logging.INFO, format="[extractor] %(message)s")
log = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)
EXTRA_HEADERS = {
    "Accept-Language": "en-GB,en;q=0.9",
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;"
        "q=0.9,image/webp,*/*;q=0.8"
    ),
}
NAV_TIMEOUT = 30_000

_stealth = Stealth()

# Canonical field order — exactly 26 keys
SCHEMA_KEYS: tuple[str, ...] = (
    "program_course_name",
    "university_name",
    "course_website_url",
    "campus",
    "country",
    "address",
    "study_level",
    "course_duration",
    "all_intakes_available",
    "mandatory_documents_required",
    "yearly_tuition_fee",
    "scholarship_availability",
    "gre_gmat_mandatory_min_score",
    "indian_regional_institution_restrictions",
    "class_12_boards_accepted",
    "gap_year_max_accepted",
    "min_duolingo",
    "english_waiver_class12",
    "english_waiver_moi",
    "min_ielts",
    "kaplan_test_of_english",
    "min_pte",
    "min_toefl",
    "ug_academic_min_gpa",
    "twelfth_pass_min_cgpa",
    "mandatory_work_exp",
    "max_backlogs",
)

NA = "NA"


# ──────────────────────────────────────────────────────────────
# Core helpers
# ──────────────────────────────────────────────────────────────

def _safe_extract(func: Callable, *args, **kwargs) -> str:
    """
    Wraps any extraction call in try/except.
    Returns "NA" on any exception and logs the error.
    """
    try:
        result = func(*args, **kwargs)
        # Guarantee we never return None or empty string
        if result is None or (isinstance(result, str) and result.strip() == ""):
            return NA
        return result
    except Exception as exc:
        log.warning("Extraction error in %s: %s", func.__name__, exc)
        return NA


def _clean(text: str | None) -> str:
    """Strip whitespace; return NA if empty."""
    if text is None:
        return NA
    cleaned = " ".join(text.split())
    return cleaned if cleaned else NA


# ──────────────────────────────────────────────────────────────
# Page fetcher
# ──────────────────────────────────────────────────────────────

def _fetch_page(url: str) -> str:
    """
    Returns raw HTML string via Playwright+stealth.
    Uses domcontentloaded (SSR confirmed — networkidle not needed).
    Raises on unrecoverable failure.
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            context = browser.new_context(
                user_agent=USER_AGENT,
                viewport={"width": 1920, "height": 1080},
                locale="en-GB",
                timezone_id="Europe/London",
            )
            page = context.new_page()
            _stealth.apply_stealth_sync(page)  # NON-NEGOTIABLE
            page.set_extra_http_headers(EXTRA_HEADERS)
            response = page.goto(url, timeout=NAV_TIMEOUT, wait_until="domcontentloaded")
            if response and response.status >= 400:
                raise RuntimeError(f"HTTP {response.status} for {url}")
            return page.content()
        finally:
            browser.close()


# ──────────────────────────────────────────────────────────────
# Page type detection
# ──────────────────────────────────────────────────────────────

def _detect_page_type(url: str) -> str:
    """Returns 'cpd' or 'pg' based on URL pattern."""
    return "cpd" if "/cpd/" in url else "pg"


# ──────────────────────────────────────────────────────────────
# CPD helpers
# ──────────────────────────────────────────────────────────────

def _get_kv_field(soup: BeautifulSoup, label: str) -> str:
    """
    CPD helper: finds <strong> whose text matches `label` (colon-insensitive).

    Page structure is a two-column grid:
        <div>  ← label column (grandparent of <strong>)
          <p><strong>Label:</strong></p>
        </div>
        <div>  ← value column (next sibling of grandparent)
          <p>Value text</p>
        </div>

    Walks up strong → p → div, then takes the first sibling div's text.
    Returns "NA" if not found.
    """
    label_normalised = label.strip().rstrip(":").lower()

    for strong in soup.find_all("strong"):
        strong_text = strong.get_text(strip=True).rstrip(":").lower()
        if strong_text == label_normalised:
            # strong → <p> → <div> (label column)
            label_div = strong.parent.parent if strong.parent else None
            if label_div is None:
                continue
            # Find first sibling Tag = value column div
            for sibling in label_div.next_siblings:
                if isinstance(sibling, Tag):
                    return _clean(sibling.get_text(strip=True))
    return NA


def _get_footer_address(soup: BeautifulSoup) -> str:
    """
    Searches footer for text containing 'Priory Street'.
    Returns the longest matching text fragment found.
    Fallback: "Priory Street, Coventry CV1 5FB, United Kingdom"
    """
    FALLBACK = "Priory Street, Coventry CV1 5FB, United Kingdom"

    for element in soup.find_all(string=lambda t: t and "Priory Street" in t):
        # Skip JSON-LD <script> tags — they contain "Priory Street" in structured data
        if element.parent.name == "script":
            continue
        parent = element.parent
        text = _clean(parent.get_text(separator=" ", strip=True))
        if text and text != NA:
            return text

    return FALLBACK


# ──────────────────────────────────────────────────────────────
# PG helpers
# ──────────────────────────────────────────────────────────────

def _get_course_feature(soup: BeautifulSoup, heading: str) -> str:
    """
    PG helper: finds h3 with text matching `heading` in the course features
    section, returns ALL text content of the following sibling container.
    Joins multiple lines with " / ". Returns "NA" if not found.
    """
    heading_lower = heading.lower()

    for h3 in soup.find_all("h3"):
        if h3.get_text(strip=True).lower() == heading_lower:
            # Collect text from the next sibling element
            sibling = h3.find_next_sibling()
            if sibling is None:
                # Try next_sibling (NavigableString or Tag)
                for ns in h3.next_siblings:
                    if isinstance(ns, Tag):
                        sibling = ns
                        break
            if sibling is None:
                return NA

            # Collect all non-empty text lines from the sibling subtree
            lines: list[str] = []
            for text_node in sibling.strings:
                t = text_node.strip()
                if t:
                    lines.append(t)

            if not lines:
                text = _clean(sibling.get_text())
                return text if text != NA else NA

            return " / ".join(lines) if len(lines) > 1 else _clean(lines[0])

    return NA


def _get_study_level_pg(soup: BeautifulSoup) -> str:
    """
    Finds the study level container below the h1.
    Returns "Postgraduate | Conversion course" or "Postgraduate".
    Falls back to "NA".
    """
    h1 = soup.find("h1")
    if h1 is None:
        return NA

    # Search in the region after h1 for "Study level:" text
    # Look in h1's parent and nearby siblings
    search_root = h1.parent if h1.parent else soup

    # Find element containing "Study level:"
    study_level_el = None
    for el in search_root.find_all(string=lambda t: t and "Study level" in t):
        study_level_el = el.parent
        break

    if study_level_el is None:
        # Broader search
        for el in soup.find_all(string=lambda t: t and "Study level" in t):
            study_level_el = el.parent
            break

    if study_level_el is None:
        return NA

    # Get the container text to check for "Conversion course"
    container = study_level_el.parent if study_level_el.parent else study_level_el
    container_text = container.get_text(separator=" ", strip=True)

    level = "Postgraduate"
    if "Conversion course" in container_text:
        level = "Postgraduate | Conversion course"

    return level


def _get_all_start_dates(soup: BeautifulSoup) -> str:
    """
    Finds the 'Start date' h3 and collects ALL text lines from the
    following sibling. Joins with " / ".
    Also appends 'Year of entry' if found.
    """
    start_dates: list[str] = []
    year_of_entry: str = NA

    for h3 in soup.find_all("h3"):
        h3_text = h3.get_text(strip=True).lower()

        if h3_text == "start date":
            sibling = h3.find_next_sibling()
            if sibling:
                lines = [t.strip() for t in sibling.strings if t.strip()]
                start_dates = lines

        elif h3_text == "year of entry":
            sibling = h3.find_next_sibling()
            if sibling:
                lines = [t.strip() for t in sibling.strings if t.strip()]
                if lines:
                    year_of_entry = ", ".join(lines)

    if not start_dates:
        return NA

    dates_str = " / ".join(start_dates)

    if year_of_entry != NA:
        return f"Year of entry: {year_of_entry} | Start dates: {dates_str}"

    return dates_str


def _get_mandatory_documents(soup: BeautifulSoup) -> str:
    """
    Looks for h3 with 'Portfolio' in the entry requirements section.
    Returns full paragraph text if found, "NA" otherwise.
    """
    # Find entry requirements section
    entry_section = soup.find(id="ct-section4")
    search_root = entry_section if entry_section else soup

    portfolio_h3 = search_root.find(
        "h3", string=lambda t: t and "Portfolio" in t
    )
    if portfolio_h3 is None:
        # Try case-insensitive
        for h3 in search_root.find_all("h3"):
            if "portfolio" in h3.get_text(strip=True).lower():
                portfolio_h3 = h3
                break

    if portfolio_h3 is None:
        return NA

    # Collect all following paragraph text until the next h3
    parts: list[str] = []
    for sibling in portfolio_h3.next_siblings:
        if isinstance(sibling, Tag):
            if sibling.name == "h3":
                break
            text = _clean(sibling.get_text(separator=" "))
            if text != NA:
                parts.append(text)

    return " ".join(parts) if parts else NA


def _get_yearly_tuition_fee(soup: BeautifulSoup) -> str:
    """
    Finds the fees table in the fees section (#ct-section5).
    Returns "UK: £X | International: £Y".
    """
    fees_section = soup.find(id="ct-section5")
    search_root = fees_section if fees_section else soup

    table = search_root.find("table")
    if table is None:
        return NA

    uk_fee: str = NA
    intl_fee: str = NA

    rows = table.find_all("tr")
    for row in rows:
        cells = [td.get_text(strip=True) for td in row.find_all(["td", "th"])]
        if not cells:
            continue

        first = cells[0].lower()
        if "uk" in first and len(cells) >= 2:
            # Take the full-time column (index 1) preferring non-empty
            for cell in cells[1:]:
                if cell and "£" in cell:
                    uk_fee = cell
                    break
        elif "international" in first and len(cells) >= 2:
            for cell in cells[1:]:
                if cell and "£" in cell:
                    intl_fee = cell
                    break

    if uk_fee == NA and intl_fee == NA:
        # Fallback: extract all £ values from the table text
        table_text = _clean(table.get_text(separator=" "))
        return table_text if table_text != NA else NA

    parts: list[str] = []
    if uk_fee != NA:
        parts.append(f"UK: {uk_fee}")
    if intl_fee != NA:
        parts.append(f"International: {intl_fee}")

    return " | ".join(parts) if parts else NA


def _get_scholarship_availability(soup: BeautifulSoup) -> str:
    """
    Looks for 'international scholarships' text in the fees section.
    Returns a structured string if found, "NA" otherwise.
    """
    fees_section = soup.find(id="ct-section5")
    search_root = fees_section if fees_section else soup

    for el in search_root.find_all(string=lambda t: t and "international scholarships" in t.lower()):
        return (
            "Yes - International Scholarships available. "
            "See: https://www.coventry.ac.uk/international-students-hub/apply-for-a-scholarship/"
        )

    return NA


def _get_min_ielts(soup: BeautifulSoup) -> str:
    """
    Finds 'IELTS:' text in the entry requirements section.
    Returns the following value text.
    """
    entry_section = soup.find(id="ct-section4")
    search_root = entry_section if entry_section else soup

    # Look for text nodes containing "IELTS:"
    for el in search_root.find_all(string=lambda t: t and "IELTS" in t):
        text = _clean(el)
        if "IELTS" in text:
            # Strip the label prefix and return the value
            if ":" in text:
                value = text.split(":", 1)[1].strip()
                if value:
                    return _clean(value)
            # May be in parent element alongside a value sibling
            parent = el.parent
            if parent:
                full = _clean(parent.get_text(separator=" "))
                if "IELTS" in full and ":" in full:
                    value = full.split("IELTS", 1)[1].lstrip(":").strip()
                    if value:
                        return _clean(value.split("\n")[0])

    return NA


def _get_entry_requirements_text(soup: BeautifulSoup) -> str:
    """
    Finds 'Typical entry requirements' h3 and collects all following
    paragraph text until the next h3.
    """
    entry_section = soup.find(id="ct-section4")
    search_root = entry_section if entry_section else soup

    target_h3 = None
    for h3 in search_root.find_all("h3"):
        if "typical entry requirements" in h3.get_text(strip=True).lower():
            target_h3 = h3
            break

    if target_h3 is None:
        return NA

    parts: list[str] = []
    for sibling in target_h3.next_siblings:
        if isinstance(sibling, Tag):
            if sibling.name == "h3":
                break
            text = _clean(sibling.get_text(separator=" "))
            if text != NA:
                parts.append(text)

    return " ".join(parts) if parts else NA


def _get_mandatory_work_exp(entry_req_text: str) -> str:
    """
    Returns the work experience clause if present in entry requirements text,
    "NA" otherwise.
    """
    if entry_req_text == NA:
        return NA

    lower = entry_req_text.lower()
    if "work experience" not in lower:
        return NA

    # Extract the clause containing "work experience"
    sentences = entry_req_text.replace(", or", ".|").replace(", and", ".|").split(".|")
    for sentence in sentences:
        if "work experience" in sentence.lower():
            return _clean(sentence)

    return _clean(entry_req_text)


# ──────────────────────────────────────────────────────────────
# CPD field extractor
# ──────────────────────────────────────────────────────────────

def _extract_cpd_fields(soup: BeautifulSoup, url: str) -> dict:
    """Extracts all 26 fields from a CPD page."""
    errors: list[str] = []

    def safe(field: str, func: Callable, *args, **kwargs) -> str:
        try:
            result = func(*args, **kwargs)
            if result is None or (isinstance(result, str) and not result.strip()):
                return NA
            return result
        except Exception as exc:
            errors.append(f"{field}: {exc}")
            return NA

    h1 = soup.find("h1")
    program_course_name = safe(
        "program_course_name",
        lambda: _clean(h1.get_text()) if h1 else NA
    )

    return {
        "program_course_name": program_course_name,
        "university_name": "Coventry University",
        "course_website_url": url,
        "campus": safe("campus", _get_kv_field, soup, "Location"),
        "country": "United Kingdom",
        "address": safe("address", _get_footer_address, soup),
        "study_level": safe("study_level", _get_kv_field, soup, "Qualification"),
        "course_duration": safe("course_duration", _get_kv_field, soup, "Duration"),
        "all_intakes_available": safe("all_intakes_available", _get_kv_field, soup, "Course dates"),
        "mandatory_documents_required": NA,
        "yearly_tuition_fee": safe("yearly_tuition_fee", _get_kv_field, soup, "Fees"),
        "scholarship_availability": NA,
        "gre_gmat_mandatory_min_score": NA,
        "indian_regional_institution_restrictions": NA,
        "class_12_boards_accepted": NA,
        "gap_year_max_accepted": NA,
        "min_duolingo": NA,
        "english_waiver_class12": NA,
        "english_waiver_moi": NA,
        "min_ielts": NA,
        "kaplan_test_of_english": NA,
        "min_pte": NA,
        "min_toefl": NA,
        "ug_academic_min_gpa": NA,
        "twelfth_pass_min_cgpa": NA,
        "mandatory_work_exp": NA,
        "max_backlogs": NA,
        **({"extraction_errors": errors} if errors else {}),
    }


# ──────────────────────────────────────────────────────────────
# PG field extractor
# ──────────────────────────────────────────────────────────────

def _extract_pg_fields(soup: BeautifulSoup, url: str) -> dict:
    """Extracts all 26 fields from a PG page."""
    errors: list[str] = []

    def safe(field: str, func: Callable, *args, **kwargs) -> str:
        try:
            result = func(*args, **kwargs)
            if result is None or (isinstance(result, str) and not result.strip()):
                return NA
            return result
        except Exception as exc:
            errors.append(f"{field}: {exc}")
            return NA

    # Extract entry requirements text once (used by two fields)
    entry_req_text = safe("entry_requirements_text", _get_entry_requirements_text, soup)

    h1 = soup.find("h1")
    program_course_name = safe(
        "program_course_name",
        lambda: _clean(h1.get_text()) if h1 else NA
    )

    mandatory_work_exp_val = safe(
        "mandatory_work_exp",
        _get_mandatory_work_exp,
        entry_req_text,
    )

    return {
        "program_course_name": program_course_name,
        "university_name": "Coventry University",
        "course_website_url": url,
        "campus": safe("campus", _get_course_feature, soup, "Location"),
        "country": "United Kingdom",
        "address": safe("address", _get_footer_address, soup),
        "study_level": safe("study_level", _get_study_level_pg, soup),
        "course_duration": safe("course_duration", _get_course_feature, soup, "Duration"),
        "all_intakes_available": safe("all_intakes_available", _get_all_start_dates, soup),
        "mandatory_documents_required": safe("mandatory_documents_required", _get_mandatory_documents, soup),
        "yearly_tuition_fee": safe("yearly_tuition_fee", _get_yearly_tuition_fee, soup),
        "scholarship_availability": safe("scholarship_availability", _get_scholarship_availability, soup),
        "gre_gmat_mandatory_min_score": NA,
        "indian_regional_institution_restrictions": NA,
        "class_12_boards_accepted": NA,
        "gap_year_max_accepted": NA,
        "min_duolingo": NA,
        "english_waiver_class12": NA,
        "english_waiver_moi": NA,
        "min_ielts": safe("min_ielts", _get_min_ielts, soup),
        "kaplan_test_of_english": NA,
        "min_pte": NA,
        "min_toefl": NA,
        "ug_academic_min_gpa": entry_req_text,
        "twelfth_pass_min_cgpa": NA,
        "mandatory_work_exp": mandatory_work_exp_val,
        "max_backlogs": NA,
        **({"extraction_errors": errors} if errors else {}),
    }


# ──────────────────────────────────────────────────────────────
# Public interface
# ──────────────────────────────────────────────────────────────

def extract_course(url: str) -> dict:
    """
    Fetches a single Coventry University course page via Playwright+stealth,
    detects page type (CPD or PG), extracts all 26 schema fields,
    and returns a dict. Never raises — catches all errors and returns
    partial dict with "NA" for failed fields plus an "extraction_errors"
    key listing what failed.
    """
    errors: list[str] = []

    try:
        log.info("Fetching: %s", url)
        html = _fetch_page(url)
    except Exception as exc:
        log.error("Failed to fetch %s: %s", url, exc)
        errors.append(f"fetch: {exc}")
        # Return a fully-NA skeleton so the pipeline never crashes
        result = {key: NA for key in SCHEMA_KEYS}
        result["course_website_url"] = url
        result["university_name"] = "Coventry University"
        result["country"] = "United Kingdom"
        result["extraction_errors"] = errors
        return result

    soup = BeautifulSoup(html, "lxml")
    page_type = _detect_page_type(url)
    log.info("Page type: %s", page_type)

    try:
        if page_type == "cpd":
            data = _extract_cpd_fields(soup, url)
        else:
            data = _extract_pg_fields(soup, url)
    except Exception as exc:
        log.error("Extraction failed for %s: %s", url, exc)
        errors.append(f"extraction: {exc}")
        data = {key: NA for key in SCHEMA_KEYS}
        data["course_website_url"] = url
        data["university_name"] = "Coventry University"
        data["country"] = "United Kingdom"

    # Merge any top-level errors
    if errors:
        existing = data.get("extraction_errors", [])
        data["extraction_errors"] = existing + errors

    # Guarantee all 26 canonical keys are present and non-empty
    for key in SCHEMA_KEYS:
        if key not in data or data[key] is None or data[key] == "":
            data[key] = NA

    # Return in canonical key order (+ extraction_errors if present)
    ordered: dict = {key: data[key] for key in SCHEMA_KEYS}
    if "extraction_errors" in data and data["extraction_errors"]:
        ordered["extraction_errors"] = data["extraction_errors"]

    return ordered


# ──────────────────────────────────────────────────────────────
# Standalone test
# ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import json

    # ── PG test ───────────────────────────────────────────────
    test_url = (
        "https://www.coventry.ac.uk/course-structure/pg/cas/"
        "applied-innovation-leadership-ma/"
    )
    result = extract_course(test_url)

    print("\n══════════ EXTRACTION TEST RESULT ══════════")
    print(json.dumps(result, indent=2))
    print("══════════════════════════════════════════")

    expected_keys = list(SCHEMA_KEYS)
    missing = [k for k in expected_keys if k not in result]
    extra   = [k for k in result if k not in expected_keys and k != "extraction_errors"]

    print(f"\n Keys present: {len([k for k in expected_keys if k in result])}/26")
    if missing:
        print(f"MISSING KEYS: {missing}")
    if extra:
        print(f"EXTRA KEYS:  {extra}")

    checks = {
        "program_course_name":        "Applied Innovation Leadership MA",
        "study_level":                "Postgraduate | Conversion course",
        "course_duration":            "1 year full-time",
        "min_ielts":                  "6.5",
        "yearly_tuition_fee":         "£11,200",
        "gre_gmat_mandatory_min_score": "NA",
    }
    print("\nSpot checks:")
    for field, expected_substring in checks.items():
        actual = result.get(field, "MISSING")
        status = "✅" if expected_substring in str(actual) else "❌"
        print(f"  {status} {field}: {str(actual)[:80]}")

    # ── CPD test ──────────────────────────────────────────────
    print("\n══════════ CPD TEST ══════════")
    cpd_url = (
        "https://www.coventry.ac.uk/course-structure/"
        "health-and-life-sciences/cpd/"
        "extended-scope-practice-neuromusculoskeletal/"
        "applied-pharmacology-for-advanced-clinical-practice/"
    )
    cpd_result = extract_course(cpd_url)
    print(json.dumps(cpd_result, indent=2))

    cpd_checks = {
        "study_level":       "CPD",
        "yearly_tuition_fee": "£150",
        "min_ielts":         "NA",
        "mandatory_work_exp": "NA",
    }
    print("\nCPD Spot checks:")
    for field, expected_substring in cpd_checks.items():
        actual = cpd_result.get(field, "MISSING")
        status = "✅" if expected_substring in str(actual) else "❌"
        print(f"  {status} {field}: {actual}")
