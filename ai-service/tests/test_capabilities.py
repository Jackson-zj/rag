import unittest
from unittest.mock import AsyncMock, patch

import httpx
from fastapi.testclient import TestClient

import app.agent as agent
import app.main as main
from app.capabilities import (
    CapabilityDispatcher,
    CapabilityRegistry,
    build_plan_with_model,
    enabled_capabilities,
    load_capability_registry,
    select_capabilities_with_model,
    validate_arguments,
)
from app.main import CHUNKS, MEMORY, app


class CapabilityRegistryTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.registry = load_capability_registry()

    def test_registry_loads_three_unique_read_only_capabilities(self):
        self.assertEqual(1, self.registry.version)
        self.assertEqual(
            {"rag.search.v1", "sql.query.v1", "document.status.v1"},
            {item.id for item in self.registry.capabilities},
        )
        self.assertTrue(all(item.side_effect == "read" for item in self.registry.capabilities))

    def test_duplicate_ids_and_unsafe_http_paths_are_rejected(self):
        payload = self.registry.model_dump()
        payload["capabilities"].append(dict(payload["capabilities"][0]))
        with self.assertRaises(ValueError):
            CapabilityRegistry.model_validate(payload)

        payload = self.registry.model_dump()
        payload["capabilities"][2]["executor"]["path"] = "https://attacker.invalid/doc"
        with self.assertRaises(ValueError):
            CapabilityRegistry.model_validate(payload)

    def test_java_capability_requires_both_runtime_settings(self):
        without_java = enabled_capabilities(self.registry, java_base_url="", internal_token="")
        with_java = enabled_capabilities(self.registry, java_base_url="http://backend-java:8080", internal_token="secret")
        self.assertNotIn("document.status.v1", {item.id for item in without_java})
        self.assertIn("document.status.v1", {item.id for item in with_java})

    def test_argument_validation_rejects_reserved_and_unknown_fields(self):
        rag = self.registry.by_id()["rag.search.v1"]
        validate_arguments(rag.input_schema, {"query": "leave policy", "top_k": 3})
        with self.assertRaises(ValueError):
            validate_arguments(rag.input_schema, {"query": "leave", "user_id": "u-admin"})
        with self.assertRaises(ValueError):
            validate_arguments(rag.input_schema, {"query": "leave", "top_k": 99})

    async def test_two_stage_planning_validates_selection_and_arguments(self):
        capabilities = enabled_capabilities(self.registry)

        async def select(_messages):
            return {"mode": "tools", "capability_ids": ["rag.search.v1"], "summary": "search policy"}

        selection = await select_capabilities_with_model("What is the leave policy?", capabilities, select)
        self.assertEqual(["rag.search.v1"], selection.capability_ids)

        async def plan(_messages):
            return {
                "steps": [
                    {"step_id": "step_1", "capability_id": "rag.search.v1", "arguments": {"query": "leave policy", "top_k": 5}}
                ]
            }

        execution_plan = await build_plan_with_model(
            "What is the leave policy?",
            [self.registry.by_id()["rag.search.v1"]],
            plan,
        )
        self.assertEqual("rag.search.v1", execution_plan.steps[0].capability_id)

        async def unsafe_plan(_messages):
            return {
                "steps": [
                    {"step_id": "step_1", "capability_id": "rag.search.v1", "arguments": {"query": "leave", "token": "bad"}}
                ]
            }

        with self.assertRaises(ValueError):
            await build_plan_with_model(
                "What is the leave policy?",
                [self.registry.by_id()["rag.search.v1"]],
                unsafe_plan,
            )

    async def test_http_executor_uses_allowlisted_service_and_injected_identity(self):
        definition = self.registry.by_id()["document.status.v1"]
        dispatcher = CapabilityDispatcher(
            handlers={},
            services={"backend-java": "http://backend-java:8080"},
            internal_token="service-secret",
        )
        response = httpx.Response(
            200,
            json={"id": "doc-1", "status": "READY", "chunkCount": 3},
            request=httpx.Request("GET", "http://backend-java:8080/internal/agent/documents/doc-1"),
        )
        get = AsyncMock(return_value=response)
        with patch("app.capabilities.httpx.AsyncClient.get", new=get):
            result = await dispatcher.execute(definition, {"document_id": "doc-1"}, {"user_id": "u-user"})
        self.assertEqual("ok", result.status)
        self.assertEqual("READY", result.data["status"])
        called_url = get.await_args.args[0]
        headers = get.await_args.kwargs["headers"]
        self.assertEqual("http://backend-java:8080/internal/agent/documents/doc-1", called_url)
        self.assertEqual("service-secret", headers["X-Agent-Service-Token"])
        self.assertEqual("u-user", headers["X-Acting-User-Id"])


