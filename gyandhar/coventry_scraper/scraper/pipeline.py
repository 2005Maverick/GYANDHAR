"""
pipeline.py — Coventry University Course Scraper
Orchestrates the full run: reads 5 URLs from output/course_urls.json,
calls extract_course() for each, validates results, and writes
output/courses.json.

Run:
    python scraper/pipeline.py
Output:
    output/courses.json
"""

from __future__ import annotations

import io
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# ── Ensure package root is on sys.path so both invocation styles work:
#    python scraper/pipeline.py        (script)
#    python -m scraper.pipeline        (module)
_pkg_root = Path(__file__).parent.parent
if str(_pkg_root) not in sys.path:
    sys.path.insert(0, str(_pkg_root))

from scraper.extractor import extract_course  # noqa: E402

# ── Force UTF-8 output on Windows ─────────────────────────────
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ── Paths ──────────────────────────────────────────────────────
OUTPUT_DIR = Path(__file__).parent.parent / "output"
URLS_FILE = OUTPUT_DIR / "course_urls.json"
COURSES_FILE = OUTPUT_DIR / "courses.json"

EXPECTED_URL_COUNT = 5
REQUEST_DELAY_SECONDS = 2

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


# ──────────────────────────────────────────────────────────────
# URL loader
# ──────────────────────────────────────────────────────────────

def load_urls(path: str) -> list[str]:
    """
    Reads output/course_urls.json.
    Returns list of exactly 5 URL strings.
    Raises ValueError if fewer or more than 5 URLs found.
    """
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    urls = [entry["url"] for entry in data["urls"]]

    if len(urls) != EXPECTED_URL_COUNT:
        raise ValueError(
            f"Expected {EXPECTED_URL_COUNT} URLs in {path}, "
            f"found {len(urls)}."
        )

    return urls


# ──────────────────────────────────────────────────────────────
# Record validator
# ──────────────────────────────────────────────────────────────

def validate_record(record: dict, index: int) -> list[str]:
    """
    Checks a single extracted record for quality issues.
    Returns list of warning strings (empty list = clean record).
    """
    warnings: list[str] = []

    # All 27 schema keys must be present
    missing = [k for k in SCHEMA_KEYS if k not in record]
    if missing:
        warnings.append(f"Record [{index}] missing schema keys: {missing}")

    # No value may be None or empty string
    for key in SCHEMA_KEYS:
        val = record.get(key)
        if val is None or val == "":
            warnings.append(
                f"Record [{index}] field '{key}' is None or empty string"
            )

    # Static field checks
    if record.get("university_name") != "Coventry University":
        warnings.append(
            f"Record [{index}] university_name is "
            f"'{record.get('university_name')}' — expected 'Coventry University'"
        )

    if record.get("country") != "United Kingdom":
        warnings.append(
            f"Record [{index}] country is "
            f"'{record.get('country')}' — expected 'United Kingdom'"
        )

    url = record.get("course_website_url", "")
    if not url.startswith("https://www.coventry.ac.uk/"):
        warnings.append(
            f"Record [{index}] course_website_url does not start with "
            f"'https://www.coventry.ac.uk/': '{url}'"
        )

    if record.get("program_course_name") == "NA":
        warnings.append(
            f"Record [{index}] program_course_name is 'NA' — extraction failed"
        )

    # Extraction errors reported by extractor
    extraction_errors = record.get("extraction_errors")
    if extraction_errors:
        warnings.append(
            f"Record [{index}] extraction_errors: {extraction_errors}"
        )

    return warnings


# ──────────────────────────────────────────────────────────────
# Output writer
# ──────────────────────────────────────────────────────────────

def write_output(results: list[dict], path: str) -> None:
    """
    Writes final JSON to output/courses.json.
    Includes scraper_metadata block and courses array.
    Written once after all records are collected.
    """
    # Strip extraction_errors from each record before writing —
    # it is pipeline-internal metadata, not part of the schema.
    clean_courses = [
        {k: v for k, v in record.items() if k != "extraction_errors"}
        for record in results
    ]

    payload = {
        "scraper_metadata": {
            "university": "Coventry University",
            "total_courses": len(clean_courses),
            "run_timestamp": datetime.now(timezone.utc).isoformat(),
            "source_urls_file": str(URLS_FILE),
        },
        "courses": clean_courses,
    }

    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


# ──────────────────────────────────────────────────────────────
# Final report printer
# ──────────────────────────────────────────────────────────────

