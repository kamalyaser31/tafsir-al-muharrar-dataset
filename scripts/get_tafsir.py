#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
أداة سريعة لاستخلاص وعرض أقسام التفسير المحرر لسور القرآن الكريم وآياته من ملفات JSON المحلية.
"""

import argparse
import json
import sys
from pathlib import Path


def parse_verse_range(range_str):
    """
    يحول سلسلة نطاق الآيات (مثل '1-4' أو '5') إلى زوج (البداية، النهاية).
    """
    range_str = str(range_str).strip()
    if "-" in range_str:
        parts = range_str.split("-")
        try:
            return int(parts[0]), int(parts[1])
        except ValueError:
            pass
    try:
        val = int(range_str)
        return val, val
    except ValueError:
        return None


def load_surah_data(surah_num, base_dir):
    """
    يفتح ملف JSON الخاص بالسورة ويعيد محتواه كقاموس.
    """
    json_path = base_dir / "json" / f"{surah_num}.json"
    if not json_path.exists():
        sys.exit(f"خطأ: ملف السورة رقم {surah_num} غير موجود في مجلد json.")
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        sys.exit(f"خطأ أثناء قراءة ملف JSON للسورة {surah_num}: {str(e)}")


def calculate_total_verses(tafseer_pages):
    """
    يحسب العدد الإجمالي للآيات في السورة بالاعتماد على نطاقات الصفحات المتوفرة.
    """
    total_verses = 1
    for page in tafseer_pages:
        verse_range = parse_verse_range(page.get("verse_range", ""))
        if verse_range:
            total_verses = max(total_verses, verse_range[1])
    return total_verses


def display_introduction(surah_data, show_refs):
    """
    يعرض مقدمة السورة ومراجعها إن طلبت.
    """
    intro_text = surah_data.get("introduction")
    if not intro_text:
        return
    print("--- [مقدمة السورة] ---")
    print(intro_text.strip())
    print()
    if show_refs:
        intro_refs = surah_data.get("introduction_references", [])
        if intro_refs:
            print("[حواشي مقدمة السورة]")
            for ref in intro_refs:
                print(f"  {ref.strip()}")
            print()
    print("-" * 50 + "\n")


def display_section(title, content, ref_key, page_refs, show_refs):
    """
    يطبع القسم النصي ومراجعه التابعة له أسفل النص مباشرة.
    """
    if not content:
        return
    print(f"\n* {title}:")
    print(content.strip())
    if show_refs and page_refs and ref_key in page_refs:
        section_refs = page_refs[ref_key]
        if section_refs:
            print(f"\n  [حواشي {title}]")
            for ref in section_refs:
                print(f"    {ref.strip()}")


def display_tafseer_pages(tafseer_pages, from_verse, to_verse, show_flags, show_refs):
    """
    يمر على صفحات التفسير ويعرض الصفحات المتقاطعة مع النطاق المطلوب.
    """
    pages_displayed = 0
    for page in tafseer_pages:
        verse_range = parse_verse_range(page.get("verse_range", ""))
        if not verse_range:
            continue
        page_start, page_end = verse_range
        # التحقق من تداخل النطاق: max(A, X) <= min(B, Y)
        if max(page_start, from_verse) <= min(page_end, to_verse):
            pages_displayed += 1
            print(f"=== [الآيات: {page.get('verse_range')}] ===")
            page_refs = page.get("references", {})

            # عرض الأقسام التي تم تفعيل أعلامها
            if show_flags["verses"]:
                display_section("الآيات الكريمة", page.get("verses"), None, page_refs, show_refs)
            if show_flags["vocab"]:
                display_section("غريب الكلمات", page.get("vocabulary"), "vocabulary", page_refs, show_refs)
            if show_flags["meaning"]:
                display_section("المعنى الإجمالي", page.get("general_meaning"), "general_meaning", page_refs, show_refs)
            if show_flags["detail"]:
                display_section("التفسير التفصيلي", page.get("tafseer"), "tafseer", page_refs, show_refs)
            if show_flags["grammar"]:
                display_section("الإعراب", page.get("grammar"), "grammar", page_refs, show_refs)
            if show_flags["balagha"]:
                display_section("البلاغة", page.get("balagha"), "balagha", page_refs, show_refs)
            if show_flags["edu"]:
                display_section("الفوائد التربوية", page.get("educational_benefits"), "educational_benefits", page_refs, show_refs)
            if show_flags["sci"]:
                display_section("الفوائد العلمية واللطائف", page.get("scientific_benefits"), "scientific_benefits", page_refs, show_refs)

            print("\n" + "-" * 50 + "\n")
    if pages_displayed == 0:
        print("تنبيه: لم يتم العثور على صفحات تفسير تغطي النطاق المطلوب.")


def setup_cli_parser():
    """
    يبني parser لواجهة سطر الأوامر.
    """
    parser = argparse.ArgumentParser(
        description="أداة استخراج وعرض نصوص التفسير المحرر من ملفات JSON المحلية.",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument("surah", type=int, help="رقم السورة المراد عرض تفسيرها (من 1 إلى 114).")
    parser.add_argument("-f", "--from-verse", type=int, default=1, help="رقم آية البداية (الافتراضي: 1).")
    parser.add_argument("-t", "--to-verse", type=int, default=None, help="رقم آية النهاية (الافتراضي: نهاية السورة).")
    parser.add_argument("-i", "--intro", action="store_true", help="عرض مقدمة السورة.")
    parser.add_argument("-v", "--verses", action="store_true", help="عرض نص الآيات الكريمة.")
    parser.add_argument("-c", "--vocab", action="store_true", help="عرض غريب الكلمات.")
    parser.add_argument("-m", "--meaning", action="store_true", help="عرض المعنى الإجمالي.")
    parser.add_argument("-d", "--detail", action="store_true", help="عرض التفسير التفصيلي.")
    parser.add_argument("-g", "--grammar", action="store_true", help="عرض الإعراب.")
    parser.add_argument("-b", "--balagha", action="store_true", help="عرض البلاغة.")
    parser.add_argument("-e", "--edu", action="store_true", help="عرض الفوائد التربوية.")
    parser.add_argument("-s", "--sci", action="store_true", help="عرض الفوائد العلمية واللطائف.")
    parser.add_argument("-a", "--all", action="store_true", help="عرض كل الأقسام (السلوك الافتراضي).")
    parser.add_argument("--no-ref", action="store_true", help="حجب الحواشي والمراجع تماماً من العرض.")
    return parser


def main():
    # فرض ترميز UTF-8 لضمان صحة طباعة الحروف العربية في الطرفية
    sys.stdout.reconfigure(encoding="utf-8")

    parser = setup_cli_parser()
    args = parser.parse_args()

    if not (1 <= args.surah <= 114):
        sys.exit("خطأ: يجب أن يكون رقم السورة بين 1 و 114.")

    # تحديد مسار المجلد الأب (التفسير المحرر) لأن السكربت يقع في مجلد scripts
    base_dir = Path(__file__).resolve().parent.parent
    surah_data = load_surah_data(args.surah, base_dir)

    surah_name = surah_data.get("surah_name", "")
    tafseer_pages = surah_data.get("tafseer_pages", [])

    total_verses = calculate_total_verses(tafseer_pages)
    to_verse = args.to_verse if args.to_verse is not None else total_verses

    if not (1 <= args.from_verse <= total_verses):
        sys.exit(f"خطأ: آية البداية غير صالحة لهذه السورة (تحتوي على {total_verses} آية).")
    if not (args.from_verse <= to_verse <= total_verses):
        sys.exit(f"خطأ: نطاق الآيات غير صالح (يجب أن يكون بين آية البداية و {total_verses}).")

    # تحديد الأقسام المطلوب عرضها
    show_all = args.all or not any([
        args.intro, args.verses, args.vocab, args.meaning,
        args.detail, args.grammar, args.balagha, args.edu, args.sci
    ])

    show_flags = {
        "intro": show_all or args.intro,
        "verses": show_all or args.verses,
        "vocab": show_all or args.vocab,
        "meaning": show_all or args.meaning,
        "detail": show_all or args.detail,
        "grammar": show_all or args.grammar,
        "balagha": show_all or args.balagha,
        "edu": show_all or args.edu,
        "sci": show_all or args.sci
    }
    show_refs = not args.no_ref

    print("=" * 60)
    print(f"سورة {surah_name} (رقمها: {args.surah}) | الآيات المطلوبة: {args.from_verse} - {to_verse}")
    print("=" * 60 + "\n")

    if show_flags["intro"]:
        display_introduction(surah_data, show_refs)

    display_tafseer_pages(tafseer_pages, args.from_verse, to_verse, show_flags, show_refs)


if __name__ == "__main__":
    main()
