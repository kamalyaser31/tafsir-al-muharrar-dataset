#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
واجهة رسومية محلية لتصفح ملفات JSON الخاصة بالتفسير المحرر.
"""

import json
import sys
from pathlib import Path

import wx


TAFSEER_ALL_FILENAME = "tafseer_all.json"
INTRO_RANGE_LABEL = "مقدمة السورة"
VERSE_RANGE_PREFIX = "الآيات: "

SECTION_OPTIONS = (
    ("verses", "الآيات الكريمة"),
    ("vocabulary", "غريب الكلمات"),
    ("general_meaning", "المعنى الإجمالي"),
    ("tafseer", "التفسير التفصيلي"),
    ("grammar", "الإعراب"),
    ("balagha", "البلاغة"),
    ("educational_benefits", "الفوائد التربوية"),
    ("scientific_benefits", "الفوائد العلمية واللطائف"),
)


def configure_stdout_encoding():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")


class TafseerGuiFrame(wx.Frame):
    def __init__(self, parent, title):
        super().__init__(
            parent, id=wx.ID_ANY, title=title, size=(900, 650), style=wx.DEFAULT_FRAME_STYLE
        )

        self.project_dir = Path(__file__).resolve().parent.parent
        self.json_dir = self.project_dir / "json"
        self.load_warning_message = ""

        self.all_surahs = []
        self.filtered_surahs = []
        self.current_surah_data = None
        self.current_text_content = ""

        self.load_surahs_index()
        self.init_ui()
        self.show_initial_content()

    def load_surahs_index(self):
        if not self.json_dir.exists():
            self.load_warning_message = f"خطأ: مجلد ملفات JSON غير موجود:\n{self.json_dir}"
            return

        skipped_files = []
        surah_summaries = []
        for json_path in sorted(self.json_dir.glob("*.json")):
            if json_path.name == TAFSEER_ALL_FILENAME:
                continue

            try:
                surah_summary = self.read_surah_summary(json_path)
            except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
                skipped_files.append(f"{json_path.name}: {exc}")
                continue

            if surah_summary:
                surah_summaries.append(surah_summary)

        self.all_surahs = sorted(surah_summaries, key=lambda surah: surah["num"])
        self.filtered_surahs = list(self.all_surahs)
        self.load_warning_message = self.surah_load_warning(skipped_files)

    def read_surah_summary(self, json_path):
        with json_path.open("r", encoding="utf-8") as json_file:
            surah_data = json.load(json_file)

        surah_num = surah_data.get("surah_num")
        surah_name = surah_data.get("surah_name")
        if surah_num is None or not surah_name:
            return None

        return {
            "num": int(surah_num),
            "name": surah_name,
            "display": f"{surah_num}. {surah_name}",
            "file": json_path,
        }

    def surah_load_warning(self, skipped_files):
        if skipped_files:
            details = "\n".join(skipped_files[:10])
            return f"تنبيه: تعذر قراءة {len(skipped_files)} ملف JSON.\n{details}"
        if not self.all_surahs:
            return f"تنبيه: لا توجد ملفات سور قابلة للقراءة في:\n{self.json_dir}"
        return ""

    def init_ui(self):
        main_panel = wx.Panel(self)
        control_panel = self.create_control_panel(main_panel)
        display_panel = self.create_display_panel(main_panel)

        main_sizer = wx.BoxSizer(wx.HORIZONTAL)
        main_sizer.Add(control_panel, 35, wx.EXPAND | wx.ALL, 5)
        main_sizer.Add(display_panel, 65, wx.EXPAND | wx.ALL, 5)
        main_panel.SetSizer(main_sizer)
        self.Centre()

    def create_control_panel(self, parent):
        panel = wx.Panel(parent)
        sizer = wx.BoxSizer(wx.VERTICAL)

        self.add_search_controls(panel, sizer)
        self.add_range_controls(panel, sizer)
        sizer.Add(self.create_sections_box(panel), 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 5)
        self.add_reference_checkbox(panel, sizer)
        self.add_action_buttons(panel, sizer)

        panel.SetSizer(sizer)
        return panel

    def add_search_controls(self, panel, sizer):
        search_label = wx.StaticText(panel, label="البحث السريع عن السورة:")
        self.search_ctrl = wx.TextCtrl(panel, style=wx.TE_PROCESS_ENTER)
        self.search_ctrl.SetHint("اكتب اسم السورة أو جزءاً منه...")
        self.search_ctrl.Bind(wx.EVT_TEXT, self.on_search_text)

        surah_label = wx.StaticText(panel, label="اختر السورة:")
        surah_choices = [surah["display"] for surah in self.filtered_surahs]
        self.surah_combo = wx.ComboBox(panel, style=wx.CB_READONLY, choices=surah_choices)
        self.surah_combo.Bind(wx.EVT_COMBOBOX, self.on_surah_selected)

        sizer.Add(search_label, 0, wx.ALL | wx.EXPAND, 5)
        sizer.Add(self.search_ctrl, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 5)
        sizer.Add(surah_label, 0, wx.ALL | wx.EXPAND, 5)
        sizer.Add(self.surah_combo, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 5)

    def add_range_controls(self, panel, sizer):
        range_label = wx.StaticText(panel, label="اختر الآيات أو النطاق:")
        self.range_combo = wx.ComboBox(panel, style=wx.CB_READONLY, choices=[])
        self.range_combo.Bind(wx.EVT_COMBOBOX, self.on_range_selected)

        sizer.Add(range_label, 0, wx.ALL | wx.EXPAND, 5)
        sizer.Add(self.range_combo, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 5)

    def create_sections_box(self, panel):
        sections_box = wx.StaticBox(panel, label="الأقسام المراد عرضها:")
        sections_sizer = wx.StaticBoxSizer(sections_box, wx.VERTICAL)
        self.section_checkboxes = {}

        for section_key, section_title in SECTION_OPTIONS:
            checkbox = wx.CheckBox(sections_box, label=section_title)
            checkbox.SetValue(True)
            checkbox.Bind(wx.EVT_CHECKBOX, self.on_option_changed)
            sections_sizer.Add(checkbox, 0, wx.ALL | wx.EXPAND, 3)
            self.section_checkboxes[section_key] = checkbox

        return sections_sizer

    def add_reference_checkbox(self, panel, sizer):
        self.refs_checkbox = wx.CheckBox(panel, label="إظهار الحواشي والمراجع أسفل الأقسام")
        self.refs_checkbox.SetValue(True)
        self.refs_checkbox.Bind(wx.EVT_CHECKBOX, self.on_option_changed)
        sizer.Add(self.refs_checkbox, 0, wx.ALL | wx.EXPAND, 5)

    def add_action_buttons(self, panel, sizer):
        self.copy_button = wx.Button(panel, label="نسخ النص للحافظة")
        self.copy_button.Bind(wx.EVT_BUTTON, self.on_copy_text)

        self.export_button = wx.Button(panel, label="تصدير كـ Markdown")
        self.export_button.Bind(wx.EVT_BUTTON, self.on_export_markdown)

        sizer.Add(self.copy_button, 0, wx.ALL | wx.EXPAND, 5)
        sizer.Add(self.export_button, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 5)

    def create_display_panel(self, parent):
        panel = wx.Panel(parent)
        sizer = wx.BoxSizer(wx.VERTICAL)

        display_label = wx.StaticText(panel, label="نص التفسير والمخرجات:")
        self.text_display = wx.TextCtrl(
            panel, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_RICH2
        )
        self.text_display.SetFont(self.display_font())

        sizer.Add(display_label, 0, wx.ALL | wx.EXPAND, 5)
        sizer.Add(self.text_display, 1, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 5)
        panel.SetSizer(sizer)
        return panel

    def display_font(self):
        arabic_font = wx.Font(
            14, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL, faceName="Amiri"
        )
        if arabic_font.IsOk():
            return arabic_font
        return wx.Font(
            13, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL, faceName="Arial"
        )

    def show_initial_content(self):
        if self.filtered_surahs:
            self.surah_combo.SetSelection(0)
            self.on_surah_selected(None)

        if self.load_warning_message:
            if not self.filtered_surahs:
                self.set_display_text(self.load_warning_message)
            wx.MessageBox(self.load_warning_message, "تنبيه في قراءة JSON", wx.OK | wx.ICON_WARNING)

    def set_display_text(self, text):
        self.current_text_content = text
        self.text_display.SetValue(text)

    def clear_display_text(self):
        self.current_text_content = ""
        self.text_display.Clear()

    def on_search_text(self, event):
        query = self.search_ctrl.GetValue().strip()
        current_selection = self.surah_combo.GetStringSelection()

        self.filtered_surahs = self.filtered_surah_list(query)
        choices = [surah["display"] for surah in self.filtered_surahs]
        self.surah_combo.Clear()
        self.surah_combo.AppendItems(choices)

        if not choices:
            self.range_combo.Clear()
            self.set_display_text("تنبيه: لم يتم العثور على سور تطابق نص البحث.")
            return

        if current_selection in choices:
            self.surah_combo.SetStringSelection(current_selection)
        else:
            self.surah_combo.SetSelection(0)
        self.on_surah_selected(None)

    def filtered_surah_list(self, query):
        if not query:
            return list(self.all_surahs)

        return [
            surah for surah in self.all_surahs
            if query in surah["name"] or query in str(surah["num"])
        ]

    def on_surah_selected(self, event):
        selection_index = self.surah_combo.GetSelection()
        if selection_index == wx.NOT_FOUND:
            self.current_surah_data = None
            self.range_combo.Clear()
            self.clear_display_text()
            return

        surah_summary = self.filtered_surahs[selection_index]
        try:
            with surah_summary["file"].open("r", encoding="utf-8") as json_file:
                self.current_surah_data = json.load(json_file)
        except (OSError, json.JSONDecodeError) as exc:
            wx.MessageBox(
                f"فشل تحميل بيانات السورة:\n{exc}",
                "خطأ في قراءة الملف",
                wx.OK | wx.ICON_ERROR,
            )
            return

        self.populate_range_combo()

    def populate_range_combo(self):
        range_choices = self.available_range_choices()
        self.range_combo.Clear()

        if not range_choices:
            self.set_display_text("تنبيه: لا توجد صفحات تفسير متوفرة لهذه السورة.")
            return

        self.range_combo.AppendItems(range_choices)
        self.range_combo.SetSelection(0)
        self.on_range_selected(None)

    def available_range_choices(self):
        range_choices = []
        intro_text = self.current_surah_data.get("introduction")
        if intro_text and intro_text.strip():
            range_choices.append(INTRO_RANGE_LABEL)

        for tafseer_page in self.current_surah_data.get("tafseer_pages", []):
            verse_range = tafseer_page.get("verse_range")
            if verse_range:
                range_choices.append(f"{VERSE_RANGE_PREFIX}{verse_range}")
        return range_choices

    def on_range_selected(self, event):
        self.update_display_text()

    def on_option_changed(self, event):
        self.update_display_text()

    def update_display_text(self):
        if not self.current_surah_data or self.range_combo.GetSelection() == wx.NOT_FOUND:
            self.clear_display_text()
            return

        range_label = self.range_combo.GetString(self.range_combo.GetSelection())
        self.set_display_text(self.formatted_range_text(range_label))

    def formatted_range_text(self, range_label):
        blocks = self.document_header_blocks(range_label)
        if range_label == INTRO_RANGE_LABEL:
            blocks.extend(self.introduction_blocks())
        else:
            blocks.extend(self.tafseer_page_blocks(range_label))
        return "\n\n".join(blocks)

    def document_header_blocks(self, range_label):
        surah_name = self.current_surah_data.get("surah_name", "")
        surah_num = self.current_surah_data.get("surah_num", "")
        return [
            f"# {surah_name}",
            f"رقم السورة: {surah_num} | النطاق المحدد: {range_label}\n",
            "=" * 40,
        ]

    def introduction_blocks(self):
        intro_text = self.current_surah_data.get("introduction", "").strip()
        blocks = ["## مقدمة السورة:\n", intro_text]

        intro_refs = self.current_surah_data.get("introduction_references", [])
        if self.refs_checkbox.GetValue() and intro_refs:
            blocks.append("\n### حواشي مقدمة السورة:")
            blocks.extend(f"* {reference.strip()}" for reference in intro_refs)
        return blocks

    def tafseer_page_blocks(self, range_label):
        selected_page = self.selected_tafseer_page(range_label)
        if not selected_page:
            return ["تنبيه: لم يتم العثور على بيانات نطاق الآيات المختار."]

        page_refs = selected_page.get("references", {})
        blocks = []
        for section_key, section_title in SECTION_OPTIONS:
            blocks.extend(self.section_blocks(selected_page, section_key, section_title, page_refs))
        return blocks

    def selected_tafseer_page(self, range_label):
        selected_range = range_label.replace(VERSE_RANGE_PREFIX, "", 1).strip()
        for tafseer_page in self.current_surah_data.get("tafseer_pages", []):
            if tafseer_page.get("verse_range") == selected_range:
                return tafseer_page
        return None

    def section_blocks(self, tafseer_page, section_key, section_title, page_refs):
        if not self.section_checkboxes[section_key].GetValue():
            return []

        section_text = tafseer_page.get(section_key)
        if not section_text:
            return []

        if section_key == "verses":
            verses = section_text.strip().replace("«", "").replace("»", "")
            return ["## الآيات الكريمة:\n", f"﴿ {verses} ﴾\n"]

        blocks = [f"## {section_title}:\n", section_text.strip()]
        section_refs = page_refs.get(section_key, [])
        if self.refs_checkbox.GetValue() and section_refs:
            blocks.append(f"\n* حواشي {section_title}:")
            blocks.extend(f"  {reference.strip()}" for reference in section_refs)
        blocks.append("")
        return blocks

    def on_copy_text(self, event):
        if not self.current_text_content:
            wx.Bell()
            return

        if not wx.TheClipboard.Open():
            wx.MessageBox("فشل فتح الحافظة لنسخ النص.", "خطأ", wx.OK | wx.ICON_ERROR)
            return

        try:
            copied = wx.TheClipboard.SetData(wx.TextDataObject(self.current_text_content))
        finally:
            wx.TheClipboard.Close()

        if copied:
            wx.MessageBox("تم نسخ نص التفسير والفوائد للحافظة بنجاح.", "تم النسخ", wx.OK | wx.ICON_INFORMATION)
        else:
            wx.MessageBox("تعذر وضع النص في الحافظة.", "خطأ", wx.OK | wx.ICON_ERROR)

    def on_export_markdown(self, event):
        if not self.current_text_content:
            wx.Bell()
            return

        with wx.FileDialog(
            self,
            message="حفظ التفسير كملف Markdown",
            defaultDir="",
            defaultFile=self.suggested_markdown_filename(),
            wildcard="ملفات Markdown (*.md)|*.md|ملفات نصية (*.txt)|*.txt",
            style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT,
        ) as file_dialog:
            if file_dialog.ShowModal() == wx.ID_CANCEL:
                return
            self.write_markdown_file(file_dialog.GetPath())

    def suggested_markdown_filename(self):
        surah_name = self.current_surah_data.get("surah_name", "") if self.current_surah_data else ""
        range_label = ""
        if self.range_combo.GetSelection() != wx.NOT_FOUND:
            range_label = self.range_combo.GetString(self.range_combo.GetSelection())
            range_label = range_label.replace(VERSE_RANGE_PREFIX, "").replace(INTRO_RANGE_LABEL, "المقدمة")
        return f"تفسير_{surah_name}_{range_label}.md".replace(" ", "_")

    def write_markdown_file(self, file_path):
        try:
            Path(file_path).write_text(self.current_text_content, encoding="utf-8")
        except OSError as exc:
            wx.MessageBox(
                f"حدث خطأ أثناء حفظ الملف:\n{exc}",
                "خطأ في الحفظ",
                wx.OK | wx.ICON_ERROR,
            )
            return
        wx.MessageBox("تم تصدير ملف التفسير والفوائد بنجاح.", "تم التصدير", wx.OK | wx.ICON_INFORMATION)


class TafseerGuiApp(wx.App):
    def OnInit(self):
        self.SetAppName("TafseerLocalBrowser")
        frame = TafseerGuiFrame(None, title="متصفح موسوعة التفسير المحرر المحلي")
        frame.Show(True)
        return True


def main():
    app = TafseerGuiApp()
    app.MainLoop()


if __name__ == "__main__":
    configure_stdout_encoding()
    main()
