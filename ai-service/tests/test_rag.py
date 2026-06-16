import unittest
from unittest.mock import patch

import app.main as main
from app.main import CHUNKS, IndexRequest, SearchRequest, index_document, rag_search, split_text


def parse_vector_literal(value):
    return [float(item) for item in value.strip("[]").split(",") if item]


class FakePostgresCursor:
    def __init__(self, database):
        self.database = database
        self.result = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params=()):
        compact = " ".join(sql.split())
        if compact.startswith("INSERT INTO knowledge_bases"):
            self.database.knowledge_bases.add(params[0])
            self.result = None
            return
        if compact.startswith("SELECT id, status, chunk_count FROM documents"):
            kb_id, content_hash = params
            self.result = next(
                (
                    {"id": doc["id"], "status": doc["status"], "chunk_count": doc["chunk_count"]}
                    for doc in self.database.documents.values()
                    if doc["knowledge_base_id"] == kb_id and doc["content_hash"] == content_hash
                ),
                None,
            )
            return
        if compact.startswith("INSERT INTO documents"):
            document_id, kb_id, filename, status, content_hash, chunk_count = params
            if any(doc["knowledge_base_id"] == kb_id and doc["content_hash"] == content_hash for doc in self.database.documents.values()):
                raise RuntimeError("duplicate content hash")
            self.database.documents[document_id] = {
                "id": document_id,
                "knowledge_base_id": kb_id,
                "filename": filename,
                "status": status,
                "content_hash": content_hash,
                "chunk_count": chunk_count,
            }
            self.result = None
            return
        if compact.startswith("SELECT count(*) AS chunk_total FROM document_chunks"):
            (document_id,) = params
            self.result = {"chunk_total": sum(1 for chunk in self.database.chunks if chunk["document_id"] == document_id)}
            return
        if compact.startswith("DELETE FROM document_chunks"):
            (document_id,) = params
            self.database.chunks = [chunk for chunk in self.database.chunks if chunk["document_id"] != document_id]
            self.result = None
            return
        if compact.startswith("DELETE FROM documents"):
            (document_id,) = params
            self.database.documents.pop(document_id, None)
            self.result = None
            return
        if compact.startswith("INSERT INTO document_chunks"):
            chunk_id, document_id, kb_id, filename, position, content, embedding, allowed_user_ids = params
            self.database.chunks.append(
                {
                    "chunk_id": chunk_id,
                    "document_id": document_id,
                    "knowledge_base_id": kb_id,
                    "filename": filename,
                    "position": position,
                    "text": content,
                    "embedding": parse_vector_literal(embedding),
                    "allowed_user_ids": allowed_user_ids,
                }
            )
            self.result = None
            return
        if "FROM document_chunks" in compact:
            query_vector, kb_ids, user_id, _query_vector_for_order, limit = params
            query = parse_vector_literal(query_vector)
            rows = []
            for chunk in self.database.chunks:
                if chunk["knowledge_base_id"] not in kb_ids:
                    continue
                if chunk["allowed_user_ids"] and user_id not in chunk["allowed_user_ids"]:
                    continue
                rows.append({**chunk, "vector_score": main.cosine(query, chunk["embedding"])})
            rows.sort(key=lambda item: item["vector_score"], reverse=True)
            self.result = rows[:limit]
            return
        raise AssertionError(f"Unhandled SQL: {compact}")

    def fetchone(self):
        return self.result

    def fetchall(self):
        return self.result or []


class FakePostgresConnection:
    def __init__(self, database):
        self.database = database

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def cursor(self):
        return FakePostgresCursor(self.database)

    def rollback(self):
        return None


class FakePostgresDatabase:
    def __init__(self):
        self.knowledge_bases = set()
        self.documents = {}
        self.chunks = []

    def connection(self):
        return FakePostgresConnection(self)


