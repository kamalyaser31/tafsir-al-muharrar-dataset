import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

from bs4 import BeautifulSoup

from helpers import (
    REFERENCE_SECTION_KEYS,
    SECTION_HEADINGS,
    article_body_text,
    classify_benefit_section,
    classify_section,
    empty_references,
    extract_clean_text_without_references,
    extract_reference_tips,
    find_content_card,
    normalize_arabic_heading,
    reference_text_marker,
    sha256_text,
    split_embedded_tafseer_text,
)

try:
    from progress.bar import IncrementalBar
except ImportError:
    class IncrementalBar:
        def __init__(self, *args, **kwargs):
            pass

        def next(self):
            pass

        def finish(self):
            pass

PROJECT_DIR = Path(__file__).resolve().parent.parent
SOURCE_TAFSEER_DIR = PROJECT_DIR / "التفسير"
OUTPUT_JSON_DIR = PROJECT_DIR / "json"
REPORT_PATH = PROJECT_DIR / "json_generation_report.txt"
UNIFIED_JSON_PATH = PROJECT_DIR / "tafseer_all.json"

@dataclass
class GenerationReport:
    success_count: int = 0
    fail_count: int = 0
    errors: list[str] = field(default_factory=list)

def add_unique_verse(verses, seen, text):
    if not text or text in seen:
        return
    normalized_text = normalize_arabic_heading(text)
    normalized_text = re.sub(r"[\sـ]+", "", normalized_text)
    if normalized_text in seen:
        return
    if any(normalized_text in re.sub(r"[\sـ]+", "", normalize_arabic_heading(verse)) for verse in verses):
        return

    for existing in list(verses):
        normalized_existing = re.sub(r"[\sـ]+", "", normalize_arabic_heading(existing))
        if normalized_existing in normalized_text:
            verses.remove(existing)
            seen.discard(normalized_existing)

    seen.add(normalized_text)
    verses.append(text)


def is_main_unnumbered_verse_span(span):
    for sibling in span.next_siblings:
        sibling_text = sibling.get_text(strip=True) if hasattr(sibling, "get_text") else str(sibling).strip()
        if not sibling_text or sibling_text in {".", "،", ":"}:
            continue
        if getattr(sibling, "name", None) == "br":
            continue
        classes = sibling.get("class", []) if hasattr(sibling, "get") else []
        if "title-1" in classes or (getattr(sibling, "name", None) == "span" and has_verse_class(sibling)):
            return True
        return sibling_text.startswith(("أي:", "مُناسبة", "مناسبة", "القِراءات", "القراءات"))
    return False


def has_verse_class(tag):
    classes = tag.get("class", [])
    return "aaya" in classes or "aya" in classes


def verse_spans(article):
    return article.find_all("span", class_=lambda value: value in {"aaya", "aya"})


def is_nested_aaya_span(span):
    parent = span.parent
    while parent is not None and getattr(parent, "name", None) != "article":
        if getattr(parent, "name", None) == "span" and has_verse_class(parent):
            return True
        parent = parent.parent
    return False


def has_adjacent_verse_number(span):
    return adjacent_verse_number(span) is not None


def adjacent_verse_number(span):
    for sibling in span.next_siblings:
        sibling_text = sibling.get_text(strip=True) if hasattr(sibling, "get_text") else str(sibling).strip()
        if not sibling_text:
            continue
        match = re.match(r"^\s*\((\d+)\)", sibling_text)
        return int(match.group(1)) if match else None
    return None


def verse_number_from_span(span):
    text = span.get_text(" ", strip=True)
    match = re.search(r"\((\d+)\)", text)
    return int(match.group(1)) if match else adjacent_verse_number(span)


def next_numbered_span_number(spans, current_index):
    for span in spans[current_index + 1:]:
        number = verse_number_from_span(span)
        if number is not None:
            return number
    return None


