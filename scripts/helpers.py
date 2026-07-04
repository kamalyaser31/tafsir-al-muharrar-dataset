import hashlib
import re

from bs4 import BeautifulSoup, Comment


SECTION_HEADINGS = ("h1", "h2", "h3", "h4", "h5", "h6", "b", "strong")
REFERENCE_SECTION_KEYS = (
    "vocabulary",
    "general_meaning",
    "tafseer",
    "grammar",
    "balagha",
    "educational_benefits",
    "scientific_benefits",
)

REFERENCE_NOTE_STARTERS = (
    "يُنظر",
    "ينظر",
    "أخرجه",
    "رواه",
    "قال",
    "وفي رواية",
    "صححه",
    "صحَّحه",
    "حسنه",
    "حسَّنه",
)
REFERENCE_NOTE_STARTER_PATTERN = "|".join(re.escape(item) for item in REFERENCE_NOTE_STARTERS)
REFERENCE_MARKER_PATTERN = re.compile(r"\[\s*([\d\s]+)\s*\]")
INVISIBLE_TEXT_CHARS = str.maketrans({
    "\u00a0": " ",
    "\u2007": " ",
    "\u202f": " ",
    "\u200e": "",
    "\u200f": "",
    "\ufeff": "",
})


def normalize_text(text):
    text = re.sub(r"[\u0617-\u061a\u064b-\u0652]", "", text or "")
    text = re.sub(r"[إأآٱ]", "ا", text)
    text = text.replace("ى", "ي")
    text = text.replace("ـ", "")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def has_inline_numbered_note(text):
    return re.search(rf"(?:^|\n)\s*\[\d+\]\s*(?:{REFERENCE_NOTE_STARTER_PATTERN})", text or "") is not None


def bare_reference_note_match(text):
    return re.match(rf"\s*(\[\d+\])\s*(?:{REFERENCE_NOTE_STARTER_PATTERN})", text or "")


def clean_arabic_text(text):
    text = (text or "").translate(INVISIBLE_TEXT_CHARS)
    return re.sub(r"[ \t]+", " ", text)


def strip_tashkeel(text):
    return re.sub(r"[\u0617-\u061a\u064b-\u0652]", "", text)


def normalize_arabic_heading(text):
    text = strip_tashkeel(text)
    text = re.sub(r"[إأآٱ]", "ا", text)
    return text.replace("ى", "ي")


def visible_text_from_html(html):
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text("\n", strip=True)
    lines = [clean_arabic_text(line).strip() for line in text.splitlines() if line.strip()]
    return "\n".join(lines).strip()


def remove_unwanted_nodes(soup):
    for tag in soup.find_all(["style", "script"]):
        tag.decompose()

    for comment in soup.find_all(string=lambda value: isinstance(value, Comment)):
        comment.extract()

    for tag in list(soup.find_all(True)):
        if tag.parent is None:
            continue
        classes = tag.get("class", [])
        class_text = " ".join(classes if isinstance(classes, list) else [classes]).lower()
        if any(marker in class_text for marker in ("nav", "navbar", "collapse", "menu", "tabs")):
            tag.decompose()

    for link in list(soup.find_all("a")):
        if link.parent is None:
            continue
        link_text = link.get_text(strip=True)
        if "التالي" in link_text or "السابق" in link_text:
            link.decompose()


def is_reference_tip(tag):
    return "tip" in tag.get("class", [])


def normalize_reference_marker_text(text):
    match = REFERENCE_MARKER_PATTERN.search(clean_arabic_text(text))
    if not match:
        return ""
    digits = re.sub(r"\s+", "", match.group(1))
    return f"[{digits}]" if digits else ""


def reference_tip_internal_marker(tip):
    return normalize_reference_marker_text(tip.get_text("", strip=True))


def previous_reference_marker(tip):
    for sibling in tip.previous_siblings:
        text = sibling.get_text(" ", strip=True) if hasattr(sibling, "get_text") else str(sibling)
        text = clean_arabic_text(text).strip()
        if not text:
            continue
        match = re.search(r"\[\s*([\d\s]+)\s*\]\s*$", text)
        if match:
            return normalize_reference_marker_text(match.group(0))
        break
    return ""


def reference_tip_marker(tip):
    return reference_tip_internal_marker(tip) or previous_reference_marker(tip)


def reference_tip_text(tip, marker):
    text = visible_text_from_html(str(tip))
    text = REFERENCE_MARKER_PATTERN.sub("", text, count=1).strip()
    return f"{marker} {text}".strip() if marker else text


def reference_text_marker(text):
    return normalize_reference_marker_text(text or "")


def has_reference_tip_ancestor(node):
    parent = getattr(node, "parent", None)
    while parent is not None:
        if getattr(parent, "name", None) and is_reference_tip(parent):
            return True
        parent = getattr(parent, "parent", None)
    return False


def bare_reference_text(text):
    lines = [clean_arabic_text(line).strip() for line in (text or "").splitlines() if line.strip()]
    return "\n".join(lines).strip()


