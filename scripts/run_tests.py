#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
سكربت اختبار مؤتمت شامل للتحقق من صحة عمل get_tafsir.py.
يقوم بتشغيل حالات اختبار متعددة ويتحقق من كود الخروج والمخرجات النصية.
"""

import subprocess
import sys
from pathlib import Path


def run_command(args):
    """
    يشغل السكربت كعملية فرعية ويعيد كود الخروج والمخرجات.
    """
    env = {"PYTHONIOENCODING": "utf-8"}
    base_dir = Path(__file__).resolve().parent
    script_path = base_dir / "get_tafsir.py"
    cmd = [sys.executable, str(script_path)] + args
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env
    )
    return result.returncode, result.stdout, result.stderr


def print_status(test_name, passed, detail=""):
    """
    يطبع حالة الاختبار بأسلوب وقور ومنظم.
    """
    status = "ناجح" if passed else "فاشل"
    print(f"[{status}] - {test_name}")
    if not passed and detail:
        print(f"   السبب: {detail}")


def run_single_test(test_case):
    """
    يشغل حالة اختبار واحدة ويتحقق من مطابقتها للتوقعات.
    """
    code, stdout, stderr = run_command(test_case["args"])
    
    # 1. التحقق من كود الخروج
    expected_code = test_case.get("expected_code", 0)
    if (expected_code == 0 and code != 0) or (expected_code != 0 and code == 0):
        return False, f"كود الخروج الفعلي {code} لا يطابق المتوقع {expected_code}."

    # 2. تحديد مصدر البحث (stdout أو stderr)
    target_output = stderr if test_case.get("search_stderr", False) else stdout

    # 3. التحقق من وجود الكلمات المطلوبة
    for expected in test_case.get("expected_contains", []):
        if expected not in target_output:
            return False, f"غياب الكلمة المفتاحية المتوقعة: '{expected}'."

    # 4. التحقق من خلو المخرجات من الكلمات الممنوعة
    for forbidden in test_case.get("forbidden_contains", []):
        if forbidden in target_output:
            return False, f"وجود كلمة ممنوعة في المخرجات: '{forbidden}'."

    return True, ""


def main():
    print("=" * 60)
    print("بدء تشغيل اختبارات جلب التفسير المحرر (get_tafsir.py)...")
    print("=" * 60 + "\n")

    # تعريف حالات الاختبار الشاملة بشكل نظيف وقابل للتوسيع
    test_cases = [
        {
            "name": "اختبار معامل المساعدة (--help)",
            "args": ["--help"],
            "expected_code": 0,
            "expected_contains": ["أداة استخراج وعرض"]
        },
        {
            "name": "اختبار عرض السورة الافتراضي الكامل (سورة 112)",
            "args": ["112"],
            "expected_code": 0,
            "expected_contains": ["سورة الإخلاص", "[مقدمة السورة]", "التفسير التفصيلي"]
        },
        {
            "name": "اختبار تعطيل الحواشي والمراجع (--no-ref)",
            "args": ["112", "--no-ref"],
            "expected_code": 0,
            "expected_contains": ["سورة الإخلاص"],
            "forbidden_contains": ["[حواشي"]
        },
        {
            "name": "اختبار نطاق الآيات (الآيات 2-3 من سورة 112)",
            "args": ["112", "-f", "2", "-t", "3"],
            "expected_code": 0,
            "expected_contains": ["=== [الآيات: 1-4] ===", "اللَّهُ الصَّمَدُ"]
        },
        {
            "name": "اختبار تصفية أقسام معينة (--verses --detail --no-ref)",
            "args": ["112", "--verses", "--detail", "--no-ref"],
            "expected_code": 0,
            "expected_contains": ["* الآيات الكريمة:", "* التفسير التفصيلي:"],
            "forbidden_contains": ["* غريب الكلمات:"]
        },
        {
            "name": "اختبار سورة متعددة الصفحات (سورة الكوثر 108)",
            "args": ["108"],
            "expected_code": 0,
            "expected_contains": ["سورة الكوثر"]
        },
        {
            "name": "اختبار إدخال رقم سورة خارج النطاق (115)",
            "args": ["115"],
            "expected_code": 1,
            "search_stderr": True,
            "expected_contains": ["خطأ"]
        },
        {
            "name": "اختبار إدخال غير رقمي لرقم السورة (abc)",
            "args": ["abc"],
            "expected_code": 2,
            "search_stderr": True,
            "expected_contains": ["invalid int value"]
        },
        {
            "name": "اختبار آية بداية خارج النطاق (آية 10 من سورة 112)",
            "args": ["112", "-f", "10"],
            "expected_code": 1,
            "search_stderr": True,
            "expected_contains": ["غير صالحة لهذه السورة"]
        },
        {
            "name": "اختبار آية نهاية أصغر من آية البداية (-f 3 -t 2)",
            "args": ["112", "-f", "3", "-t", "2"],
            "expected_code": 1,
            "search_stderr": True,
            "expected_contains": ["نطاق الآيات غير صالح"]
        }
    ]

    tests_failed = 0
    for case in test_cases:
        passed, detail = run_single_test(case)
        print_status(case["name"], passed, detail)
        if not passed:
            tests_failed += 1

    print("\n" + "=" * 60)
    print(f"النتيجة النهائية: تشغيل {len(test_cases)} اختبارات، الفشل: {tests_failed}.")
    print("=" * 60)

    if tests_failed > 0:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
