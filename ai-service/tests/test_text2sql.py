import unittest
from datetime import date, timedelta

from app.text2sql import (
    LockedQueryConstraints,
    PermissionDenied,
    PlanValidationError,
    QueryPlan,
    apply_policy,
    compile_query,
    create_query_plan,
    extract_locked_constraints,
    fallback_query_plan,
    load_semantic_registry,
    merge_locked_constraints,
    preflight_permission,
    retrieve_domains,
    validate_query_plan,
)


class Text2SqlCoreTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.registry = load_semantic_registry()
        self.admin = {"id": "u-admin", "username": "admin", "is_admin": True}
        self.user1 = {"id": "u-user1", "username": "user1", "is_admin": False}

    def merge_locked(self, question: str, plan: QueryPlan) -> QueryPlan:
        constraints = extract_locked_constraints(question, [plan.domain], self.registry)
        return merge_locked_constraints(question, plan, constraints, self.registry)

    def test_registry_contains_six_valid_domains(self):
        self.assertEqual(
            {"attendance", "employee_worklog", "knowledge_base", "document", "chat_session", "chat_message"},
            set(self.registry.domains),
        )

    def test_unknown_sensitive_field_is_rejected(self):
        with self.assertRaises(PlanValidationError) as caught:
            validate_query_plan(
                {"domain": "attendance", "dimensions": ["password_hash"], "limit": 20},
                self.registry,
                ["attendance"],
            )
        self.assertTrue(any("unknown_field" in issue["code"] for issue in caught.exception.issues))

    def test_invalid_enum_and_operator_types_are_rejected(self):
        with self.assertRaises(PlanValidationError):
            validate_query_plan(
                {
                    "domain": "attendance",
                    "dimensions": ["username"],
                    "filters": [{"field": "status", "operator": "eq", "value": "DROP_TABLE"}],
                },
                self.registry,
                ["attendance"],
            )
        with self.assertRaises(PlanValidationError):
            validate_query_plan(
                {
                    "domain": "attendance",
                    "dimensions": ["username"],
                    "filters": [{"field": "status", "operator": "contains", "value": "ABS"}],
                },
                self.registry,
                ["attendance"],
            )

    def test_rule_planner_and_compiler_cover_all_domains(self):
        questions = {
            "attendance": "查找缺卡人员",
            "employee_worklog": "查看最近的工作日志",
            "knowledge_base": "当前有哪些知识库",
            "document": "目前有多少文档和多少切片",
            "chat_session": "查看最近会话",
            "chat_message": "系统总共有多少轮对话",
        }
        for expected_domain, question in questions.items():
            with self.subTest(domain=expected_domain):
                candidates = retrieve_domains(question, self.registry)
                self.assertEqual(expected_domain, candidates[0])
                plan = fallback_query_plan(question, candidates, self.registry)
                self.assertIsNotNone(plan)
                validated = validate_query_plan(plan, self.registry, candidates)
                secured, scope = apply_policy(question, validated, self.registry, self.admin, ["kb-hr", "kb-tech"])
                compiled = compile_query(secured, self.registry, scope)
                self.assertTrue(compiled.sql.startswith("SELECT "))
                self.assertIn(f"FROM {self.registry.domains[expected_domain].source}", compiled.sql)
                self.assertLessEqual(secured.limit, 50)

    def test_absence_aliases_produce_the_same_query_plan(self):
        plans = []
        for alias in ("缺卡", "未打卡", "漏打卡", "忘记打卡"):
            question = f"查找{alias}人员"
            candidates = retrieve_domains(question, self.registry)
            base = fallback_query_plan(question, candidates, self.registry)
            plans.append(merge_locked_constraints(question, base, extract_locked_constraints(question, candidates, self.registry), self.registry))
        filters = [[item.model_dump() for item in plan.filters] for plan in plans if plan]
        self.assertEqual(filters[0], filters[1])
        self.assertEqual(filters[0], filters[2])
        self.assertEqual(filters[0], filters[3])

    def test_locked_constraints_fill_missing_plan_filters(self):
        unfiltered = QueryPlan(domain="attendance", dimensions=["username", "attendance_date"])
        normalized = self.merge_locked("查找缺卡人员", unfiltered)
        self.assertEqual(
            [{"field": "status", "operator": "eq", "value": "ABSENT"}],
            [item.model_dump() for item in normalized.filters],
        )

        message_plan = QueryPlan(domain="chat_message", metrics=["record_count"])
        message_normalized = self.merge_locked("系统有多少轮对话", message_plan)
        self.assertEqual("role", message_normalized.filters[0].field)
        self.assertEqual("user", message_normalized.filters[0].value)

    def test_worklog_date_expressions_are_extracted_before_planning(self):
        base = QueryPlan(domain="employee_worklog", dimensions=["username", "log_date", "work_summary"])
        today = date.today()

        explicit = self.merge_locked("查询我6.19的工作日志", base)
        self.assertEqual(
            [("eq", f"{today.year}-06-19")],
            [(item.operator, item.value) for item in explicit.filters if item.field == "log_date"],
        )

        date_range = self.merge_locked("查询user2从6.17到6.22的工作日志", base)
        self.assertEqual(
            [("gte", f"{today.year}-06-17"), ("lte", f"{today.year}-06-22")],
            [(item.operator, item.value) for item in date_range.filters if item.field == "log_date"],
        )

        chinese_range = self.merge_locked("查询6月17日至6月22日的工作日志", base)
        self.assertEqual(
            [("gte", f"{today.year}-06-17"), ("lte", f"{today.year}-06-22")],
            [(item.operator, item.value) for item in chinese_range.filters if item.field == "log_date"],
        )

        for separator in ("-", "—", "–", "~", "～"):
            normalized = self.merge_locked(f"查询user2 6.17{separator}6.22的工作日志", base)
            self.assertEqual(
                [("gte", f"{today.year}-06-17"), ("lte", f"{today.year}-06-22")],
                [(item.operator, item.value) for item in normalized.filters if item.field == "log_date"],
            )

        recent = self.merge_locked("列出我近五天的工作日志", base)
        self.assertEqual(
            [("gte", (today - timedelta(days=4)).isoformat())],
            [(item.operator, item.value) for item in recent.filters if item.field == "log_date"],
        )

        monday = today - timedelta(days=today.weekday())
        last_week = self.merge_locked("列出我上周的工作日志", base)
        self.assertEqual(
            [("gte", (monday - timedelta(days=7)).isoformat()), ("lt", monday.isoformat())],
            [(item.operator, item.value) for item in last_week.filters if item.field == "log_date"],
        )

    def test_non_iso_model_date_is_rejected_before_sql_compilation(self):
        with self.assertRaises(PlanValidationError) as caught:
            validate_query_plan(
                {
                    "domain": "employee_worklog",
                    "dimensions": ["username", "log_date", "work_summary"],
                    "filters": [{"field": "log_date", "operator": "eq", "value": "6.19"}],
                },
                self.registry,
                ["employee_worklog"],
            )
        self.assertTrue(any("invalid_date_value" in issue["code"] for issue in caught.exception.issues))

    def test_policy_rejects_other_employee_and_injects_self_scope(self):
        plan = QueryPlan(domain="attendance", dimensions=["username", "status"])
        with self.assertRaises(PermissionDenied):
            apply_policy("查询user2的考勤", plan, self.registry, self.user1, [])

        secured, scope = apply_policy("查询我的考勤", plan, self.registry, self.user1, [])
        compiled = compile_query(secured, self.registry, scope)
        self.assertIn("user_id = %s", compiled.sql)
        self.assertEqual(("u-user1",), compiled.params)

    def test_permission_preflight_rejects_before_planning(self):
        with self.assertRaises(PermissionDenied):
            preflight_permission("查询user2的考勤", ["attendance"], self.registry, self.user1, [])

    async def test_model_plan_gets_one_sanitized_repair(self):
        calls = []

        async def fake_complete(messages):
            calls.append(messages)
            if len(calls) == 1:
                return {"domain": "attendance", "dimensions": ["password_hash"]}
            return {"domain": "attendance", "dimensions": ["username", "status"], "limit": 20}

        plan, planner = await create_query_plan(
            "查询考勤",
            self.registry,
            ["attendance"],
            fake_complete,
            max_repairs=1,
        )
        self.assertEqual("model", planner)
        self.assertEqual(["username", "status"], plan.dimensions)
        self.assertEqual(2, len(calls))
        repair_payload = calls[1][-1]["content"]
        self.assertIn("unknown_field:password_hash", repair_payload)
        self.assertNotIn("SELECT", repair_payload)

    async def test_locked_entities_are_sent_before_planning_and_override_model_filters(self):
        question = "查询user5 6.17-6.22的工作日志"
        candidates = ["employee_worklog"]
        locked = extract_locked_constraints(question, candidates, self.registry)
        calls = []

        async def conflicting_model(messages):
            calls.append(messages)
            return {
                "domain": "employee_worklog",
                "dimensions": ["username", "log_date", "work_summary"],
                "filters": [
                    {"field": "username", "operator": "eq", "value": "user1"},
                    {"field": "log_date", "operator": "eq", "value": "2026-06-17"},
                ],
                "order_by": [{"field": "log_date", "direction": "desc"}],
                "limit": 20,
            }

        plan, planner = await create_query_plan(
            question,
            self.registry,
            candidates,
            conflicting_model,
            locked_constraints=locked,
        )

        self.assertEqual("model", planner)
        prompt_payload = calls[0][-1]["content"]
        self.assertIn("locked_constraints", prompt_payload)
        self.assertIn("user5", prompt_payload)
        self.assertEqual(
            [
                ("username", "eq", "user5"),
                ("log_date", "gte", f"{date.today().year}-06-17"),
                ("log_date", "lte", f"{date.today().year}-06-22"),
            ],
            [(item.field, item.operator, item.value) for item in plan.filters],
        )

    def test_locked_enum_and_username_entities_are_domain_specific(self):
        constraints = extract_locked_constraints(
            "查询user3的缺卡记录",
            ["attendance", "employee_worklog"],
            self.registry,
        )
        attendance = constraints["attendance"]
        worklog = constraints["employee_worklog"]
        self.assertIsInstance(attendance, LockedQueryConstraints)
        self.assertIn(("status", "ABSENT"), [(item.field, item.value) for item in attendance.filters])
        self.assertIn(("username", "user3"), [(item.field, item.value) for item in attendance.filters])
        self.assertNotIn("status", [item.field for item in worklog.filters])

    async def test_missing_model_uses_rule_query_plan(self):
        candidates = retrieve_domains("统计文档数量", self.registry)
        plan, planner = await create_query_plan("统计文档数量", self.registry, candidates, None)
        self.assertEqual("fallback", planner)
        self.assertEqual("document", plan.domain)
        self.assertIn("record_count", plan.metrics)

    async def test_model_network_failure_falls_back_without_repair(self):
        calls = 0

        async def unavailable_model(_messages):
            nonlocal calls
            calls += 1
            raise RuntimeError("network unavailable")

        plan, planner = await create_query_plan(
            "列出我近五天的工作日志",
            self.registry,
            ["employee_worklog"],
            unavailable_model,
            max_repairs=1,
        )
        self.assertEqual(1, calls)
        self.assertEqual("fallback", planner)
        self.assertEqual("employee_worklog", plan.domain)
        self.assertTrue(any(item.field == "log_date" for item in plan.filters))


if __name__ == "__main__":
    unittest.main()
