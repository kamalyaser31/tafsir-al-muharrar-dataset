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
    has_inline_numbered_note,
    normalize_text,
    sha256_text,
    split_embedded_tafseer_text,
)
from json_generator import extract_verses_from_tafseer_article, split_references_by_text


PROJECT_DIR = Path(__file__).resolve().parent.parent
SOURCE_TAFSEER_DIR = PROJECT_DIR / "التفسير"
OUTPUT_JSON_DIR = PROJECT_DIR / "json"
UNIFIED_JSON_PATH = PROJECT_DIR / "tafseer_all.json"
VALIDATION_REPORT_PATH = PROJECT_DIR / "json_validation_report.txt"

REQUIRED_PAGE_FIELDS = ("verse_range",)
OPTIONAL_PAGE_FIELDS = ("vocabulary", "grammar", "balagha", "educational_benefits", "scientific_benefits", "references")
SOURCE_SECTIONS = REFERENCE_SECTION_KEYS


@dataclass
class ValidationResult:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    checked_surahs: int = 0
    checked_pages: int = 0

    @property
    def ok(self):
        return not self.errors


def extract_source_section_hashes(html_path):
    soup = BeautifulSoup(Path(html_path).read_text(encoding="utf-8"), "html.parser")
    card, _ = find_content_card(soup)

    hashes = {}
    for article in card.find_all("article"):
        header = article.find(SECTION_HEADINGS)
        if not header:
            continue
        section = classify_section(header.get_text(strip=True))
        if not section:
            continue
        text = article_body_text(article)
        if not text:
            continue
        if section == "benefits":
            header_text = article.find(SECTION_HEADINGS).get_text(strip=True)
            benefit_section = classify_benefit_section(header_text)
            hashes[benefit_section] = sha256_text(f"{header_text}\n{text}")
        elif section == "general_meaning":
            general_text, embedded_tafseer = split_embedded_tafseer_text(text)
            hashes["general_meaning"] = sha256_text(general_text)
            if embedded_tafseer:
                hashes["tafseer"] = sha256_text(embedded_tafseer)
        else:
            hashes[section] = sha256_text(text)
    return hashes


def extract_source_verses(html_path):
    soup = BeautifulSoup(Path(html_path).read_text(encoding="utf-8"), "html.parser")
    card, _ = find_content_card(soup)

    for article in card.find_all("article"):
        header = article.find(SECTION_HEADINGS)
        if not header:
            continue
        section = classify_section(header.get_text(strip=True))
        if section not in {"tafseer", "general_meaning"}:
            continue
        verses = extract_verses_from_tafseer_article(article)
        if verses:
            return verses
    return None


def extract_source_references(html_path):
    soup = BeautifulSoup(Path(html_path).read_text(encoding="utf-8"), "html.parser")
    card, _ = find_content_card(soup)

    references = empty_references()
    for article in card.find_all("article"):
        header = article.find(SECTION_HEADINGS)
        if not header:
            continue
        section = classify_section(header.get_text(strip=True))
        if not section:
            continue
        text = article_body_text(article)
        if not text:
            continue
        reference_section = classify_benefit_section(header.get_text(strip=True)) if section == "benefits" else section
        article_references = extract_reference_tips(article)
        if section == "general_meaning":
            general_text, embedded_tafseer = split_embedded_tafseer_text(text)
            general_references, tafseer_references = split_references_by_text(article_references, general_text, embedded_tafseer)
            references["general_meaning"].extend(general_references)
            references["tafseer"].extend(tafseer_references)
        else:
            references[reference_section].extend(article_references)
    return references


def extract_intro_references(html_path):
    soup = BeautifulSoup(Path(html_path).read_text(encoding="utf-8"), "html.parser")
    card, _ = find_content_card(soup)
    return extract_reference_tips(card)


def extract_intro_hash(html_path):
    soup = BeautifulSoup(Path(html_path).read_text(encoding="utf-8"), "html.parser")
    card, _ = find_content_card(soup)
    return sha256_text(extract_clean_text_without_references(card))