class RagServiceTest(unittest.TestCase):
    def setUp(self):
        CHUNKS.clear()

    def test_split_text_uses_overlap(self):
        chunks = split_text("a" * 1100)
        self.assertEqual(3, len(chunks))
        self.assertEqual(500, len(chunks[0]))

    def test_split_text_filters_pdf_page_markers(self):
        chunks = split_text("Page 4\n— 3 —\n员工累计工作已满1年不满10年的，年休假5天。")

        self.assertEqual(["员工累计工作已满1年不满10年的，年休假5天。"], chunks)

    def test_search_filters_by_user_acl(self):
        index_document(
            IndexRequest(
                document_id="doc-1",
                knowledge_base_id="kb-hr",
                filename="policy.txt",
                content="报销需要发票和审批单",
                allowed_user_ids=["u-admin"],
            )
        )

        denied = rag_search(SearchRequest(user_id="u-analyst", query="报销", knowledge_base_ids=["kb-hr"]))
        allowed = rag_search(SearchRequest(user_id="u-admin", query="报销", knowledge_base_ids=["kb-hr"]))

        self.assertEqual([], denied["results"])
        self.assertEqual(1, len(allowed["results"]))

    def test_memory_search_treats_empty_legacy_acl_as_kb_scoped(self):
        index_document(
            IndexRequest(
                document_id="doc-kb-scope",
                knowledge_base_id="kb-hr",
                filename="policy.txt",
                content="Travel reimbursement requires manager approval.",
                allowed_user_ids=[],
            )
        )

        allowed = rag_search(SearchRequest(user_id="u-analyst", query="travel reimbursement", knowledge_base_ids=["kb-hr"]))
        denied_by_kb_scope = rag_search(SearchRequest(user_id="u-analyst", query="travel reimbursement", knowledge_base_ids=["kb-tech"]))

        self.assertEqual(1, len(allowed["results"]))
        self.assertEqual("kb-hr", allowed["results"][0]["knowledge_base_id"])
        self.assertEqual([], denied_by_kb_scope["results"])

    def test_postgres_search_treats_empty_legacy_acl_as_kb_scoped(self):
        database = FakePostgresDatabase()

        with patch.object(main, "VECTOR_DATABASE_URL", "postgresql://test"), patch.object(main, "postgres_connection", database.connection):
            index_document(
                IndexRequest(
                    document_id="doc-pg-kb-scope",
                    knowledge_base_id="kb-hr",
                    filename="policy.txt",
                    content="Travel reimbursement requires manager approval.",
                    content_hash="pg-kb-scope",
                    allowed_user_ids=[],
                )
            )
            allowed = rag_search(SearchRequest(user_id="u-analyst", query="travel reimbursement", knowledge_base_ids=["kb-hr"]))
            denied_by_kb_scope = rag_search(SearchRequest(user_id="u-analyst", query="travel reimbursement", knowledge_base_ids=["kb-tech"]))

        self.assertEqual(1, len(allowed["results"]))
        self.assertEqual("doc-pg-kb-scope", allowed["results"][0]["document_id"])
        self.assertEqual([], denied_by_kb_scope["results"])

    def test_pgvector_dedupes_same_hash_within_knowledge_base(self):
        database = FakePostgresDatabase()
        payload = IndexRequest(
            document_id="doc-original",
            knowledge_base_id="kb-hr",
            filename="policy.txt",
            content="Employees must submit reimbursement invoices within 30 days.",
            content_hash="same-content",
            allowed_user_ids=["u-admin"],
        )

        with patch.object(main, "VECTOR_DATABASE_URL", "postgresql://test"), patch.object(main, "postgres_connection", database.connection):
            first = index_document(payload)
            second = index_document(
                IndexRequest(
                    document_id="doc-duplicate",
                    knowledge_base_id="kb-hr",
                    filename="policy-copy.txt",
                    content="Employees must submit reimbursement invoices within 30 days.",
                    content_hash="same-content",
                    allowed_user_ids=["u-admin"],
                )
            )

        self.assertFalse(first["duplicate"])
        self.assertTrue(second["duplicate"])
        self.assertEqual("doc-original", second["document_id"])
        self.assertEqual(1, len(database.documents))
        self.assertEqual(first["chunk_count"], len(database.chunks))

    def test_pgvector_allows_same_hash_in_different_knowledge_bases(self):
        database = FakePostgresDatabase()

        with patch.object(main, "VECTOR_DATABASE_URL", "postgresql://test"), patch.object(main, "postgres_connection", database.connection):
            first = index_document(
                IndexRequest(
                    document_id="doc-hr",
                    knowledge_base_id="kb-hr",
                    filename="policy.txt",
                    content="Shared policy text.",
                    content_hash="same-content",
                    allowed_user_ids=["u-admin"],
                )
            )
            second = index_document(
                IndexRequest(
                    document_id="doc-tech",
                    knowledge_base_id="kb-tech",
                    filename="policy.txt",
                    content="Shared policy text.",
                    content_hash="same-content",
                    allowed_user_ids=["u-admin"],
                )
            )

        self.assertFalse(first["duplicate"])
        self.assertFalse(second["duplicate"])
        self.assertEqual({"doc-hr", "doc-tech"}, set(database.documents))

    def test_pgvector_search_reads_persisted_chunks_after_memory_clear(self):
        database = FakePostgresDatabase()

        with patch.object(main, "VECTOR_DATABASE_URL", "postgresql://test"), patch.object(main, "postgres_connection", database.connection):
            index_document(
                IndexRequest(
                    document_id="doc-persisted",
                    knowledge_base_id="kb-hr",
                    filename="policy.txt",
                    content="Employees must submit reimbursement invoices within 30 days.",
                    content_hash="persisted-content",
                    allowed_user_ids=["u-admin"],
                )
            )
            CHUNKS.clear()
            response = rag_search(SearchRequest(user_id="u-admin", query="reimbursement invoices", knowledge_base_ids=["kb-hr"]))

        self.assertEqual(1, len(response["results"]))
        self.assertEqual("doc-persisted", response["results"][0]["document_id"])

    def test_rerank_prefers_relevant_annual_leave_chunk(self):
        index_document(
            IndexRequest(
                document_id="doc-policy",
                knowledge_base_id="kb-hr",
                filename="attendance.txt",
                content=(
                    "发生5次及以下可通过PMS平台提交补卡申请，经部门审批后作正常出勤处理。"
                    "出差员工因公出差1天及以上须通过财务共享系统发起出差申请。"
                    "员工连续工作满1年不满10年的，年休假5天；满10年不满20年的，年休假10天；满20年的，年休假15天。"
                ),
                allowed_user_ids=["u-admin"],
            )
        )

        response = rag_search(SearchRequest(user_id="u-admin", query="年假有多少天", knowledge_base_ids=["kb-hr"]))

        self.assertGreaterEqual(len(response["results"]), 1)
        self.assertIn("年休假", response["results"][0]["text"])
        self.assertIn("5天", response["results"][0]["text"])


if __name__ == "__main__":
    unittest.main()
