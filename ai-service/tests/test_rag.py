import unittest

from app.main import CHUNKS, IndexRequest, SearchRequest, index_document, rag_search, split_text


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
