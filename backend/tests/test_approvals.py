import json
import tempfile
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from docx import Document

from app.agent import execute_tool
from app.core.config import settings
from app.db.session import Base, get_db
from app.files import create_excel_workbook, create_word_document, file_hash
from app.main import app
from app.models import Conversation, PendingApproval


class ApprovalEndpointTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary_directory.name)
        self.previous_files_directory = settings.agent_files_dir
        settings.agent_files_dir = self.directory
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.session_factory = sessionmaker(bind=self.engine)

        def override_db():
            with self.session_factory() as session:
                yield session

        app.dependency_overrides[get_db] = override_db
        self.client = TestClient(app)
        with self.session_factory() as session:
            conversation = Conversation(title="Approval test")
            session.add(conversation)
            session.flush()
            self.conversation_id = conversation.id
            create_word_document(self.directory, "Plan.docx", "Plan", "draft")
            approval = PendingApproval(
                id="test-approval-id",
                conversation_id=conversation.id,
                operation="update_word_document",
                arguments=json.dumps({
                    "filename": "Plan.docx",
                    "find_text": "draft",
                    "replace_text": "approved",
                }),
                summary="Replace draft with approved",
                target_hash=file_hash(self.directory, "Plan.docx"),
                status="pending",
            )
            session.add(approval)
            session.commit()

    def tearDown(self):
        app.dependency_overrides.pop(get_db, None)
        settings.agent_files_dir = self.previous_files_directory
        self.engine.dispose()
        self.temporary_directory.cleanup()

    def test_explicit_approval_applies_the_stored_file_change_once(self):
        response = self.client.post(
            "/api/approvals/test-approval-id", json={"action": "approve"}
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "approved")
        self.assertIn("Approved and completed", response.json()["message"])
        self.assertIn(
            "approved",
            [paragraph.text for paragraph in Document(self.directory / "Plan.docx").paragraphs],
        )
        second_response = self.client.post(
            "/api/approvals/test-approval-id", json={"action": "approve"}
        )
        self.assertEqual(second_response.status_code, 409)

    def test_rejection_does_not_change_the_file(self):
        pending = self.client.get("/api/approvals")
        self.assertEqual(pending.status_code, 200)
        self.assertEqual(pending.json()[0]["id"], "test-approval-id")

        response = self.client.post(
            "/api/approvals/test-approval-id", json={"action": "reject"}
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "rejected")
        self.assertIn(
            "draft",
            [paragraph.text for paragraph in Document(self.directory / "Plan.docx").paragraphs],
        )

    def test_edit_tool_requests_approval_without_changing_the_document(self):
        with self.session_factory() as session:
            response = execute_tool(
                "update_word_document",
                {"filename": "Plan.docx", "find_text": "draft", "replace_text": "final"},
                self.conversation_id,
                session,
            )
            session.commit()

        approval = json.loads(response)
        self.assertEqual(approval["status"], "approval_required")
        self.assertIn('"draft"', approval["summary"])
        self.assertIn('"final"', approval["summary"])
        self.assertIn(
            "draft",
            [paragraph.text for paragraph in Document(self.directory / "Plan.docx").paragraphs],
        )

    def test_file_download_endpoint_returns_document_attachment(self):
        create_word_document(self.directory, "RAG_Overview.docx", "RAG overview", "Document content")

        listing = self.client.get("/api/files")
        response = self.client.get("/api/files/RAG_Overview.docx")
        invalid_path = self.client.get("/api/files/%2E%2E%5Coutside.docx")

        self.assertEqual(listing.status_code, 200)
        self.assertIn(
            {"filename": "RAG_Overview.docx", "type": "docx"},
            listing.json(),
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("attachment", response.headers["content-disposition"])
        self.assertIn("RAG_Overview.docx", response.headers["content-disposition"])
        self.assertTrue(response.content.startswith(b"PK"))
        self.assertEqual(invalid_path.status_code, 400)

    def test_upload_endpoint_accepts_valid_word_file_without_overwrite(self):
        create_word_document(self.directory, "Source.docx", "Uploaded plan", "Upload content")
        document_bytes = (self.directory / "Source.docx").read_bytes()

        response = self.client.post(
            "/api/files",
            files={"file": ("RAG_Upload.docx", document_bytes, "application/octet-stream")},
        )
        duplicate = self.client.post(
            "/api/files",
            files={"file": ("RAG_Upload.docx", document_bytes, "application/octet-stream")},
        )
        invalid = self.client.post(
            "/api/files",
            files={"file": ("not-a-document.docx", b"not a Word file", "application/octet-stream")},
        )
        path_traversal = self.client.post(
            "/api/files",
            files={"file": ("../outside.docx", document_bytes, "application/octet-stream")},
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["filename"], "RAG_Upload.docx")
        self.assertIn("RAG_Upload.docx", [item["filename"] for item in self.client.get("/api/files").json()])
        self.assertEqual(duplicate.status_code, 409)
        self.assertEqual(invalid.status_code, 400)
        self.assertEqual(path_traversal.status_code, 400)
        self.assertFalse((self.directory.parent / "outside.docx").exists())

    def test_upload_endpoint_accepts_valid_excel_and_rejects_unsupported_files(self):
        create_excel_workbook(self.directory, "Source.xlsx", "Data", ["Name"], [["AgentOS"]])
        workbook_bytes = (self.directory / "Source.xlsx").read_bytes()
        response = self.client.post(
            "/api/files",
            files={"file": ("RAG_Upload.xlsx", workbook_bytes, "application/octet-stream")},
        )
        unsupported = self.client.post(
            "/api/files",
            files={"file": ("notes.txt", b"not supported", "text/plain")},
        )
        malformed_excel = self.client.post(
            "/api/files",
            files={"file": ("malformed.xlsx", b"not an Excel workbook", "application/octet-stream")},
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["type"], "xlsx")
        self.assertEqual(unsupported.status_code, 400)
        self.assertEqual(malformed_excel.status_code, 400)

    def test_upload_endpoint_rejects_files_over_10_mib(self):
        oversized = b"x" * ((10 * 1024 * 1024) + 1)

        response = self.client.post(
            "/api/files",
            files={"file": ("large.docx", oversized, "application/octet-stream")},
        )

        self.assertEqual(response.status_code, 413)


if __name__ == "__main__":
    unittest.main()
