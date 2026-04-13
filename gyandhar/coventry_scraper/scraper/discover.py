"""
discover.py — Coventry University Course Scraper
Discovers exactly 5 valid course page URLs from coventry.ac.uk using
Playwright + playwright-stealth to bypass Cloudflare WAF.

Strategies (attempted in order, stops at first success):
  1. sitemapindex.xml  — PRIMARY
  2. sitemap.xml       — FALLBACK 1
  3. Homepage crawl    — FALLBACK 2

Run:
    python scraper/discover.py
Output:
    output/course_urls.json
"""

from __future__ import annotations

import io
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import NamedTuple
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from playwright.sync_api import Page, sync_playwright
from playwright_stealth import Stealth

_stealth = Stealth()

# ── Force UTF-8 output on Windows ─────────────────────────────
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

# ── Constants ──────────────────────────────────────────────────
BASE = "https://www.coventry.ac.uk"
OUTPUT_DIR = Path(__file__).parent.parent / "output"
OUTPUT_FILE = OUTPUT_DIR / "course_urls.json"

TARGET_DOMAIN = "coventry.ac.uk"
REQUIRED_COUNT = 5
NAV_TIMEOUT = 30_000  # ms

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

# URL fragments that indicate a course page
COURSE_PATTERNS: tuple[str, ...] = (
    "/course-structure/",
    "/undergraduate-study/courses/",
    "/postgraduate-study/courses/",
    "/study-at-coventry/",
)

# URL fragments that must NOT appear in course page URLs
EXCLUDE_PATTERNS: tuple[str, ...] = (
    "/course-finder-search-results/",
    "/search/",
)

# File extensions that indicate non-page resources
EXCLUDE_EXTENSIONS: tuple[str, ...] = (".jpg", ".jpeg", ".png", ".gif", ".pdf", ".svg", ".webp")

# Keywords that identify a course-relevant child sitemap
SITEMAP_COURSE_KEYWORDS: tuple[str, ...] = (
    "course",
    "study",
    "undergraduate",
    "postgraduate",
    "programme",
)


# ── Data types ─────────────────────────────────────────────────
class DiscoveredURL(NamedTuple):
    index: int
    url: str
    url_pattern_matched: str


@dataclass(frozen=True)
class DiscoveryResult:
    source_strategy: str
    urls: list[DiscoveredURL]


# ── Playwright browser factory ─────────────────────────────────
def _make_page(playwright_instance) -> tuple:
    """Return (browser, context, page) with stealth and real fingerprint applied."""
    browser = playwright_instance.chromium.launch(headless=True)
    context = browser.new_context(
        user_agent=USER_AGENT,
        viewport={"width": 1920, "height": 1080},
        locale="en-GB",
        timezone_id="Europe/London",
    )
    page = context.new_page()
    _stealth.apply_stealth_sync(page)  # NON-NEGOTIABLE — must run before any navigation
    page.set_extra_http_headers(EXTRA_HEADERS)
    return browser, context, page


def _fetch_text(page: Page, url: str) -> str | None:
    """Navigate to url and return page.content(). Returns None on any error."""
    try:
        response = page.goto(url, timeout=NAV_TIMEOUT, wait_until="domcontentloaded")
        if response is None:
            print(f"  [WARN] No response object for {url}")
            return None
        if response.status >= 400:
            print(f"  [WARN] HTTP {response.status} for {url}")
            return None
        return page.content()
    except Exception as exc:
        print(f"  [ERROR] Navigation failed for {url}: {exc}")
        return None


# ── URL filtering helpers ──────────────────────────────────────
def _is_valid_course_url(url: str) -> tuple[bool, str]:
    """
    Returns (is_valid, matched_pattern).
    A valid course URL must:
      - be from coventry.ac.uk
      - contain at least one COURSE_PATTERNS fragment
      - not contain any EXCLUDE_PATTERNS fragment
      - not end with an excluded file extension
    """
    parsed = urlparse(url)

    if TARGET_DOMAIN not in parsed.netloc:
        return False, ""

    lower = url.lower()

    if any(lower.endswith(ext) for ext in EXCLUDE_EXTENSIONS):
        return False, ""

    if any(excl in lower for excl in EXCLUDE_PATTERNS):
        return False, ""

    for pattern in COURSE_PATTERNS:
        if pattern in lower:
            return True, pattern

    return False, ""


