import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

import app.main as main
from app.main import CHUNKS, MEMORY, app, compose_retrieval_answer, generate_answer, split_text


class AiApiTest(unittest.TestCase):
    def setUp(self):
        CHUNKS.clear()
        MEMORY.clear()
        main.MODEL_API_KEY = ""
        self.client = TestClient(app)

    def test_index_search_and_agent_response_contract(self):
        index_response = self.client.post(
            "/ai/documents/index",
            json={
                "document_id": "doc-api-1",
                "knowledge_base_id": "kb-hr",
                "filename": "hr-policy.txt",
                "content": "Employees must submit reimbursement invoices within 30 days.",
                "allowed_user_ids": ["u-admin"],
            },
        )
        self.assertEqual(200, index_response.status_code)
        self.assertEqual("READY", index_response.json()["status"])

        search_response = self.client.post(
            "/ai/rag/search",
            json={
                "user_id": "u-admin",
                "query": "reimbursement invoices",
                "knowledge_base_ids": ["kb-hr"],
            },
        )
        self.assertEqual(200, search_response.status_code)
        self.assertEqual(1, len(search_response.json()["results"]))

        agent_response = self.client.post(
            "/ai/agent/run",
            json={
                "user_id": "u-admin",
                "session_id": "session-api-1",
                "question": "What is the reimbursement rule?",
                "knowledge_base_ids": ["kb-hr"],
            },
        )
        body = agent_response.json()
        self.assertEqual(200, agent_response.status_code)
        self.assertIn("answer", body)
        self.assertIn("citations", body)
        self.assertIn("tool_calls", body)
        self.assertEqual("rag_search", body["tool_calls"][0]["name"])

    def test_search_uses_knowledge_base_scope_when_legacy_acl_is_empty(self):
        self.client.post(
            "/ai/documents/index",
            json={
                "document_id": "doc-api-kb-contract",
                "knowledge_base_id": "kb-hr",
                "filename": "hr-contract.txt",
                "content": "The travel reimbursement policy requires manager approval.",
                "allowed_user_ids": [],
            },
        )

        allowed = self.client.post(
            "/ai/rag/search",
            json={
                "user_id": "u-new-role-member",
                "query": "travel reimbursement manager approval",
                "knowledge_base_ids": ["kb-hr"],
            },
        )
        denied_by_kb_scope = self.client.post(
            "/ai/rag/search",
            json={
                "user_id": "u-new-role-member",
                "query": "travel reimbursement manager approval",
                "knowledge_base_ids": ["kb-tech"],
            },
        )

        self.assertEqual(200, allowed.status_code)
        self.assertEqual(1, len(allowed.json()["results"]))
        self.assertEqual("kb-hr", allowed.json()["results"][0]["knowledge_base_id"])
        self.assertEqual(200, denied_by_kb_scope.status_code)
        self.assertEqual([], denied_by_kb_scope.json()["results"])

    def test_index_is_idempotent_for_same_document(self):
        payload = {
            "document_id": "doc-repeat",
            "knowledge_base_id": "kb-hr",
            "filename": "repeat.txt",
            "content": "The same document should replace previous chunks.",
            "allowed_user_ids": ["u-admin"],
        }

        first = self.client.post("/ai/documents/index", json=payload)
        second = self.client.post("/ai/documents/index", json=payload)

        self.assertEqual(200, first.status_code)
        self.assertEqual(200, second.status_code)
        self.assertEqual(1, len([chunk for chunk in CHUNKS if chunk["document_id"] == "doc-repeat"]))

    def test_retrieval_answer_is_never_blank_when_context_exists(self):
        answer = compose_retrieval_answer(
            "报销规则是什么？",
            [
                {
                    "filename": "hr-policy.txt",
                    "text": "Employees must submit reimbursement invoices within 30 days.",
                }
            ],
        )

        self.assertIn("hr-policy.txt", answer)
        self.assertIn("Employees must submit reimbursement invoices", answer)
        self.assertIn("回答：", answer)
        self.assertNotIn("Based on the retrieved", answer)

    def test_fallback_recommends_size_from_retrieved_size_chart(self):
        self.client.post(
            "/ai/documents/index",
            json={
                "document_id": "doc-size-1",
                "knowledge_base_id": "kb-hr",
                "filename": "size-chart.txt",
                "content": (
                    "S 码：身高165-175cm，体重45-55kg。"
                    "M 码：身高175-185cm，体重55-65kg。"
                    "L 码：身高180-190cm，体重65-78kg。"
                ),
                "allowed_user_ids": ["u-admin"],
            },
        )

        response = self.client.post(
            "/ai/agent/run",
            json={
                "user_id": "u-admin",
                "session_id": "session-size-1",
                "question": "我身高180，体重58kg，帮我推荐一下尺码",
                "knowledge_base_ids": ["kb-hr"],
            },
        )
        answer = response.json()["answer"]

        self.assertEqual(200, response.status_code)
        self.assertIn("M 码", answer)
        self.assertIn("size-chart.txt", answer)
        self.assertNotIn("Based on the retrieved", answer)

    def test_fallback_general_answer_uses_chinese_conclusion_and_source(self):
        self.client.post(
            "/ai/documents/index",
            json={
                "document_id": "doc-hr-1",
                "knowledge_base_id": "kb-hr",
                "filename": "hr-policy.txt",
                "content": "员工报销需要在费用发生后30天内提交发票、付款凭证和审批单。",
                "allowed_user_ids": ["u-admin"],
            },
        )

        response = self.client.post(
            "/ai/agent/run",
            json={
                "user_id": "u-admin",
                "session_id": "session-hr-1",
                "question": "员工报销需要注意什么？",
                "knowledge_base_ids": ["kb-hr"],
            },
        )
        answer = response.json()["answer"]

        self.assertEqual(200, response.status_code)
        self.assertIn("回答：", answer)
        self.assertIn("来源：hr-policy.txt", answer)
        self.assertNotIn("Based on the retrieved", answer)

    def test_fallback_answers_clothing_color_and_size_question(self):
        self.client.post(
            "/ai/documents/index",
            json={
                "document_id": "doc-clothing-size",
                "knowledge_base_id": "kb-hr",
                "filename": "尺码推荐.txt",
                "content": (
                    "S 码：身高165-175cm，体重45-55kg。"
                    "M 码：身高175-185cm，体重55-65kg。"
                    "L 码：身高180-190cm，体重65-78kg。"
                ),
                "allowed_user_ids": ["u-admin"],
            },
        )
        self.client.post(
            "/ai/documents/index",
            json={
                "document_id": "doc-clothing-color",
                "knowledge_base_id": "kb-hr",
                "filename": "颜色选择.txt",
                "content": "肤色偏白：适合浅蓝、米白、浅灰、浅粉、雾霾蓝等低饱和度色系，整体更清爽显气色。",
                "allowed_user_ids": ["u-admin"],
            },
        )

        response = self.client.post(
            "/ai/agent/run",
            json={
                "user_id": "u-admin",
                "session_id": "session-clothing-1",
                "question": "我180，比较瘦，偏白，帮我推荐衣服的颜色以及尺码",
                "knowledge_base_ids": ["kb-hr"],
            },
        )
        answer = response.json()["answer"]

        self.assertEqual(200, response.status_code)
        self.assertIn("M 码", answer)
        self.assertIn("颜色建议", answer)
        self.assertIn("浅蓝", answer)
        self.assertNotIn("结论：根据已召回的文档", answer)

    def test_index_filters_pdf_garbage_text(self):
        chunks = split_text("QE\x14\x00QE\x14\x00QE\x14\x00\ufffd\ufffd\ufffd\n员工请病假需要提交请假申请和医疗证明。")

        self.assertEqual(["员工请病假需要提交请假申请和医疗证明。"], chunks)

    def test_fallback_answers_sick_leave_question_without_garbage(self):
        self.client.post(
            "/ai/documents/index",
            json={
                "document_id": "doc-sick-leave",
                "knowledge_base_id": "kb-hr",
                "filename": "attendance-policy.pdf",
                "content": "QE\x14\x00QE\x14\x00QE\x14\x00\ufffd\ufffd\n员工请病假需要提交请假申请和医疗证明，经公司审批后方可请假。病假期间工资按公司制度计算。",
                "allowed_user_ids": ["u-admin"],
            },
        )

        response = self.client.post(
            "/ai/agent/run",
            json={
                "user_id": "u-admin",
                "session_id": "session-sick-leave",
                "question": "病假怎么请",
                "knowledge_base_ids": ["kb-hr"],
            },
        )
        answer = response.json()["answer"]

        self.assertEqual(200, response.status_code)
        self.assertIn("病假", answer)
        self.assertIn("请假申请", answer)
        self.assertNotIn("QE", answer)
        self.assertNotIn("\ufffd", answer)

    def test_agent_answers_amount_question_after_rerank(self):
        self.client.post(
            "/ai/documents/index",
            json={
                "document_id": "doc-annual-leave",
                "knowledge_base_id": "kb-hr",
                "filename": "attendance-policy.txt",
                "content": (
                    "发生5次及以下可通过PMS平台提交补卡申请，经部门审批后作正常出勤处理。"
                    "出差员工因公出差1天及以上须通过财务共享系统发起出差申请。"
                    "员工连续工作满1年不满10年的，年休假5天；满10年不满20年的，年休假10天；满20年的，年休假15天。"
                ),
                "allowed_user_ids": ["u-admin"],
            },
        )

        response = self.client.post(
            "/ai/agent/run",
            json={
                "user_id": "u-admin",
                "session_id": "session-annual-leave",
                "question": "年假有多少天",
                "knowledge_base_ids": ["kb-hr"],
            },
        )
        answer = response.json()["answer"]

        self.assertEqual(200, response.status_code)
        self.assertIn("年休假5天", answer)
        self.assertIn("年休假10天", answer)
        self.assertNotIn("补卡申请", answer.split("\n", 1)[0])

    def test_generate_answer_uses_model_when_api_key_is_configured(self):
        class FakeResponse:
            def raise_for_status(self):
                return None

            def json(self):
                return {"choices": [{"message": {"content": "工作两年可享受5天年休假。"}}]}

        class FakeClient:
            def __init__(self, timeout):
                self.timeout = timeout

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return None

            async def post(self, *args, **kwargs):
                return FakeResponse()

        main.MODEL_API_KEY = "test-key"
        try:
            with patch("app.main.httpx.AsyncClient", FakeClient):
                import asyncio

                answer = asyncio.run(
                    generate_answer(
                        "工作两年，年假有多少天",
                        [{"filename": "policy.pdf", "text": "员工累计工作已满1年不满10年的，年休假5天。"}],
                        [],
                    )
                )
        finally:
            main.MODEL_API_KEY = ""

        self.assertEqual("工作两年可享受5天年休假。", answer)


if __name__ == "__main__":
    unittest.main()