class CapabilityAgentApiTest(unittest.TestCase):
    def setUp(self):
        CHUNKS.clear()
        MEMORY.clear()
        self.client = TestClient(app)

    def tearDown(self):
        main.MODEL_API_KEY = ""

    def test_public_capability_endpoint_hides_executor_configuration(self):
        with patch.object(agent, "JAVA_TOOL_BASE_URL", ""), patch.object(agent, "AGENT_INTERNAL_TOKEN", ""):
            response = self.client.get("/ai/capabilities")
        self.assertEqual(200, response.status_code)
        body = response.json()
        self.assertEqual({"rag.search.v1", "sql.query.v1"}, {item["id"] for item in body["capabilities"]})
        self.assertTrue(all("executor" not in item for item in body["capabilities"]))

    def test_model_driven_rag_plan_is_exposed_without_breaking_existing_contract(self):
        self.client.post(
            "/ai/documents/index",
            json={
                "document_id": "doc-capability-1",
                "knowledge_base_id": "kb-hr",
                "filename": "leave-policy.txt",
                "content": "Annual leave requests require manager approval.",
                "allowed_user_ids": ["u-admin"],
            },
        )
        main.MODEL_API_KEY = "test-key"
        responses = iter(
            [
                {"mode": "tools", "capability_ids": ["rag.search.v1"], "summary": "Search the policy knowledge base."},
                {
                    "steps": [
                        {
                            "step_id": "step_1",
                            "capability_id": "rag.search.v1",
                            "arguments": {"query": "annual leave approval", "top_k": 5},
                        }
                    ]
                },
                {"decision": "complete", "summary": "The retrieved passage is sufficient."},
            ]
        )

        async def fake_json(**_kwargs):
            return next(responses)

        async def fake_text(**_kwargs):
            return "Annual leave requests require manager approval."

        with patch("app.model_client.complete_json", new=fake_json), patch(
            "app.model_client.complete_text", new=fake_text
        ):
            response = self.client.post(
                "/ai/agent/run",
                json={
                    "user_id": "u-admin",
                    "session_id": "session-capability-1",
                    "question": "How are annual leave requests approved?",
                    "knowledge_base_ids": ["kb-hr"],
                },
            )
        body = response.json()
        self.assertEqual(200, response.status_code)
        self.assertEqual("model", body["planner_mode"])
        self.assertEqual("rag", body["route"])
        self.assertEqual(["rag.search.v1"], body["selected_capabilities"])
        self.assertEqual("rag.search.v1", body["plan"][0]["capability_id"])
        self.assertEqual("rag.search.v1", body["tool_calls"][0]["name"])
        self.assertIn("manager approval", body["answer"])

    def test_duplicate_execution_is_suppressed_without_consuming_budget(self):
        state = {
            "question": "policy",
            "user_id": "u-admin",
            "session_id": "s-duplicate",
            "knowledge_base_ids": ["kb-hr"],
            "tool_calls": [],
            "tool_results": [],
            "capability_results": [],
            "executed_capability_keys": [],
            "execution_count": 0,
            "capability_plan": [
                {"step_id": "step_1", "capability_id": "rag.search.v1", "arguments": {"query": "policy", "top_k": 1}}
            ],
        }

        async def run_twice():
            await agent.execute_capability_plan_node(state)
            await agent.execute_capability_plan_node(state)

        import asyncio

        asyncio.run(run_twice())
        self.assertEqual(1, state["execution_count"])
        self.assertEqual("error", state["capability_results"][-1]["status"])
        self.assertIn("重复", state["capability_results"][-1]["summary"])