def surah_sort_key(path):
    match = re.match(r"^(\d+)\s", path.name)
    return int(match.group(1)) if match else 999


def verse_file_sort_key(path):
    if path.name == "المقدمة.html":
        return -1
    match = re.match(r"^(\d+)[-–—]", path.name)
    return int(match.group(1)) if match else 999


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


def source_page_range(path):
    if re.match(r"^\d+(?:[-–—]\d+)?$", path.stem):
        return path.stem
    return extract_verse_range_from_html(path)


def source_file_sort_key(path):
    if path.name == "المقدمة.html":
        return -1
    range_text = source_page_range(path)
    match = re.match(r"^(\d+)(?:[-–—]\d+)?$", range_text)
    return int(match.group(1)) if match else 999


def scan_source_surahs():
    surahs = {}
    for folder in sorted(SOURCE_TAFSEER_DIR.iterdir(), key=surah_sort_key):
        if not folder.is_dir():
            continue
        match = re.match(r"^(\d+)\s+(.*)$", folder.name)
        if not match:
            continue
        surah_num = int(match.group(1))
        files = sorted(folder.glob("*.html"), key=source_file_sort_key)
        page_files = [path for path in files if path.name != "المقدمة.html"]
        surahs[surah_num] = {
            "surah_num": surah_num,
            "surah_name": match.group(2),
            "path": folder,
            "files": files,
            "page_ranges": [source_page_range(path) for path in page_files],
            "range_to_file": {source_page_range(path): path for path in page_files},
            "has_intro": any(path.name == "المقدمة.html" for path in files),
        }
    return surahs


def parse_range(range_text):
    match = re.match(r"^(\d+)(?:[-–—](\d+))?$", range_text)
    if not match:
        return None
    start = int(match.group(1))
    end = int(match.group(2) or start)
    return start, end


def expected_verse_count(range_text):
    parsed = parse_range(range_text)
    if not parsed:
        return None
    start, end = parsed
    return end - start + 1 if end >= start else None


def split_json_verses(verses_text):
    text = (verses_text or "").strip()
    text = text.removeprefix("«").removesuffix("»").strip()
    if not text:
        return []
    return [part.strip() for part in text.split(" * ") if part.strip()]


def load_generated_surahs(surah_num=None):
    if surah_num is not None:
        path = OUTPUT_JSON_DIR / f"{surah_num}.json"
        if not path.exists():
            raise FileNotFoundError(f"Generated JSON file not found: {path}")
        return [json.loads(path.read_text(encoding="utf-8"))]

    if not UNIFIED_JSON_PATH.exists():
        raise FileNotFoundError(f"Unified JSON file not found: {UNIFIED_JSON_PATH}")
    data = json.loads(UNIFIED_JSON_PATH.read_text(encoding="utf-8"))
    return data.get("surahs", [])