def _deduplicate(urls: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            result.append(u)
    return result


# ── XML sitemap parsing ────────────────────────────────────────
def _extract_locs(xml_text: str) -> list[str]:
    """Extract all <loc> text values from an XML sitemap/sitemapindex."""
    soup = BeautifulSoup(xml_text, "lxml-xml")
    return [loc.get_text(strip=True) for loc in soup.find_all("loc")]


def _is_sitemapindex(xml_text: str) -> bool:
    soup = BeautifulSoup(xml_text, "lxml-xml")
    return soup.find("sitemapindex") is not None


def _best_child_sitemap(child_urls: list[str]) -> str | None:
    """Return the child sitemap URL most likely to contain course pages."""
    for url in child_urls:
        lower = url.lower()
        if any(kw in lower for kw in SITEMAP_COURSE_KEYWORDS):
            return url
    return child_urls[0] if child_urls else None


def _collect_course_urls_from_sitemap_text(xml_text: str) -> list[str]:
    """Parse sitemap XML and return all URLs passing the course filter."""
    locs = _extract_locs(xml_text)
    results: list[str] = []
    for loc in locs:
        valid, _ = _is_valid_course_url(loc)
        if valid:
            results.append(loc)
    return results


def _build_discovered_list(raw_urls: list[str]) -> list[DiscoveredURL]:
    deduped = _deduplicate(raw_urls)[:REQUIRED_COUNT]
    result: list[DiscoveredURL] = []
    for i, url in enumerate(deduped, start=1):
        _, pattern = _is_valid_course_url(url)
        result.append(DiscoveredURL(index=i, url=url, url_pattern_matched=pattern))
        print(f"  [URL {i}] {url}")
    return result


# ── Strategy 1 — sitemapindex.xml ─────────────────────────────
def strategy_sitemapindex(playwright_instance) -> DiscoveryResult | None:
    """
    Fetch sitemapindex.xml, identify the most course-relevant child sitemap,
    extract 5 course URLs from it.
    """
    print("\n[STRATEGY 1] Fetching sitemapindex.xml...")
    browser, context, page = _make_page(playwright_instance)

    try:
        sitemap_index_url = f"{BASE}/sitemapindex.xml"
        xml_text = _fetch_text(page, sitemap_index_url)

        if not xml_text:
            print("[STRATEGY 1] Failed to fetch sitemapindex.xml")
            return None

        if not _is_sitemapindex(xml_text):
            # Might be a regular sitemap — try extracting course URLs directly
            print("[STRATEGY 1] sitemapindex.xml is a regular sitemap — scanning directly")
            course_urls = _collect_course_urls_from_sitemap_text(xml_text)
            if len(course_urls) >= REQUIRED_COUNT:
                print(f"[STRATEGY 1] Found {len(course_urls)} course URLs after filtering")
                discovered = _build_discovered_list(course_urls)
                return DiscoveryResult(source_strategy="sitemapindex", urls=discovered)
            print(f"[STRATEGY 1] Only {len(course_urls)} course URLs found in sitemapindex.xml — insufficient")
            return None

        child_urls = _extract_locs(xml_text)
        print(f"[STRATEGY 1] Found {len(child_urls)} child sitemaps:")
        for u in child_urls:
            print(f"  {u}")

        target = _best_child_sitemap(child_urls)
        if not target:
            print("[STRATEGY 1] No usable child sitemap found")
            return None

        print(f"[STRATEGY 1] Targeting: {target}")
        child_xml = _fetch_text(page, target)

        if not child_xml:
            print(f"[STRATEGY 1] Failed to fetch child sitemap: {target}")
            # Try remaining child sitemaps as fallback within this strategy
            for alt in child_urls:
                if alt == target:
                    continue
                print(f"[STRATEGY 1] Trying alternate child sitemap: {alt}")
                child_xml = _fetch_text(page, alt)
                if child_xml:
                    break

        if not child_xml:
            print("[STRATEGY 1] All child sitemaps failed")
            return None

        # Handle nested sitemapindex
        if _is_sitemapindex(child_xml):
            nested_children = _extract_locs(child_xml)
            print(f"[STRATEGY 1] Child sitemap is itself a sitemapindex with {len(nested_children)} entries")
            course_urls: list[str] = []
            for nested_url in nested_children:
                nested_xml = _fetch_text(page, nested_url)
                if nested_xml:
                    course_urls.extend(_collect_course_urls_from_sitemap_text(nested_xml))
                if len(course_urls) >= REQUIRED_COUNT:
                    break
        else:
            course_urls = _collect_course_urls_from_sitemap_text(child_xml)

        print(f"[STRATEGY 1] Found {len(course_urls)} course URLs after filtering")

        if len(course_urls) < REQUIRED_COUNT:
            # Scan remaining child sitemaps to top up
            print(f"[STRATEGY 1] Scanning remaining child sitemaps to reach {REQUIRED_COUNT}...")
            for alt in child_urls:
                if alt == target:
                    continue
                alt_xml = _fetch_text(page, alt)
                if alt_xml and not _is_sitemapindex(alt_xml):
                    course_urls.extend(_collect_course_urls_from_sitemap_text(alt_xml))
                    course_urls = _deduplicate(course_urls)
                    print(f"[STRATEGY 1] Running total: {len(course_urls)} course URLs")
                if len(course_urls) >= REQUIRED_COUNT:
                    break

        if len(course_urls) < REQUIRED_COUNT:
            print(f"[STRATEGY 1] Insufficient URLs ({len(course_urls)} < {REQUIRED_COUNT})")
            return None

        discovered = _build_discovered_list(course_urls)
        return DiscoveryResult(source_strategy="sitemapindex", urls=discovered)

    except Exception as exc:
        print(f"[STRATEGY 1] Unexpected error: {exc}")
        return None
    finally:
        browser.close()


# ── Strategy 2 — sitemap.xml direct scan ──────────────────────
def strategy_sitemap(playwright_instance) -> DiscoveryResult | None:
    """
    Fetch sitemap.xml directly. If it is a sitemapindex, recurse into children.
    """
    print("\n[STRATEGY 2] Fetching sitemap.xml...")
    browser, context, page = _make_page(playwright_instance)

    try:
        sitemap_url = f"{BASE}/sitemap.xml"
        xml_text = _fetch_text(page, sitemap_url)

        if not xml_text:
            print("[STRATEGY 2] Failed to fetch sitemap.xml")
            return None

        if _is_sitemapindex(xml_text):
            print("[STRATEGY 2] sitemap.xml is a sitemapindex — recursing into children")
            child_urls = _extract_locs(xml_text)
            print(f"[STRATEGY 2] Found {len(child_urls)} child sitemaps")
            course_urls: list[str] = []
            for child_url in child_urls:
                child_xml = _fetch_text(page, child_url)
                if child_xml and not _is_sitemapindex(child_xml):
                    course_urls.extend(_collect_course_urls_from_sitemap_text(child_xml))
                    course_urls = _deduplicate(course_urls)
                if len(course_urls) >= REQUIRED_COUNT:
                    break
        else:
            course_urls = _collect_course_urls_from_sitemap_text(xml_text)

        print(f"[STRATEGY 2] Found {len(course_urls)} course URLs after filtering")

        if len(course_urls) < REQUIRED_COUNT:
            print(f"[STRATEGY 2] Insufficient URLs ({len(course_urls)} < {REQUIRED_COUNT})")
            return None

        discovered = _build_discovered_list(course_urls)
        return DiscoveryResult(source_strategy="sitemap", urls=discovered)

    except Exception as exc:
        print(f"[STRATEGY 2] Unexpected error: {exc}")
        return None
    finally:
        browser.close()


# ── Strategy 3 — Homepage crawl ───────────────────────────────
def strategy_homepage(playwright_instance) -> DiscoveryResult | None:
    """
    Load the homepage, extract all internal <a href> links, filter for course
    patterns, follow promising links one level deep if needed.
    """
    print("\n[STRATEGY 3] Crawling homepage...")
    browser, context, page = _make_page(playwright_instance)

    try:
        html = _fetch_text(page, BASE + "/")
        if not html:
            print("[STRATEGY 3] Failed to load homepage")
            return None

        # networkidle gives JS-rendered content time to settle
        try:
            page.wait_for_load_state("networkidle", timeout=NAV_TIMEOUT)
        except Exception:
            pass  # domcontentloaded already waited; proceed

        html = page.content()
        soup = BeautifulSoup(html, "lxml")
        anchors = soup.find_all("a", href=True)

        internal_links: list[str] = []
        for a in anchors:
            href = a["href"].strip()
            full_url = urljoin(BASE, href)
            if TARGET_DOMAIN in urlparse(full_url).netloc:
                internal_links.append(full_url)

        internal_links = _deduplicate(internal_links)
        print(f"[STRATEGY 3] Found {len(internal_links)} internal links on homepage")

        course_urls: list[str] = []
        for link in internal_links:
            valid, _ = _is_valid_course_url(link)
            if valid:
                course_urls.append(link)

        print(f"[STRATEGY 3] {len(course_urls)} direct course URLs on homepage")

        if len(course_urls) < REQUIRED_COUNT:
            # Follow promising links one level deep
            promising_parents = [
                link for link in internal_links
                if any(kw in link.lower() for kw in ("study", "course", "undergraduate", "postgraduate"))
                and link not in course_urls
            ]
            print(f"[STRATEGY 3] Following {len(promising_parents)} promising links one level deep")

            for parent_url in promising_parents[:10]:
                try:
                    child_html = _fetch_text(page, parent_url)
                    if not child_html:
                        continue
                    child_soup = BeautifulSoup(child_html, "lxml")
                    for a in child_soup.find_all("a", href=True):
                        href = a["href"].strip()
                        full_url = urljoin(BASE, href)
                        valid, _ = _is_valid_course_url(full_url)
                        if valid:
                            course_urls.append(full_url)
                    course_urls = _deduplicate(course_urls)
                    if len(course_urls) >= REQUIRED_COUNT:
                        break
                except Exception as exc:
                    print(f"[STRATEGY 3] Error following {parent_url}: {exc}")
                    continue

        print(f"[STRATEGY 3] Found {len(course_urls)} course URLs after deep crawl")

        if len(course_urls) < REQUIRED_COUNT:
            print(f"[STRATEGY 3] Insufficient URLs ({len(course_urls)} < {REQUIRED_COUNT})")
            return None

        discovered = _build_discovered_list(course_urls)
        return DiscoveryResult(source_strategy="homepage_crawl", urls=discovered)

    except Exception as exc:
        print(f"[STRATEGY 3] Unexpected error: {exc}")
        return None
    finally:
        browser.close()


# ── Output writer ─────────────────────────────────────────────
def _write_output(result: DiscoveryResult) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    payload = {
        "source_strategy": result.source_strategy,
        "discovery_timestamp": datetime.now(timezone.utc).isoformat(),
        "total_found": len(result.urls),
        "urls": [
            {
                "index": du.index,
                "url": du.url,
                "url_pattern_matched": du.url_pattern_matched,
            }
            for du in result.urls
        ],
    }

    OUTPUT_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"\n[OUTPUT] Written to {OUTPUT_FILE}")