def format_verses(verses):
    return f"« {' * '.join(verses)} »" if verses else None


def add_numbered_verse(verses, seen_numbers, span, number):
    if number in seen_numbers:
        return
    text = span.get_text(" ", strip=True)
    verses.append(re.sub(r"\s*\(\d+\)\s*", "", text).strip())
    seen_numbers.add(number)


def extract_numbered_or_gap_verses(article):
    verses, seen, seen_numbers = [], set(), set()
    spans = [span for span in verse_spans(article) if not is_nested_aaya_span(span)]
    previous_number = None

    for index, span in enumerate(spans):
        number = verse_number_from_span(span)
        if number is not None:
            add_numbered_verse(verses, seen_numbers, span, number)
            previous_number = number
            continue

        next_number = next_numbered_span_number(spans, index)
        if previous_number is not None and next_number is not None and next_number > previous_number + 1 and is_main_unnumbered_verse_span(span):
            add_unique_verse(verses, seen, span.get_text(" ", strip=True))

    return verses


def extract_unnumbered_main_verses(article):
    verses, seen = [], set()
    for span in verse_spans(article):
        if is_nested_aaya_span(span):
            continue
        if is_main_unnumbered_verse_span(span):
            add_unique_verse(verses, seen, span.get_text(" ", strip=True))
    return verses


def extract_verses_from_tafseer_article(article):
    verses = extract_numbered_or_gap_verses(article)
    if not verses:
        verses = extract_unnumbered_main_verses(article)
    return format_verses(verses)


def empty_page_data():
    return {
        "verses": None,
        "vocabulary": None,
        "general_meaning": None,
        "tafseer": None,
        "grammar": None,
        "balagha": None,
        "educational_benefits": None,
        "scientific_benefits": None,
        "references": empty_references(),
        "section_sha256": {},
    }


def parse_intro_card(card):
    introduction = extract_clean_text_without_references(card)
    return {
        "introduction": introduction,
        "introduction_references": extract_reference_tips(card),
        "introduction_sha256": sha256_text(introduction),
        "tafseer_pages": [],
    }


def split_references_by_text(references, primary_text, secondary_text):
    primary_references, secondary_references = [], []
    for reference in references:
        marker = reference_text_marker(reference)
        if marker and secondary_text and marker in secondary_text:
            secondary_references.append(reference)
        else:
            primary_references.append(reference)
    return primary_references, secondary_references


def apply_article_section(page_data, article):
    header = article.find(SECTION_HEADINGS)
    if not header:
        return

    header_text = header.get_text(strip=True)
    section = classify_section(header_text)
    if not section:
        return

    reference_section = classify_benefit_section(header_text) if section == "benefits" else section
    references = extract_reference_tips(article)

    text = article_body_text(article)
    if not text:
        return

    if section == "tafseer":
        page_data["references"][reference_section].extend(references)
        page_data["verses"] = extract_verses_from_tafseer_article(article) or page_data["verses"]
        page_data["tafseer"] = text
        page_data["section_sha256"][section] = sha256_text(text)
    elif section == "benefits":
        page_data["references"][reference_section].extend(references)
        benefit_text = f"{header_text}\n{text}"
        page_data[reference_section] = benefit_text
        page_data["section_sha256"][reference_section] = sha256_text(benefit_text)
    elif section == "general_meaning":
        general_text, embedded_tafseer = split_embedded_tafseer_text(text)
        general_references, tafseer_references = split_references_by_text(references, general_text, embedded_tafseer)

        if not page_data["verses"]:
            page_data["verses"] = extract_verses_from_tafseer_article(article) or page_data["verses"]
        page_data["general_meaning"] = general_text
        page_data["references"]["general_meaning"].extend(general_references)
        page_data["section_sha256"]["general_meaning"] = sha256_text(general_text)

        if embedded_tafseer:
            page_data["tafseer"] = embedded_tafseer
            page_data["references"]["tafseer"].extend(tafseer_references)
            page_data["section_sha256"]["tafseer"] = sha256_text(embedded_tafseer)
    else:
        page_data["references"][reference_section].extend(references)
        page_data[section] = text
        page_data["section_sha256"][section] = sha256_text(text)


