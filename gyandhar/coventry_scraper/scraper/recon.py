"""
recon.py — Coventry University Course Scraper
Reconnaissance script: investigates robots.txt, sitemaps, API endpoints,
course page structure, and bot-detection headers BEFORE any extraction logic.

Run:  python scraper/recon.py
"""

import io
import sys

import httpx
from bs4 import BeautifulSoup

# Force UTF-8 output on Windows (avoids cp1252 UnicodeEncodeError with box-drawing chars)
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

BASE = "https://www.coventry.ac.uk"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9",
}

DIVIDER = "─" * 60


def fetch(url: str, *, as_json: bool = False, timeout: int = 20) -> tuple[httpx.Response | None, str | None]:
    """Return (response, error_message). Never raises."""
    try:
        with httpx.Client(headers=HEADERS, follow_redirects=True, timeout=timeout) as client:
            r = client.get(url)
        return r, None
    except Exception as exc:
        return None, str(exc)


def section(title: str) -> None:
    print(f"\n{'═' * 60}")
    print(f"  {title}")
    print(f"{'═' * 60}")


# ─────────────────────────────────────────────────────────────
# RECON TARGET 1 — robots.txt
# ─────────────────────────────────────────────────────────────
def recon_robots() -> dict:
    section("RECON TARGET 1 — robots.txt")
    url = f"{BASE}/robots.txt"
    resp, err = fetch(url)

    result = {"status": None, "course_paths_allowed": "UNCLEAR"}

    if err:
        print(f"  ERROR fetching {url}: {err}")
        return result

    print(f"  URL     : {url}")
    print(f"  Status  : {resp.status_code}")

    if resp.status_code != 200:
        print(f"  robots.txt not found (HTTP {resp.status_code})")
        result["status"] = resp.status_code
        result["course_paths_allowed"] = "UNCLEAR"
        return result

    result["status"] = 200
    text = resp.text

    print(f"\n  ── Full contents ──")
    print(text[:4000])
    if len(text) > 4000:
        print(f"  ... [truncated, total {len(text)} chars]")

    # Analyse Disallow rules for education-related paths
    EDUCATION_PATTERNS = ["/study", "/course", "/search", "/undergraduate", "/postgraduate", "/find-a-course"]
    disallowed_matches = []
    allowed_matches = []

    for line in text.splitlines():
        line_stripped = line.strip()
        if line_stripped.lower().startswith("disallow:"):
            path = line_stripped.split(":", 1)[1].strip()
            if any(p in path.lower() for p in EDUCATION_PATTERNS):
                disallowed_matches.append(path)
        elif line_stripped.lower().startswith("allow:"):
            path = line_stripped.split(":", 1)[1].strip()
            if any(p in path.lower() for p in EDUCATION_PATTERNS):
                allowed_matches.append(path)

    print(f"\n  ── Education-relevant Disallow rules ──")
    if disallowed_matches:
        for p in disallowed_matches:
            print(f"    DISALLOWED: {p}")
        result["course_paths_allowed"] = "DISALLOWED"
    else:
        print("    None found.")

    print(f"\n  ── Education-relevant Allow rules ──")
    if allowed_matches:
        for p in allowed_matches:
            print(f"    ALLOWED: {p}")
        result["course_paths_allowed"] = "ALLOWED"
    else:
        print("    None found (no explicit Allow rules for these paths).")

    if not disallowed_matches and not allowed_matches:
        result["course_paths_allowed"] = "ALLOWED"  # not blocked = implicitly allowed

    print(f"\n  CONCLUSION — COURSE PAGES: {result['course_paths_allowed']}")
    return result