def next_synthetic_marker(used_markers):
    numbers = []
    for marker in used_markers:
        match = re.match(r"\[(\d+)\]", marker)
        if match:
            numbers.append(int(match.group(1)))
    number = max(numbers, default=0) + 1
    marker = f"[{number}]"
    used_markers.add(marker)
    return marker


def collect_reference_markers(element):
    markers = set()
    for tip in element.find_all(is_reference_tip):
        marker = reference_tip_marker(tip)
        if marker:
            markers.add(marker)
    for node in element.find_all(string=True):
        if has_reference_tip_ancestor(node):
            continue
        marker = reference_text_marker(str(node))
        if marker:
            markers.add(marker)
    return markers


def is_embedded_tafseer_heading(text):
    normalized = normalize_arabic_heading(text)
    normalized = re.sub(r"[\s:：]+", " ", normalized).strip()
    return normalized in {"تفسير الايات", "تفسير الايه", "تفسير الاية", "تفسير الايتين"}


def split_embedded_tafseer_text(text):
    lines = (text or "").splitlines()
    for index, line in enumerate(lines):
        if is_embedded_tafseer_heading(line):
            general_text = "\n".join(lines[:index]).strip()
            tafseer_text = "\n".join(lines[index + 1:]).strip()
            if general_text and tafseer_text:
                return general_text, tafseer_text
    return text, None


def remove_reference_tips(element):
    for tip in list(element.find_all(is_reference_tip)):
        tip.decompose()


def replace_reference_tips_with_markers(element):
    used_markers = collect_reference_markers(element)
    replacements = []
    for tip in list(element.find_all(is_reference_tip)):
        internal_marker = reference_tip_internal_marker(tip)
        marker = internal_marker or previous_reference_marker(tip)
        if internal_marker:
            replacements.append((tip, f" {marker} "))
        elif marker:
            replacements.append((tip, None))
        else:
            replacements.append((tip, f" {next_synthetic_marker(used_markers)} "))

    for tip, replacement in replacements:
        if replacement is None:
            tip.decompose()
        else:
            tip.replace_with(replacement)


def replace_bare_reference_notes_with_markers(element):
    for node in list(element.find_all(string=True)):
        if has_reference_tip_ancestor(node):
            continue
        match = bare_reference_note_match(str(node))
        if match:
            node.replace_with(f" {match.group(1)} ")


def extract_reference_tips(article):
    references = []
    used_markers = collect_reference_markers(article)
    for node in article.descendants:
        if getattr(node, "name", None) and is_reference_tip(node):
            marker = reference_tip_marker(node) or next_synthetic_marker(used_markers)
            text = reference_tip_text(node, marker)
            if text:
                references.append(text)
            continue
        if getattr(node, "name", None) is None and not has_reference_tip_ancestor(node):
            text = bare_reference_text(str(node))
            if bare_reference_note_match(text):
                references.append(text)
    return references


def extract_clean_text(element):
    copied = BeautifulSoup(str(element), "html.parser")
    remove_unwanted_nodes(copied)
    return visible_text_from_html(str(copied))


def extract_clean_text_without_references(element):
    copied = BeautifulSoup(str(element), "html.parser")
    remove_unwanted_nodes(copied)
    replace_reference_tips_with_markers(copied)
    replace_bare_reference_notes_with_markers(copied)
    return visible_text_from_html(str(copied))


def find_content_card(soup):
    card = soup.find("div", class_="card-body amiri") or soup.find(class_="amiri_custom_content")
    if card:
        return card, False

    body = soup.find("body")
    if body:
        return body, True

    raise ValueError("Could not find content card or body in HTML.")


def classify_section(header_text):
    normalized = normalize_arabic_heading(header_text)

    if any(token in normalized for token in ("المعنى الاجمالي", "المعني الاجمالي", "معنى اجمالي", "معني اجمالي")):
        return "general_meaning"
    if any(token in normalized for token in ("غريب الكلمات", "المفردات", "غريب")):
        return "vocabulary"
    if "تفسير الا" in normalized or normalized == "التفسير":
        return "tafseer"
    if "اعراب" in normalized:
        return "grammar"
    if "بلاغة الا" in normalized or normalized == "البلاغة":
        return "balagha"
    if any(token in normalized for token in ("الفوائد", "اللطائف", "فوائد")):
        return "benefits"
    return None


def classify_benefit_section(header_text):
    normalized = normalize_arabic_heading(header_text)
    if "تربوي" in normalized:
        return "educational_benefits"
    if "علمي" in normalized or "لطائف" in normalized:
        return "scientific_benefits"
    return "scientific_benefits"


def article_body_html(article):
    article_copy = BeautifulSoup(str(article), "html.parser")
    copied_article = article_copy.find("article")
    if copied_article:
        header = copied_article.find(SECTION_HEADINGS)
        if header:
            header.decompose()
        replace_reference_tips_with_markers(copied_article)
        replace_bare_reference_notes_with_markers(copied_article)
    return str(article_copy)


def article_body_text(article):
    return visible_text_from_html(article_body_html(article))


def sha256_text(text):
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def empty_references():
    return {key: [] for key in REFERENCE_SECTION_KEYS}