def parse_tafseer_html(html_path, is_intro=False):
    html_content = Path(html_path).read_text(encoding="utf-8")
    soup = BeautifulSoup(html_content, "html.parser")
    card, fallback_used = find_content_card(soup)

    if is_intro:
        return parse_intro_card(card)

    page_data = empty_page_data()

    for article in card.find_all("article"):
        apply_article_section(page_data, article)

    return {"page_data": page_data, "fallback_used": fallback_used}


def surah_sort_key(folder_name):
    match = re.match(r"^(\d+)\s", folder_name)
    return int(match.group(1)) if match else 999


def verse_file_sort_key(filename):
    if filename == "المقدمة.html":
        return -1
    match = re.match(r"^(\d+)[-–—]", filename)
    return int(match.group(1)) if match else 999


def parse_verse_range(range_text):
    return re.match(r"^\d+(?:[-–—]\d+)?$", range_text or "") is not None


def extract_verse_range_from_html(html_path):
    html = Path(html_path).read_text(encoding="utf-8")
    patterns = (
        r"(?:الآيات|لآيات|الآية|الآيتان|الآيتين)\s*\(?\s*(\d+)\s*[-–—]\s*(\d+)\s*\)?",
        r"(?:الآيات|لآيات|الآية|الآيتان|الآيتين)\s*\(?\s*(\d+)\s*\)?",
    )
    for pattern in patterns:
        match = re.search(pattern, html)
        if match:
            start = match.group(1)
            end = match.group(2) if len(match.groups()) > 1 and match.group(2) else start
            return f"{start}-{end}"
    return Path(html_path).stem


def file_sort_key(path):
    if path.name == "المقدمة.html":
        return -1
    range_text = path.stem if re.match(r"^\d+[-–—]", path.stem) else extract_verse_range_from_html(path)
    match = re.match(r"^(\d+)[-–—]", range_text)
    return int(match.group(1)) if match else 999


def scan_source_surahs():
    if not SOURCE_TAFSEER_DIR.exists():
        return []

    surahs = []
    for folder in sorted(SOURCE_TAFSEER_DIR.iterdir(), key=lambda item: surah_sort_key(item.name)):
        if not folder.is_dir() or not re.match(r"^\d+\s", folder.name):
            continue

        match = re.match(r"^(\d+)\s+(.*)$", folder.name)
        surah_num = int(match.group(1)) if match else 999
        surah_name = match.group(2) if match else folder.name
        files = [path.name for path in sorted(folder.glob("*.html"), key=file_sort_key)]

        surahs.append({
            "folder_name": folder.name,
            "surah_num": surah_num,
            "surah_name": surah_name,
            "path": str(folder),
            "files": files,
        })

    return surahs


def filter_surahs(surahs, surah_num):
    return surahs if surah_num is None else [surah for surah in surahs if surah["surah_num"] == surah_num]


def new_surah_data(surah):
    return {
        "surah_num": surah["surah_num"],
        "surah_name": surah["surah_name"],
        "introduction": None,
        "introduction_references": [],
        "introduction_sha256": None,
        "tafseer_pages": [],
    }


def process_html_file(surah, filename, surah_data, report):
    html_path = Path(surah["path"]) / filename
    is_intro = filename == "المقدمة.html"

    try:
        result = parse_tafseer_html(html_path, is_intro)
    except Exception as exc:
        report.fail_count += 1
        report.errors.append(f"Error processing Surah {surah['surah_num']} ({surah['surah_name']}), File '{filename}': {exc}")
        return

    if is_intro:
        surah_data["introduction"] = result["introduction"]
        surah_data["introduction_references"] = result["introduction_references"]
        surah_data["introduction_sha256"] = result["introduction_sha256"]
    else:
        page = result["page_data"]
        stem = Path(filename).stem
        page["verse_range"] = stem if parse_verse_range(stem) else extract_verse_range_from_html(html_path)
        surah_data["tafseer_pages"].append(page)

    report.success_count += 1


