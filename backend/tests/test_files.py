import tempfile
import unittest
from pathlib import Path

from docx import Document
from openpyxl import load_workbook

from app.files import (
    create_excel_workbook,
    create_word_document,
    execute_approved_operation,
    file_hash,
    list_files,
    read_excel_workbook,
    read_word_document,
    update_excel_cell,
    update_word_document,
)


class AgentFileTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary_directory.name)

    def tearDown(self):
        self.temporary_directory.cleanup()

    def test_create_and_list_word_document(self):
        result = create_word_document(
            self.directory, "Plan.docx", "Project plan", "First step\nSecond step"
        )

        self.assertIn("Plan.docx", result)
        document = Document(self.directory / "Plan.docx")
        self.assertEqual(document.paragraphs[0].text, "Project plan")
        self.assertEqual(document.paragraphs[1].text, "First step")
        self.assertEqual(list_files(self.directory), [{"filename": "Plan.docx", "type": "docx"}])

    def test_create_and_update_workbook(self):
        create_excel_workbook(
            self.directory, "Budget.xlsx", "Costs", ["Item", "Amount"], [["Travel", "100"]]
        )

        result = update_excel_cell(
            self.directory, "Budget.xlsx", "Costs", "B2", "250", expected_hash=None
        )
        workbook = load_workbook(self.directory / "Budget.xlsx", data_only=True)

        self.assertIn("B2", result)
        self.assertEqual(workbook["Costs"]["B2"].value, "250")
        workbook.close()

    def test_read_tools_return_bounded_word_and_excel_contents(self):
        create_word_document(self.directory, "Notes.docx", "Project plan", "Review risks")
        create_excel_workbook(
            self.directory, "Budget.xlsx", "Costs", ["Item", "Amount"], [["Travel", "100"]]
        )

        word_preview = read_word_document(self.directory, "Notes.docx")
        excel_preview = read_excel_workbook(self.directory, "Budget.xlsx")

        self.assertIn("Project plan", word_preview)
        self.assertIn("Review risks", word_preview)
        self.assertIn("Sheet: Costs", excel_preview)
        self.assertIn("Travel | 100", excel_preview)

    def test_word_edit_requires_a_matching_file_snapshot(self):
        create_word_document(self.directory, "Notes.docx", "Notes", "draft")

        with self.assertRaisesRegex(ValueError, "changed after approval"):
            execute_approved_operation(
                self.directory,
                "update_word_document",
                {"filename": "Notes.docx", "find_text": "draft", "replace_text": "final"},
                "incorrect-snapshot",
            )

        self.assertIn("draft", [paragraph.text for paragraph in Document(self.directory / "Notes.docx").paragraphs])

    def test_approved_rename_keeps_file_type_and_does_not_replace_destination(self):
        create_word_document(self.directory, "Before.docx", "Plan", "draft")
        create_word_document(self.directory, "Existing.docx", "Existing", "keep")
        digest = file_hash(self.directory, "Before.docx")
        with self.assertRaises(FileExistsError):
            execute_approved_operation(
                self.directory,
                "rename_agent_file",
                {"filename": "Before.docx", "new_filename": "Existing.docx"},
                digest,
            )
        result = execute_approved_operation(
            self.directory,
            "rename_agent_file",
            {"filename": "Before.docx", "new_filename": "After.docx"},
            digest,
        )

        self.assertIn("Before.docx to After.docx", result)
        self.assertFalse((self.directory / "Before.docx").exists())
        self.assertEqual(Document(self.directory / "After.docx").paragraphs[0].text, "Plan")

    def test_create_never_overwrites_and_paths_cannot_escape(self):
        create_word_document(self.directory, "Keep.docx", "Keep", "original")

        with self.assertRaises(FileExistsError):
            create_word_document(self.directory, "Keep.docx", "Replace", "changed")
        with self.assertRaisesRegex(ValueError, "simple filename"):
            create_word_document(self.directory, "..\\outside.docx", "Outside", "no")

        self.assertEqual(Document(self.directory / "Keep.docx").paragraphs[0].text, "Keep")

    def test_excel_formulas_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "formulas are not supported"):
            create_excel_workbook(
                self.directory, "Unsafe.xlsx", "Sheet", ["Formula"], [["=1+1"]]
            )


if __name__ == "__main__":
    unittest.main()
