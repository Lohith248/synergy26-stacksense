"""E7 / D14: lossless input coercion. Only integer-valued floats for integer fields and a numeric availability equal to
an enum value are accepted (with an assumptions line and an INPUT_COERCED info warning). Every other notation stays an
error: the statement (p4) says enum values are lower-case strings exactly as written."""
import copy
import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

from engine.load import loads  # noqa: E402
from engine.run import evaluate  # noqa: E402
from engine.validate import validate  # noqa: E402
from check_contract import check  # noqa: E402

with open(os.path.join(ROOT, "scenarios", "stacksense_public_scenarios.json"), encoding="utf-8") as f:
    PUBLIC = json.load(f)


def P(i, **edits):
    s = copy.deepcopy(PUBLIC[i - 1])
    for path, v in edits.items():
        d = s
        parts = path.split("__")
        for p in parts[:-1]:
            d = d[p]
        d[parts[-1]] = v
    return s


def coerced(out):
    return [w for w in out["warnings"] if w["code"] == "INPUT_COERCED"]


def errs(out):
    return {e["field"]: e["message"] for e in out["validation_errors"]}


class Accepted(unittest.TestCase):
    def test_integer_valued_float_gives_stack_assumption_and_warning(self):
        base = evaluate(P(2))
        out = evaluate(P(2, scale__users_12_months=float(PUBLIC[1]["scale"]["users_12_months"])))
        self.assertIn(out["status"], ("ok", "ok_with_warnings"))
        self.assertIsNotNone(out["stack"])
        self.assertEqual(check(out), [])
        w = coerced(out)
        self.assertEqual(len(w), 1)
        self.assertEqual(w[0]["severity"], "info")
        self.assertEqual(w[0]["fields"], ["scale.users_12_months"])
        self.assertTrue(any(a.startswith("scale.users_12_months:") and "integer-valued" in a for a in out["assumptions"]))
        # the recommendation itself is the integer's recommendation
        self.assertEqual(out["stack"], base["stack"])
        self.assertEqual(out["estimated_monthly_cost_usd"], base["estimated_monthly_cost_usd"])

    def test_every_integer_kind(self):
        # int, xint (extra), opt_int, prio
        out = evaluate(P(2, team__size=3.0, scale__peak_rps=50.0, requirements__p95_latency_ms=300.0,
                         priorities__cost=4.0, timeline__mvp_weeks=12.0))
        self.assertIsNotNone(out["stack"], out["validation_errors"])
        self.assertEqual(sorted(coerced(out)[0]["fields"]),
                         sorted(["team.size", "scale.peak_rps", "requirements.p95_latency_ms", "priorities.cost",
                                 "timeline.mvp_weeks"]))

    def test_exponent_notation_is_an_integer_valued_float(self):
        text = json.dumps(P(2, scale__users_12_months=0)).replace('"users_12_months": 0', '"users_12_months": 3e4')
        data, err = loads(text)
        self.assertIsNone(err)
        out = evaluate(data)
        self.assertIsNotNone(out["stack"])
        self.assertEqual(len(coerced(out)), 1)

    def test_numeric_availability_equal_to_enum_value(self):
        for num, text in ((99.9, "99.9"), (99.95, "99.95"), (99.99, "99.99"), (99, "99"), (99.0, "99")):
            with self.subTest(num=num):
                out = evaluate(P(2, requirements__availability=num))
                self.assertIsNotNone(out["stack"], out["validation_errors"])
                self.assertEqual(check(out), [])
                self.assertEqual(coerced(out)[0]["fields"], ["requirements.availability"])
                self.assertTrue(any(a.startswith("requirements.availability:") and repr(text) in a
                                    for a in out["assumptions"]))
                string_out = evaluate(P(2, requirements__availability=text))
                self.assertEqual(out["stack"], string_out["stack"])
                self.assertEqual(coerced(string_out), [])

    def test_warning_follows_the_existing_schema(self):
        out = evaluate(P(2, requirements__availability=99.9, team__size=3.0))
        w = coerced(out)[0]
        self.assertEqual(list(w), ["code", "severity", "fields", "message"])
        self.assertEqual(w["fields"], ["team.size", "requirements.availability"])  # schema order, not input order

    def test_no_coercion_no_note(self):
        for i in range(1, 7):
            out = evaluate(P(i))
            self.assertEqual(coerced(out), [], i)
            self.assertFalse(any("no value changed" in a for a in out["assumptions"]), i)