def generate_json(surahs, show_progress=True):
    OUTPUT_JSON_DIR.mkdir(exist_ok=True)
    report = GenerationReport()
    all_surahs_data = []
    total_files = sum(len(surah["files"]) for surah in surahs)
    bar = IncrementalBar("Generating", max=total_files, suffix="%(percent)d%% [Time: %(elapsed)ds / ETA: %(eta)ds]") if show_progress else None

    for surah in surahs:
        surah_data = new_surah_data(surah)
        for filename in surah["files"]:
            process_html_file(surah, filename, surah_data, report)
            if bar:
                bar.next()

        write_json(OUTPUT_JSON_DIR / f"{surah['surah_num']}.json", surah_data, report, f"Failed to write Surah {surah['surah_num']} JSON")
        all_surahs_data.append(surah_data)

    if bar:
        bar.finish()

    write_json(UNIFIED_JSON_PATH, {"surahs": all_surahs_data}, report, "Failed to write unified JSON file")
    write_generation_report(report)
    return report, all_surahs_data


def write_json(path, data, report, error_prefix):
    try:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as exc:
        report.errors.append(f"{error_prefix}: {exc}")


def write_generation_report(report):
    total_issues = len(report.errors)
    lines = [
        "========================================================================",
        "                         JSON GENERATION REPORT                         ",
        "========================================================================",
        "",
        f"Total generation issues detected: {total_issues}",
        f" - Programming Exceptions: {len(report.errors)}",
        "",
    ]

    append_report_section(lines, "1. Programming Exceptions / Parsing Failures", report.errors, "[ERROR]", "No exceptions occurred. All files parsed successfully.")

    REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def append_report_section(lines, title, items, prefix, empty_message):
    lines.extend(["------------------------------------------------------------------------", title, "------------------------------------------------------------------------"])
    if items:
        lines.extend(f"{prefix} {item}" for item in items)
    else:
        lines.append(empty_message)
    lines.append("")


def build_parser():
    parser = argparse.ArgumentParser(description="Generate structured JSON from local tafseer HTML files.")
    parser.add_argument("--surah", type=int, default=112, help="Surah number to process. Defaults to 112 for safe test runs.")
    parser.add_argument("--all", action="store_true", help="Process all available surahs.")
    parser.add_argument("--no-progress", action="store_true", help="Disable the progress bar.")
    return parser


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    args = build_parser().parse_args(argv)
    requested_surah = None if args.all else args.surah

    print("Scanning Surah folders in 'التفسير' directory...")
    surahs = filter_surahs(scan_source_surahs(), requested_surah)
    total_files = sum(len(surah["files"]) for surah in surahs)

    if total_files == 0:
        scope = "all surahs" if requested_surah is None else f"Surah {requested_surah}"
        print(f"No HTML files found to process for {scope}.")
        return 1

    scope = "all available Surahs" if requested_surah is None else f"Surah {requested_surah}"
    print(f"Found {len(surahs)} Surahs containing {total_files} HTML files for {scope}. Starting JSON generation...")

    report, _ = generate_json(surahs, show_progress=not args.no_progress)

    print("\n--- JSON GENERATION COMPLETED ---")
    print(f"Successfully processed: {report.success_count} HTML files")
    print(f"Failed: {report.fail_count} files")
    print("Individual Surah files saved inside the 'json/' directory.")
    print("Unified JSON file saved at 'tafseer_all.json'.")
    print(f"Please check the comprehensive logs and verification results at: {REPORT_PATH}")
    return 0 if report.fail_count == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