def validate_surah(surah_data, source_index, result):
    surah_num = surah_data.get("surah_num")
    source = source_index.get(surah_num)
    result.checked_surahs += 1

    if not source:
        result.errors.append(f"Surah {surah_num}: no matching source folder found.")
        return

    if source["has_intro"] and not surah_data.get("introduction"):
        result.errors.append(f"Surah {surah_num}: source has introduction.html but JSON introduction is empty.")
    if source["has_intro"]:
        intro_path = source["path"] / "المقدمة.html"
        expected_intro_hash = extract_intro_hash(intro_path)
        expected_intro_references = extract_intro_references(intro_path)
        if "introduction_html" in surah_data:
            result.errors.append(f"Surah {surah_num}: raw HTML field 'introduction_html' must not be stored in JSON.")
        if "introduction_references" not in surah_data:
            result.errors.append(f"Surah {surah_num}: missing introduction_references field.")
        elif surah_data.get("introduction_references") != expected_intro_references:
            result.errors.append(f"Surah {surah_num}: introduction_references do not match source reference notes.")
        if has_inline_numbered_note(surah_data.get("introduction")):
            result.errors.append(f"Surah {surah_num}: introduction still contains inline numbered reference notes.")
        if not surah_data.get("introduction_sha256"):
            result.errors.append(f"Surah {surah_num}: missing introduction_sha256 field.")
        elif surah_data.get("introduction_sha256") != expected_intro_hash:
            result.errors.append(f"Surah {surah_num}: introduction text hash does not match source visible text.")
        elif sha256_text(surah_data.get("introduction")) != surah_data.get("introduction_sha256"):
            result.errors.append(f"Surah {surah_num}: introduction text does not match introduction_sha256.")

    pages = surah_data.get("tafseer_pages") or []
    json_ranges = [page.get("verse_range") for page in pages]
    if json_ranges != source["page_ranges"]:
        result.errors.append(
            f"Surah {surah_num}: page ranges mismatch. Expected {len(source['page_ranges'])} pages, got {len(json_ranges)} pages."
        )
        missing = [item for item in source["page_ranges"] if item not in json_ranges]
        extra = [item for item in json_ranges if item not in source["page_ranges"]]
        if missing:
            result.errors.append(f"Surah {surah_num}: missing page ranges: {', '.join(missing[:20])}")
        if extra:
            result.errors.append(f"Surah {surah_num}: extra page ranges: {', '.join(extra[:20])}")

    for page in pages:
        validate_page(surah_num, page, source, result)


def validate_page(surah_num, page, source, result):
    result.checked_pages += 1
    verse_range = page.get("verse_range") or "<missing-range>"
    prefix = f"Surah {surah_num}, page {verse_range}"

    for field_name in REQUIRED_PAGE_FIELDS:
        if not page.get(field_name):
            result.errors.append(f"{prefix}: required field '{field_name}' is empty.")

    html_path = source_html_path_for_page(page, source)
    expected_hashes = {}
    expected_verses = None
    if html_path.exists():
        try:
            expected_hashes = extract_source_section_hashes(html_path)
            expected_verses = extract_source_verses(html_path)
        except Exception as exc:
            result.errors.append(f"{prefix}: failed to inspect source HTML required fields: {exc}")

    for field_name in ("general_meaning", "tafseer"):
        if field_name in expected_hashes and not page.get(field_name):
            result.errors.append(f"{prefix}: required field '{field_name}' is empty.")

    if expected_verses and not page.get("verses"):
        result.errors.append(f"{prefix}: required field 'verses' is empty.")

    for field_name in OPTIONAL_PAGE_FIELDS:
        if field_name not in page:
            result.errors.append(f"{prefix}: optional schema field '{field_name}' is missing; expected null when absent.")

    if "benefits" in page:
        result.errors.append(f"{prefix}: old combined field 'benefits' must be split into educational_benefits and scientific_benefits.")
    if "REFRENCES" in page:
        result.errors.append(f"{prefix}: misspelled field 'REFRENCES' must be renamed to 'references'.")

    for text_field in ("vocabulary", "general_meaning", "tafseer", "grammar", "balagha", "educational_benefits", "scientific_benefits"):
        if has_inline_numbered_note(page.get(text_field)):
            result.errors.append(f"{prefix}: field '{text_field}' still contains inline numbered reference notes.")

    validate_source_html_hashes(prefix, page, source, result)

    expected_count = expected_verse_count(verse_range)
    actual_verses = split_json_verses(page.get("verses"))
    if expected_count is None:
        result.errors.append(f"{prefix}: invalid verse_range format.")
    elif len(actual_verses) != expected_count:
        result.warnings.append(
            f"{prefix}: verse segment count differs from range count. "
            f"Expected {expected_count}, got {len(actual_verses)}. "
            "This can be normal when the source groups multiple verses in one HTML span or splits one verse across spans."
        )

    for verse in actual_verses:
        if re.search(r"\(\d+\)", verse):
            result.errors.append(f"{prefix}: verse text still contains a verse number marker: {verse[:80]}")
        if len(normalize_text(verse)) < 2:
            result.errors.append(f"{prefix}: suspiciously short verse segment: {verse!r}")


