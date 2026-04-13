# Coventry University Course Scraper

> Programmatically discovers and extracts structured course data from [coventry.ac.uk](https://www.coventry.ac.uk/) — built for Senbonzakura Consultancy Private Limited.

![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-blue)
![Playwright](https://img.shields.io/badge/Playwright-Chromium-green)
![BeautifulSoup4](https://img.shields.io/badge/BeautifulSoup4-lxml-orange)
![Data](https://img.shields.io/badge/Data-5%20courses-purple)

---

## Overview

This scraper discovers course URLs from the official Coventry University sitemap, fetches each course page using a real Chromium browser to bypass Cloudflare WAF, and extracts 27 structured fields per course into a single JSON file. All data originates exclusively from `https://www.coventry.ac.uk/` — no third-party aggregators, no pre-existing datasets. The final output is `output/courses.json`, a human-readable JSON file containing 5 course records with a metadata block.

---

## Project Structure

```
coventry_scraper/
├── scraper/
│   ├── recon.py        — target investigation: robots.txt, sitemaps, bot detection headers
│   ├── discover.py     — course URL discovery via sitemapindex.xml → course-sitemap.xml
│   ├── extractor.py    — per-page field extraction (separate logic for CPD and PG pages)
│   └── pipeline.py     — end-to-end orchestrator: reads URLs, calls extractor, writes output
├── output/
│   ├── course_urls.json — 5 discovered course URLs with source metadata
│   └── courses.json    — final structured output: 5 course records + scraper metadata
├── requirements.txt
└── README.md
```

| File | Role |
|------|------|
| `recon.py` | One-time investigation script. Confirms Cloudflare presence, robots.txt rules, sitemap availability, and whether pages are server-side rendered. Run once before development. |
| `discover.py` | Fetches `sitemapindex.xml` via Playwright, identifies `course-sitemap.xml`, filters URLs by path pattern, and writes `output/course_urls.json`. |
| `extractor.py` | Public interface: `extract_course(url) -> dict`. Detects page type (CPD or PG), routes to the appropriate parser, returns a 27-field dict. All missing fields return `"NA"`. |
| `pipeline.py` | Reads `course_urls.json`, calls `extract_course()` for each URL sequentially, validates schema, and writes `output/courses.json` after all 5 records are collected. |

---

## Dependencies

### Python Packages

| Package | Why it is needed |
|---------|-----------------|
| `httpx` | HTTP client used in `recon.py` for lightweight pre-scraping investigation |
| `beautifulsoup4` | HTML and XML parsing for all field extraction logic |
| `lxml` | High-performance parser backend for BeautifulSoup (`lxml` for HTML, `lxml-xml` for sitemaps) |
| `playwright` | Headless Chromium automation — required to pass Cloudflare's browser fingerprint checks |
| `playwright-stealth` | Removes Playwright's bot-detection signals (webdriver flag, JS inconsistencies) from every page context |

### System Requirements

- **Python 3.11 or higher**
- **Chromium browser** — installed separately via Playwright (see Setup step 4)

---

## Setup

Follow these steps exactly on a clean machine.

**Step 1 — Download the project**

```bash
# If cloning from a repository:
git clone <repository-url>
cd coventry_scraper

# Or unzip the submission archive and navigate into it:
cd coventry_scraper
```

**Step 2 — Create and activate a virtual environment**

```bash
python -m venv venv

# macOS / Linux:
source venv/bin/activate

# Windows:
venv\Scripts\activate
```

**Step 3 — Install Python dependencies**

```bash
pip install -r requirements.txt
```

**Step 4 — Install Playwright's Chromium browser**

```bash
playwright install chromium
```

**Step 5 — Verify setup (optional but recommended)**

```bash
python scraper/recon.py
```

Expected output: a multi-section report confirming Cloudflare is present, course pages are not disallowed in `robots.txt`, and `sitemapindex.xml` is accessible. This script is informational only — it does not modify any files.

---

## How to Run

### Option A — Full pipeline (recommended)

Runs all stages end-to-end and writes the final output file:

```bash
python scraper/pipeline.py
```

**What happens:**
1. Reads `output/course_urls.json`
2. Calls `extract_course()` for each of the 5 URLs sequentially
3. Validates each record against the 27-field schema
4. Writes `output/courses.json` after all 5 records are collected
5. Prints a `PIPELINE COMPLETE` report with per-course summary and critical field checks

**Expected runtime:** 60–90 seconds for 5 courses (includes a 2-second polite delay between requests).

---

### Option B — Individual stages

```bash
# Stage 1: Reconnaissance — investigates the target site (informational, no file output)
python scraper/recon.py

# Stage 2: URL Discovery — fetches sitemapindex.xml and writes output/course_urls.json
python scraper/discover.py

# Stage 3: Single-course extraction test — fetches one PG and one CPD course, prints results
python scraper/extractor.py

# Stage 4: Full pipeline — reads course_urls.json, writes output/courses.json
python scraper/pipeline.py
```

---

### Important Notes

- **Playwright is mandatory.** Plain `httpx` requests to `coventry.ac.uk` return HTTP 400 from Cloudflare WAF. Every fetch in this project uses a headless Chromium browser with stealth evasion applied.
- **A 2-second delay** is enforced between pipeline requests to avoid rate limiting.
- **All output files** are written to the `output/` directory.
- **Do not run stages out of order.** `pipeline.py` depends on `output/course_urls.json` produced by `discover.py`.

---

## Output Format

### File: `output/courses.json`

Top-level structure:

```json
{
  "scraper_metadata": {
    "university": "Coventry University",
    "total_courses": 5,
    "run_timestamp": "2026-04-13T14:18:37.371059+00:00",
    "source_urls_file": "output/course_urls.json"
  },
  "courses": [ ... ]
}
```

**Metadata fields:**

| Field | Description |
|-------|-------------|
| `university` | Static identifier for the scraped institution |
| `total_courses` | Number of course records in the `courses` array |
| `run_timestamp` | ISO 8601 UTC timestamp of the pipeline run |
| `source_urls_file` | Path to the `course_urls.json` file used as input |

---

### Course Record Schema (27 fields)

Every course record contains exactly 27 fields. Fields not published on the course page return `"NA"`.

#### Core Info

| Field | Description / Source |
|-------|---------------------|
| `program_course_name` | Course title from the page `<h1>` tag. Never inferred from the URL slug. |
| `university_name` | Static value: `"Coventry University"` |
| `course_website_url` | The scraped page URL, carried through from `course_urls.json` |
| `campus` | Location extracted from the course features section or CPD key-value block |
| `country` | Static value: `"United Kingdom"` |
| `address` | Extracted from the page footer; falls back to `"Priory Street, Coventry CV1 5FB, United Kingdom"` |

#### Academic Info

| Field | Description / Source |
|-------|---------------------|
| `study_level` | CPD pages: `"CPD/Short courses"`. PG pages: `"Postgraduate"` or `"Postgraduate \| Conversion course"` if that label appears on the page |
| `course_duration` | From the course features section (e.g. `"1 year full-time"`, `"1 day"`) |
| `all_intakes_available` | All start dates joined with ` / `, prefixed with year of entry where available |

#### Requirements and Fees

| Field | Description / Source |
|-------|---------------------|
| `mandatory_documents_required` | Portfolio requirement text from the entry requirements section. `"NA"` if no portfolio section exists |
| `yearly_tuition_fee` | Extracted from the fees table: `"UK: £X \| International: £Y"`. CPD pages return a single flat fee |
| `scholarship_availability` | `"Yes - International Scholarships available..."` if that text appears in the fees section; otherwise `"NA"` |
| `gre_gmat_mandatory_min_score` | Not published by Coventry University. Returns `"NA"` |
| `indian_regional_institution_restrictions` | Not published. Returns `"NA"` |
| `class_12_boards_accepted` | Not published. Returns `"NA"` |
| `gap_year_max_accepted` | Not published. Returns `"NA"` |
| `mandatory_work_exp` | Work experience clause extracted from entry requirements text if present; otherwise `"NA"` |

#### English Requirements

| Field | Description / Source |
|-------|---------------------|
| `min_ielts` | Extracted from the entry requirements section where `"IELTS:"` appears. CPD pages: `"NA"` |
| `min_duolingo` | Not published on individual course pages. Returns `"NA"` |
| `english_waiver_class12` | Not published. Returns `"NA"` |
| `english_waiver_moi` | Not published. Returns `"NA"` |
| `kaplan_test_of_english` | Not published on individual course pages. Returns `"NA"` |
| `min_pte` | Not published on individual course pages. Returns `"NA"` |
| `min_toefl` | Not published on individual course pages. Returns `"NA"` |

#### Academic Entry Requirements

| Field | Description / Source |
|-------|---------------------|
| `ug_academic_min_gpa` | Full text of the "Typical entry requirements" section. UK degree classifications are used (e.g. `"2:1 or above"`), not GPA |
| `twelfth_pass_min_cgpa` | Not applicable for UK postgraduate admissions. Returns `"NA"` |
| `max_backlogs` | Not published. Returns `"NA"` |

---

### Sample Record

Course 5 — Automotive Journalism MA (live values from `output/courses.json`):

```json
{
  "program_course_name": "Automotive Journalism MA",
  "university_name": "Coventry University",
  "course_website_url": "https://www.coventry.ac.uk/course-structure/pg/cas/automotive-journalism-ma/",
  "campus": "Coventry University (Coventry)",
  "country": "United Kingdom",
  "address": "Priory Street Coventry CV1 5FB United Kingdom",
  "study_level": "Postgraduate | Conversion course",
  "course_duration": "1 year full-time",
  "all_intakes_available": "Year of entry: 2025-26, 2026-27 | Start dates: May 2026 / July 2026",
  "mandatory_documents_required": "NA",
  "yearly_tuition_fee": "UK: £11,200 | International: £18,600",
  "scholarship_availability": "Yes - International Scholarships available. See: https://www.coventry.ac.uk/international-students-hub/apply-for-a-scholarship/",
  "gre_gmat_mandatory_min_score": "NA",
  "indian_regional_institution_restrictions": "NA",
  "class_12_boards_accepted": "NA",
  "gap_year_max_accepted": "NA",
  "min_duolingo": "NA",
  "english_waiver_class12": "NA",
  "english_waiver_moi": "NA",
  "min_ielts": "6.5 overall, with no component lower than 5.5.",
  "kaplan_test_of_english": "NA",
  "min_pte": "NA",
  "min_toefl": "NA",
  "ug_academic_min_gpa": "An undergraduate degree 2:2 or above (or international equivalent) in any discipline, or demonstrable and appropriate work experience together with relevant professional qualifications.",
  "twelfth_pass_min_cgpa": "NA",
  "mandatory_work_exp": "demonstrable and appropriate work experience together with relevant professional qualifications.",
  "max_backlogs": "NA"
}
```

---

## Data Source Compliance

- ✅ All data is scraped exclusively from `https://www.coventry.ac.uk/`
- ✅ Course URLs were discovered programmatically by fetching `https://www.coventry.ac.uk/sitemapindex.xml` and parsing `https://www.coventry.ac.uk/course-sitemap.xml`
- ✅ Each course page was fetched in real time during the pipeline run and parsed directly
- ✅ No third-party platforms used (Shiksha, Yocket, LeverageEdu, Hotcourses, or similar)
- ✅ No pre-existing datasets or cached HTML used
- ✅ No manual copy-pasting of any field value
- ✅ Course pages are not disallowed in Coventry's `robots.txt` — confirmed during recon

---

## Technical Decisions

**Why Playwright instead of httpx / requests**

Coventry University's infrastructure is protected by Cloudflare WAF. All direct HTTP client requests (httpx, requests, urllib) return HTTP 400 before reaching the origin server. Playwright launches a real Chromium browser which passes Cloudflare's browser fingerprint checks. `playwright-stealth` is applied to every page context to remove additional bot-detection signals such as the `navigator.webdriver` flag and JavaScript timing inconsistencies.

**Why sitemapindex.xml for URL discovery**

The course search page (`/study-at-coventry/find-a-course/`) is a JavaScript-rendered shell with no accessible API — confirmed during recon. The sitemap route is deterministic, requires no UI interaction, and `sitemapindex.xml` contained a dedicated `course-sitemap.xml` with 296 clean, filterable course page URLs. This is a more reliable and maintainable discovery strategy than driving a search UI.

**Why two separate extractors (CPD vs PG)**

CPD pages use a flat two-column key-value grid where each label (`<strong>`) and its value live in adjacent sibling `<div>` elements within a Bootstrap grid row. PG pages use anchor-linked sections with `<h3>` headings, structured fee tables, and multi-paragraph entry requirement blocks. Combining both into one function would require branching on every field — two focused extractors are simpler, easier to debug, and independently maintainable.

**Why many fields return "NA"**

Fields such as `min_pte`, `min_toefl`, `min_duolingo`, `gre_gmat_mandatory_min_score`, and `indian_regional_institution_restrictions` are India-specific admission concepts that UK universities do not publish on individual course pages. PTE and TOEFL scores appear only on a central English requirements page linked from course pages — scraping that linked page would exceed the per-course-page scope. Returning `"NA"` is accurate; it is not a failure of extraction.

---

## Known Limitations

1. **CPD course dates may be historical.** Coventry does not remove past CPD pages from their sitemap. The scraper extracts the date shown on the live page — for the two CPD courses in this dataset, those dates are in 2024. The extracted data accurately reflects what is published.

2. **Course 4 (Automotive and Transport Design MA) shows two start dates, not three.** An earlier draft spec noted "March 2026 / May 2026 / July 2026" as three intake dates. As of the pipeline run date (April 2026), the March 2026 intake has passed and Coventry has removed it from the live page. The scraper correctly reflects current live data: `"May 2026 / July 2026"`.

3. **PTE, TOEFL, Duolingo, and Kaplan scores return "NA" for all courses.** These are not published on individual course pages. They appear only on Coventry's central English language requirements page. Following that link would exceed the per-course scope.

4. **India-specific admission fields return "NA" for all courses.** Fields including `class_12_boards_accepted`, `max_backlogs`, `gap_year_max_accepted`, `twelfth_pass_min_cgpa`, and `indian_regional_institution_restrictions` are not published by UK universities in any form.

---

## Quick Reference

| Command | What it does |
|---------|-------------|
| `python scraper/recon.py` | Investigates the target site — informational only, no files written |
| `python scraper/discover.py` | Discovers 5 course URLs → writes `output/course_urls.json` |
| `python scraper/extractor.py` | Tests extraction on one PG and one CPD course, prints results |
| `python scraper/pipeline.py` | Full run → writes `output/courses.json` |