# ─────────────────────────────────────────────────────────────
# RECON TARGET 2 — XML Sitemap
# ─────────────────────────────────────────────────────────────
def recon_sitemap() -> dict:
    section("RECON TARGET 2 — XML Sitemap")
    url = f"{BASE}/sitemap.xml"
    resp, err = fetch(url)

    result = {"found": False, "course_pattern": None}

    if err:
        print(f"  ERROR fetching {url}: {err}")
        return result

    print(f"  URL    : {url}")
    print(f"  Status : {resp.status_code}")

    if resp.status_code != 200:
        print("  NO SITEMAP FOUND")
        return result

    result["found"] = True
    content = resp.text

    soup = BeautifulSoup(content, "lxml-xml")

    # Check if sitemap index
    sitemapindex = soup.find("sitemapindex")
    if sitemapindex:
        print("  Type: SITEMAP INDEX")
        child_locs = [loc.get_text(strip=True) for loc in sitemapindex.find_all("loc")]
        print(f"  Child sitemaps ({len(child_locs)} total):")
        for loc in child_locs:
            print(f"    {loc}")

        # Find most relevant child sitemap
        COURSE_KEYWORDS = ["course", "study", "undergraduate", "postgraduate"]
        relevant = [l for l in child_locs if any(k in l.lower() for k in COURSE_KEYWORDS)]
        if not relevant:
            relevant = child_locs[:1]  # fallback: fetch first

        target_sitemap = relevant[0] if relevant else None
        if target_sitemap:
            print(f"\n  Fetching most relevant child sitemap: {target_sitemap}")
            child_resp, child_err = fetch(target_sitemap)
            if child_err:
                print(f"  ERROR: {child_err}")
            elif child_resp.status_code == 200:
                child_soup = BeautifulSoup(child_resp.text, "lxml-xml")
                urls = [loc.get_text(strip=True) for loc in child_soup.find_all("loc")]
                print(f"  Total URLs in child sitemap: {len(urls)}")
                print(f"  First 20 URLs:")
                for u in urls[:20]:
                    print(f"    {u}")
                # Find course pattern
                course_urls = [u for u in urls if any(k in u.lower() for k in COURSE_KEYWORDS)]
                if course_urls:
                    result["course_pattern"] = course_urls[0]
                    print(f"\n  Course URL pattern example: {course_urls[0]}")
            else:
                print(f"  Child sitemap HTTP {child_resp.status_code}")
    else:
        # Regular sitemap
        print("  Type: REGULAR SITEMAP")
        urls = [loc.get_text(strip=True) for loc in soup.find_all("loc")]
        print(f"  Total URLs: {len(urls)}")
        print(f"  First 20 URLs:")
        for u in urls[:20]:
            print(f"    {u}")

        COURSE_KEYWORDS = ["course", "study", "undergraduate", "postgraduate"]
        course_urls = [u for u in urls if any(k in u.lower() for k in COURSE_KEYWORDS)]
        if course_urls:
            result["course_pattern"] = course_urls[0]
            print(f"\n  Course URL pattern example: {course_urls[0]}")
        else:
            print("\n  No course-pattern URLs detected in sitemap.")

    return result


# ─────────────────────────────────────────────────────────────
# RECON TARGET 3 — Course Search API Sniffing
# ─────────────────────────────────────────────────────────────
def _classify_response(resp: httpx.Response) -> dict:
    """Return content type classification and key signals."""
    ct = resp.headers.get("content-type", "")
    body = resp.text

    is_json = "json" in ct
    is_html = "html" in ct

    signals = {
        "status": resp.status_code,
        "content_type": ct,
        "is_json": is_json,
        "is_html": is_html,
        "body_preview": body[:500] if body else "",
        "js_shell": False,
        "page_title": None,
    }

    if is_html and body:
        soup = BeautifulSoup(body, "lxml")
        title_tag = soup.find("title")
        signals["page_title"] = title_tag.get_text(strip=True) if title_tag else None

        # JS shell detection heuristics
        app_div = soup.find("div", {"id": "app"})
        root_div = soup.find("div", {"id": "root"})
        noscript = soup.find("noscript")
        has_empty_app = app_div is not None and not app_div.get_text(strip=True)
        has_empty_root = root_div is not None and not root_div.get_text(strip=True)
        signals["js_shell"] = bool(has_empty_app or has_empty_root or noscript)

    return signals