def print_final_report(results: list[dict]) -> None:
    """Prints structured validation report after pipeline completes."""
    courses_with_warnings = sum(
        1 for r in results if r.get("extraction_errors")
    )

    print("\n══════════════ PIPELINE COMPLETE ══════════════")
    print(f"Total courses extracted : {len(results)}")
    print(f"Courses with warnings   : {courses_with_warnings}")
    print(f"Output file             : {COURSES_FILE}")

    print("\nPer-course summary:")
    for i, record in enumerate(results, start=1):
        name = record.get("program_course_name", "UNKNOWN")
        level = record.get("study_level", "UNKNOWN")
        fee = record.get("yearly_tuition_fee", "UNKNOWN")
        print(f"  [{i}] {name} | {level} | {fee}")

    # Schema validation
    print("\nSchema validation:")
    all_valid = True
    for i, record in enumerate(results, start=1):
        missing = [k for k in SCHEMA_KEYS if k not in record]
        if missing:
            print(f"  ❌ Record [{i}] missing fields: {missing}")
            all_valid = False
    if all_valid:
        print("  ✅ All 27 fields present in every record")

    # Critical field checks — Course 4 (index 3)
    print("\nCritical field checks:")
    if len(results) >= 4:
        c4 = results[3]
        c4_name = c4.get("program_course_name", "MISSING")
        c4_intakes = c4.get("all_intakes_available", "MISSING")
        c4_portfolio = c4.get("mandatory_documents_required", "MISSING")

        name_ok = c4_name == "Automotive and Transport Design MA"
        intakes_ok = all(m in c4_intakes for m in ("March", "May", "July"))
        portfolio_ok = "portfolio" in c4_portfolio.lower()

        print(
            f"  {'✅' if name_ok else '❌'} Course 4 name: {c4_name}"
            f"  (should be 'Automotive and Transport Design MA')"
        )
        print(
            f"  {'✅' if intakes_ok else '❌'} Course 4 intakes: {c4_intakes}"
            f"  (should contain March/May/July)"
        )
        print(
            f"  {'✅' if portfolio_ok else '❌'} Course 4 portfolio: "
            f"{c4_portfolio[:60]}  (should contain 'portfolio')"
        )
    else:
        print("  ❌ Fewer than 4 results — Course 4 checks skipped")

    print("═══════════════════════════════════════════════\n")


# ──────────────────────────────────────────────────────────────
# Main orchestrator
# ──────────────────────────────────────────────────────────────

def run_pipeline() -> None:
    """
    Sequential pipeline: read URLs → extract → validate → write output.
    Per-record errors are caught and logged; the pipeline never stops
    early due to a single failed record.
    """
    print("╔══════════════════════════════════════════╗")
    print("║   Coventry University Course Scraper     ║")
    print("║   Pipeline Starting — 5 courses          ║")
    print("╚══════════════════════════════════════════╝\n")

    # Load URLs
    urls = load_urls(str(URLS_FILE))

    results: list[dict] = []
    total = len(urls)

    for i, url in enumerate(urls, start=1):
        print(f"[{i}/{total}] Processing: {url}")

        # Extract — catch hard failures without stopping the pipeline
        try:
            record = extract_course(url)
        except Exception as exc:
            print(f"[{i}/{total}] ❌ FATAL extraction error: {exc}")
            # Build a minimal NA record so the output always has 5 entries
            record = {k: "NA" for k in SCHEMA_KEYS}
            record["course_website_url"] = url
            record["university_name"] = "Coventry University"
            record["country"] = "United Kingdom"
            record["extraction_errors"] = [f"fatal: {exc}"]

        # Validate
        warnings = validate_record(record, i)
        for warning in warnings:
            print(f"  ⚠️  {warning}")

        results.append(record)

        name = record.get("program_course_name", "UNKNOWN")
        if warnings:
            print(f"[{i}/{total}] ⚠️  Done with warnings: {name}")
        else:
            print(f"[{i}/{total}] ✅ Done: {name}")

        # Polite delay between requests — skip after the last URL
        if i < total:
            print(f"  (waiting {REQUEST_DELAY_SECONDS}s...)")
            time.sleep(REQUEST_DELAY_SECONDS)

        print()

    # Write output — once, after all records collected
    print(f"Writing {COURSES_FILE}...")
    try:
        write_output(results, str(COURSES_FILE))
        print("✅ File written successfully.")
    except Exception as exc:
        print(f"❌ Failed to write output file: {exc}")
        raise

    print_final_report(results)


# ──────────────────────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    run_pipeline()