def validate_source_html_hashes(prefix, page, source, result):
    verse_range = page.get("verse_range")
    html_path = source_html_path_for_page(page, source)
    if not html_path.exists():
        result.errors.append(f"{prefix}: source HTML file not found for hash validation: {html_path}")
        return

    section_hashes = page.get("section_sha256")
    if "section_html" in page:
        result.errors.append(f"{prefix}: raw HTML field 'section_html' must not be stored in JSON.")
    if not isinstance(section_hashes, dict):
        result.errors.append(f"{prefix}: missing section_sha256 dictionary.")
        return

    try:
        expected_hashes = extract_source_section_hashes(html_path)
        expected_references = extract_source_references(html_path)
    except Exception as exc:
        result.errors.append(f"{prefix}: failed to extract source section hashes: {exc}")
        return

    actual_references = page.get("references")
    if not isinstance(actual_references, dict):
        result.errors.append(f"{prefix}: field 'references' must be an object keyed by section name.")
    elif set(actual_references) != set(REFERENCE_SECTION_KEYS):
        result.errors.append(f"{prefix}: references keys do not match expected section keys.")
    elif actual_references != expected_references:
        result.errors.append(f"{prefix}: extracted references do not match source reference notes.")

    for section in SOURCE_SECTIONS:
        expected = expected_hashes.get(section)
        actual = section_hashes.get(section)
        if expected is None:
            if section in section_hashes:
                result.errors.append(f"{prefix}: JSON contains hash for absent source section '{section}'.")
            continue

        if section not in section_hashes:
            result.errors.append(f"{prefix}: missing source text hash for section '{section}'.")
            continue

        if actual != expected:
            result.errors.append(f"{prefix}: source visible text hash mismatch for section '{section}'.")

        if sha256_text(page.get(section)) != actual:
            result.errors.append(f"{prefix}: stored text does not match stored hash for section '{section}'.")


def source_html_path_for_page(page, source):
    verse_range = page.get("verse_range")
    return source.get("range_to_file", {}).get(verse_range) or (source["path"] / f"{verse_range}.html")


def write_validation_report(result):
    lines = [
        "========================================================================",
        "                         JSON VALIDATION REPORT                         ",
        "========================================================================",
        "",
        f"Checked surahs: {result.checked_surahs}",
        f"Checked tafseer pages: {result.checked_pages}",
        f"Errors: {len(result.errors)}",
        f"Warnings: {len(result.warnings)}",
        "",
        "------------------------------------------------------------------------",
        "1. Errors",
        "------------------------------------------------------------------------",
    ]

    lines.extend((f"[ERROR] {item}" for item in result.errors) if result.errors else ["No validation errors detected."])
    lines.extend(["", "------------------------------------------------------------------------", "2. Warnings", "------------------------------------------------------------------------"])
    lines.extend((f"[WARNING] {item}" for item in result.warnings) if result.warnings else ["No validation warnings detected."])
    VALIDATION_REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_parser():
    parser = argparse.ArgumentParser(description="Validate generated tafseer JSON against local HTML inventory and schema rules.")
    parser.add_argument("--surah", type=int, help="Validate a single distributed surah JSON file, e.g. --surah 2.")
    parser.add_argument("--unified", action="store_true", help="Validate tafseer_all.json instead of a single surah file.")
    return parser


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    args = build_parser().parse_args(argv)
    if not args.unified and args.surah is None:
        args.unified = True

    result = ValidationResult()
    source_index = scan_source_surahs()
    try:
        surahs = load_generated_surahs(None if args.unified else args.surah)
    except Exception as exc:
        result.errors.append(str(exc))
        write_validation_report(result)
        print(f"Validation completed. Errors: {len(result.errors)}, Warnings: {len(result.warnings)}")
        print(f"Report: {VALIDATION_REPORT_PATH}")
        return 1

    for surah_data in surahs:
        validate_surah(surah_data, source_index, result)

    write_validation_report(result)
    print(f"Validation completed. Errors: {len(result.errors)}, Warnings: {len(result.warnings)}")
    print(f"Report: {VALIDATION_REPORT_PATH}")
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