def recon_api() -> dict:
    section("RECON TARGET 3 — Course Search API Sniffing")

    probe_urls = [
        f"{BASE}/study-at-coventry/find-a-course/",
        f"{BASE}/api/courses",
        f"{BASE}/api/v1/courses",
        f"{BASE}/search/?query=computer+science&format=json",
        "https://coventry.funnelback.com/s/search.html?collection=coventry-courses&query=computer+science",
        "https://s.funnelback.com/s/search.html?collection=coventry&query=computer+science",
    ]

    result = {"api_found": False, "api_url": None}

    for url in probe_urls:
        print(f"\n  {DIVIDER}")
        print(f"  Probing: {url}")
        resp, err = fetch(url)
        if err:
            print(f"  ERROR: {err}")
            continue

        signals = _classify_response(resp)
        print(f"  HTTP Status  : {signals['status']}")
        print(f"  Content-Type : {signals['content_type']}")

        if signals["is_json"] and signals["status"] == 200:
            print(f"  JSON RESPONSE DETECTED")
            print(f"  Preview (first 500 chars):")
            print(f"    {signals['body_preview']}")
            result["api_found"] = True
            result["api_url"] = url
            print(f"  >>> API FOUND: {url}")

        elif signals["is_html"] and signals["status"] == 200:
            print(f"  Page title   : {signals['page_title']}")
            print(f"  JS shell     : {'YES' if signals['js_shell'] else 'NO'}")
            if signals["js_shell"]:
                print(f"  WARNING: Page appears to be a JS-rendered shell — content may not be in raw HTML")
            else:
                print(f"  Page appears to have server-side rendered content")

        elif signals["status"] in (301, 302, 307, 308):
            location = resp.headers.get("location", "N/A")
            print(f"  Redirect to  : {location}")

        else:
            print(f"  Not useful (HTTP {signals['status']})")

    if result["api_found"]:
        print(f"\n  CONCLUSION — API FOUND: {result['api_url']}")
    else:
        print(f"\n  CONCLUSION — NO API FOUND — DOM SCRAPING REQUIRED")

    return result


# ─────────────────────────────────────────────────────────────
# RECON TARGET 4 — Single Course Page Test
# ─────────────────────────────────────────────────────────────
KEY_FIELD_TERMS = ["ielts", "tuition", "duration", "entry requirements", "ucas", "award", "qualification"]

def _check_key_fields(body: str) -> dict:
    body_lower = body.lower()
    found = {term: term in body_lower for term in KEY_FIELD_TERMS}
    return found


def recon_course_page() -> dict:
    section("RECON TARGET 4 — Single Course Page Test")

    test_urls = [
        (
            "Pattern A (course-structure)",
            f"{BASE}/course-structure/2024-25/faculty-of-engineering-environment-and-computing/"
            "school-of-computing-mathematics-and-data-sciences/bsc-hons-computer-science/",
        ),
        (
            "Pattern B (study-at-coventry/undergraduate-study)",
            f"{BASE}/study-at-coventry/undergraduate-study/courses/computer-science-bsc/",
        ),
    ]

    result = {"ssr_confirmed": False, "working_url_pattern": None}

    for label, url in test_urls:
        print(f"\n  {DIVIDER}")
        print(f"  Testing [{label}]")
        print(f"  URL: {url}")
        resp, err = fetch(url)
        if err:
            print(f"  ERROR: {err}")
            continue

        print(f"  HTTP Status : {resp.status_code}")

        if resp.status_code == 200:
            fields = _check_key_fields(resp.text)
            found_fields = [k for k, v in fields.items() if v]
            missing_fields = [k for k, v in fields.items() if not v]

            print(f"  KEY FIELDS IN RAW HTML: {'YES' if found_fields else 'NO'}")
            print(f"    Found   : {found_fields if found_fields else 'none'}")
            print(f"    Missing : {missing_fields if missing_fields else 'none'}")

            if found_fields:
                result["ssr_confirmed"] = True
                result["working_url_pattern"] = url
                print(f"  CONCLUSION — SSR CONFIRMED")
            else:
                print(f"  CONCLUSION — JS RENDERING REQUIRED (or wrong URL)")

        elif resp.status_code in (301, 302, 307, 308):
            location = resp.headers.get("location", "N/A")
            print(f"  Redirect → {location}")
        else:
            print(f"  Page not found or error (HTTP {resp.status_code})")

    return result


# ─────────────────────────────────────────────────────────────
# RECON TARGET 5 — Response Headers & Bot Detection
# ─────────────────────────────────────────────────────────────
BOT_DETECTION_HEADERS = {
    "cloudflare": ["cf-ray", "cf-cache-status", "cf-request-id"],
    "akamai": ["x-akamai-transformed", "x-akamai-request-id", "akamai-origin-hop"],
    "imperva": ["x-iinfo", "x-cdn"],
    "generic_waf": ["x-waf-", "x-sucuri-", "x-fw-", "x-protected-by"],
}