class StillRejected(unittest.TestCase):
    def invalid(self, field, **edit):
        out = evaluate(P(2, **edit))
        self.assertEqual(out["status"], "invalid_input", edit)
        self.assertIn(field, errs(out), edit)
        self.assertEqual(coerced(out), [], edit)
        return out

    def test_fractional_float_for_integer(self):
        self.invalid("team.size", team__size=2.5)
        self.invalid("scale.users_12_months", scale__users_12_months=30000.5)
        self.invalid("priorities.cost", priorities__cost=3.5)

    def test_out_of_range_after_coercion(self):
        self.invalid("priorities.cost", priorities__cost=7.0)
        self.invalid("team.size", team__size=0.0)
        out = self.invalid("scale.users_at_launch", scale__users_at_launch=-5.0)
        self.assertIn("-5.0", errs(out)["scale.users_at_launch"])

    def test_strings_as_numbers(self):
        self.invalid("team.size", team__size="3")
        self.invalid("scale.users_12_months", scale__users_12_months="150")
        self.invalid("budget.monthly_infra_usd", budget__monthly_infra_usd="150")
        self.invalid("requirements.p95_latency_ms", requirements__p95_latency_ms="300")
        self.invalid("priorities.cost", priorities__cost="3")

    def test_booleans_are_not_numbers(self):
        self.invalid("team.size", team__size=True)
        self.invalid("requirements.availability", requirements__availability=True)
        self.invalid("requirements.availability", requirements__availability=False)
        self.invalid("requirements.realtime", requirements__realtime="true")
        self.invalid("requirements.payments", requirements__payments=1)

    def test_availability_numbers_that_equal_no_enum_value(self):
        for v in (99.5, 100, 99.999, 0, 98.9):
            with self.subTest(v=v):
                self.invalid("requirements.availability", requirements__availability=v)

    def test_availability_message_says_what_is_accepted(self):
        m = errs(evaluate(P(2, requirements__availability=99.5)))["requirements.availability"]
        for token in ("'99'", "'99.9'", "'99.95'", "'99.99'", "number 99.5", "string", "equals one of"):
            self.assertIn(token, m)
        self.assertNotIn("(got 99.5)", m)

    def test_case_and_unknown_enums(self):
        self.invalid("requirements.auth", requirements__auth="Email_Password")
        self.invalid("project.type", project__type="SaaS_B2B")
        self.invalid("infrastructure.cloud_preference", infrastructure__cloud_preference="AWS")
        self.invalid("infrastructure.deployment_model", infrastructure__deployment_model="cloud")
        self.invalid("requirements.availability", requirements__availability="99.9 ")
        self.invalid("requirements.availability", requirements__availability="99.90")
        self.invalid("scale.workload", scale__workload=1)

    def test_lists_of_wrong_type(self):
        self.invalid("compliance", compliance=[1])
        self.invalid("project.platforms", project__platforms=["Web", "Android"])
        self.invalid("compliance", compliance=["DPDP"])
        self.invalid("team.languages", team__languages=[1, 2])

    def test_float_for_non_integer_enum_and_bool_fields_is_not_coerced(self):
        self.invalid("scale.traffic_pattern", scale__traffic_pattern=1.0)
        self.invalid("requirements.realtime", requirements__realtime=1.0)
        self.invalid("requirements.auth", requirements__auth=99.9)

    def test_huge_floats(self):
        self.invalid("scale.users_12_months", scale__users_12_months=1e300)
        self.invalid("scale.users_12_months", scale__users_12_months=float(2 ** 60))

    def test_e2_screenshot_case_stays_invalid_input(self):
        with open(os.path.join(ROOT, "scenarios", "edge_cases", "E2_invalid_values.json"), encoding="utf-8") as f:
            out = evaluate(json.load(f))
        self.assertEqual(out["status"], "invalid_input")
        self.assertIsNone(out["stack"])
        self.assertEqual(coerced(out), [])


class Deterministic(unittest.TestCase):
    def test_pure_function_of_the_input(self):
        s = P(3, scale__users_12_months=20000.0, requirements__availability=99.95, priorities__security=5.0)
        before = copy.deepcopy(s)
        a, b = evaluate(s), evaluate(copy.deepcopy(s))
        self.assertEqual(json.dumps(a), json.dumps(b))
        self.assertEqual(s, before)  # the caller's object is never mutated
        self.assertEqual(validate(s)[2], validate(copy.deepcopy(s))[2])

    def test_key_order_does_not_change_output(self):
        s = P(3, scale__users_12_months=20000.0, requirements__availability=99.95)
        rev = json.loads(json.dumps(s))
        rev["requirements"] = dict(reversed(list(rev["requirements"].items())))
        rev["scale"] = dict(reversed(list(rev["scale"].items())))
        self.assertEqual(json.dumps(evaluate(s)), json.dumps(evaluate(rev)))

    def test_coerced_equals_native_except_for_the_note(self):
        native = evaluate(P(3))
        c = evaluate(P(3, scale__users_12_months=float(PUBLIC[2]["scale"]["users_12_months"]),
                        requirements__availability=float(PUBLIC[2]["requirements"]["availability"])))
        n_keep = {k: v for k, v in native.items() if k not in ("assumptions", "warnings")}
        c_keep = {k: v for k, v in c.items() if k not in ("assumptions", "warnings")}
        self.assertEqual(n_keep, c_keep)
        self.assertEqual([w for w in c["warnings"] if w["code"] != "INPUT_COERCED"], native["warnings"])


if __name__ == "__main__":
    unittest.main()