# ── Main ──────────────────────────────────────────────────────
def main() -> None:
    print("╔══════════════════════════════════════════════════════════╗")
    print("║   Coventry University Course Scraper — DISCOVER RUN      ║")
    print("╚══════════════════════════════════════════════════════════╝")

    result: DiscoveryResult | None = None

    with sync_playwright() as pw:
        # Strategy 1 — sitemapindex.xml
        result = strategy_sitemapindex(pw)

        # Strategy 2 — sitemap.xml (fallback)
        if result is None:
            print("\n[FALLBACK] Strategy 1 failed — attempting Strategy 2")
            result = strategy_sitemap(pw)

        # Strategy 3 — Homepage crawl (last resort)
        if result is None:
            print("\n[FALLBACK] Strategy 2 failed — attempting Strategy 3")
            result = strategy_homepage(pw)

    if result is None or len(result.urls) < REQUIRED_COUNT:
        tried = "Strategy 1 (sitemapindex.xml), Strategy 2 (sitemap.xml), Strategy 3 (homepage crawl)"
        actual = len(result.urls) if result else 0
        raise RuntimeError(
            f"Discovery failed: all strategies exhausted ({tried}). "
            f"Collected {actual}/{REQUIRED_COUNT} course URLs. "
            "Check Cloudflare challenge handling, sitemap availability, or URL filter patterns."
        )

    print(f"\n[SUCCESS] Strategy '{result.source_strategy}' produced {len(result.urls)} course URLs")
    _write_output(result)


if __name__ == "__main__":
    main()