def recon_headers() -> dict:
    section("RECON TARGET 5 — Response Headers & Bot Detection")

    # Use the main site homepage for header analysis
    probe_url = f"{BASE}/study-at-coventry/find-a-course/"
    resp, err = fetch(probe_url)

    result = {"bot_detection_level": "NONE", "headers": {}}

    if err:
        print(f"  ERROR: {err}")
        return result

    print(f"  Probed URL: {probe_url}")
    print(f"  HTTP Status: {resp.status_code}")

    headers = dict(resp.headers)
    result["headers"] = headers

    # Print key headers
    PRINT_HEADERS = ["server", "x-powered-by", "content-type", "x-cache", "via", "age"]
    print(f"\n  ── Key headers ──")
    for h in PRINT_HEADERS:
        val = headers.get(h) or headers.get(h.title())
        if val:
            print(f"    {h}: {val}")

    # Bot detection
    print(f"\n  ── Bot/CDN detection headers ──")
    detected_systems = []
    for system, header_names in BOT_DETECTION_HEADERS.items():
        for h in header_names:
            matched = [(k, v) for k, v in headers.items() if h.lower() in k.lower()]
            if matched:
                for k, v in matched:
                    print(f"    [{system.upper()}] {k}: {v}")
                    detected_systems.append(system)

    # Cookie analysis
    print(f"\n  ── Set-Cookie headers ──")
    cookie_headers = resp.headers.get_list("set-cookie") if hasattr(resp.headers, "get_list") else []
    if not cookie_headers:
        raw_cookie = headers.get("set-cookie")
        cookie_headers = [raw_cookie] if raw_cookie else []

    if cookie_headers:
        for c in cookie_headers:
            c_lower = c.lower()
            flags = []
            if any(kw in c_lower for kw in ["__cf", "cf_", "cloudflare"]):
                flags.append("CLOUDFLARE-SESSION")
            if any(kw in c_lower for kw in ["ak_bmsc", "bm_sz", "bm_sv"]):
                flags.append("AKAMAI-BOT-MANAGER")
            if any(kw in c_lower for kw in ["incap_ses", "visid_incap"]):
                flags.append("IMPERVA")
            if "httponly" in c_lower:
                flags.append("HttpOnly")
            if "secure" in c_lower:
                flags.append("Secure")
            label = f" [{', '.join(flags)}]" if flags else ""
            print(f"    {c[:120]}{label}")
    else:
        print("    None set")

    # Determine bot detection level
    unique_systems = set(detected_systems)
    if "cloudflare" in unique_systems or "akamai" in unique_systems:
        level = "HIGH"
    elif "imperva" in unique_systems or unique_systems:
        level = "MEDIUM"
    elif cookie_headers:
        level = "LOW"
    else:
        level = "NONE"

    result["bot_detection_level"] = level
    print(f"\n  CONCLUSION — BOT DETECTION LEVEL: {level}")
    return result


# ─────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────
def main() -> None:
    print("╔══════════════════════════════════════════════════════════╗")
    print("║   Coventry University Course Scraper — RECON RUN         ║")
    print("╚══════════════════════════════════════════════════════════╝")

    r1 = recon_robots()
    r2 = recon_sitemap()
    r3 = recon_api()
    r4 = recon_course_page()
    r5 = recon_headers()

    # ── SUMMARY BLOCK ──────────────────────────────────────────
    print("\n")
    print("  ══════════════ RECON SUMMARY ══════════════")
    print(f"  robots.txt course paths : {r1.get('course_paths_allowed', 'UNCLEAR')}")
    print(f"  Sitemap found           : {'YES' if r2.get('found') else 'NO'}")
    print(f"  Course URL pattern      : {r2.get('course_pattern') or r4.get('working_url_pattern') or 'UNKNOWN'}")
    api_val = f"YES  {r3['api_url']}" if r3.get("api_found") else "NO"
    print(f"  Hidden API found        : {api_val}")
    print(f"  Raw HTML has content    : {'YES' if r4.get('ssr_confirmed') else 'NO'}")
    js_needed = "NO" if r4.get("ssr_confirmed") else "YES"
    print(f"  JS rendering needed     : {js_needed}")
    print(f"  Bot detection level     : {r5.get('bot_detection_level', 'UNKNOWN')}")

    # Recommended next step logic
    if r3.get("api_found"):
        next_step = "Use the discovered API endpoint in discover.py to enumerate course URLs directly."
    elif r4.get("ssr_confirmed"):
        next_step = "Implement discover.py to enumerate course URLs via sitemap or search page (SSR confirmed — no Playwright needed)."
    else:
        next_step = "Investigate JS rendering with Playwright — raw HTML does not contain course content."

    print(f"  Recommended next step   : {next_step}")
    print("  ═══════════════════════════════════════════")


if __name__ == "__main__":
    main()
