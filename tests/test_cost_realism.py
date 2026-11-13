"""E8 / D17 cost realism: synthetic inputs only, no scenario ids or product titles.
Each rule: at least three project types, one must-not-fire case, and the invariant that the band equals the sum of its printed lines."""
import os
import re
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from engine import costreal  # noqa: E402
from test_round9 import run  # noqa: E402

RANGE = re.compile(r"\$([\d,]+)-([\d,]+)/month")


def lines(out):
    return out["estimated_monthly_cost_usd"]["assumptions"]


def line(out, start):
    return next((l for l in lines(out) if l.startswith(start) or (": " + start) in l[:40]), None)


def amount(text):
    m = RANGE.search(text)
    return int(m.group(1).replace(",", "")), int(m.group(2).replace(",", ""))


def warn(out, code):
    return [w for w in out["warnings"] if w["code"] == code]


def codes(out):
    return [w["code"] for w in out["warnings"]]


def band_is_sum_of_lines(tc, out):
    c = out["estimated_monthly_cost_usd"]
    lo = hi = 0
    for l in c["assumptions"]:
        m = RANGE.search(l)
        if m and "already running" not in l:
            lo, hi = lo + int(m.group(1).replace(",", "")), hi + int(m.group(2).replace(",", ""))
    tc.assertEqual((lo, hi), (c["min"], c["max"]), c["assumptions"])


def mk(typ, desc="", **kw):
    kw.update({"project.type": typ, "project.description": desc})
    return kw


class PeakConcurrency(unittest.TestCase):
    """E8e: a monthly audience gets a stated, lower ratio; the figure never exceeds the total users."""

    def test_monthly_audience_wording_lowers_the_ratio_for_three_types(self):
        for typ, desc, frac in [("content_site", "A magazine with 2,000,000 monthly readers.", 0.02),
                                ("ecommerce", "A shop with about 1,000,000 monthly visitors browsing products.", 0.02),
                                ("social", "A hobby network with 1,000,000 monthly active users.", 0.05)]:
            with self.subTest(typ=typ):
                users = 1_000_000
                out = run(**mk(typ, desc, **{"scale.users_at_launch": 5000, "scale.users_12_months": users,
                                             "scale.peak_concurrent_users": None, "requirements.realtime": typ == "social"}))
                note = next(a for a in out["assumptions"] if a.startswith("scale.peak_concurrent_users"))
                self.assertIn(f"{frac:.0%} of users_12_months", note)
                self.assertIn("planning heuristic", note)
                tier = next(a for a in out["assumptions"] if a.startswith("Scale tier"))
                peak = int(re.search(r"~([\d,]+) peak", tier).group(1).replace(",", ""))
                self.assertEqual(peak, int(users * frac))
                self.assertLessEqual(peak, users)

    def test_no_audience_wording_keeps_ten_percent_and_the_old_note(self):
        out = run(**mk("web_app", "A booking tool for a clinic.", **{"scale.users_12_months": 50000, "scale.peak_concurrent_users": None}))
        self.assertTrue(any(a.startswith("scale.peak_concurrent_users") and "estimated as 10% of users_12_months for sizing only." in a for a in out["assumptions"]))
        self.assertTrue(any("~5,000 peak concurrent" in a for a in out["assumptions"]))

    def test_explicit_peak_is_never_replaced(self):
        out = run(**mk("content_site", "2,000,000 monthly readers.", **{"scale.users_12_months": 2_000_000, "scale.peak_concurrent_users": 90000}))
        self.assertTrue(any("~90,000 peak concurrent" in a for a in out["assumptions"]))
        self.assertFalse(any(a.startswith("scale.peak_concurrent_users absent") for a in out["assumptions"]))

    def test_derived_peak_never_above_users(self):
        for users in (1, 3, 9, 25):
            p, _, _ = costreal.derived_peak(users, {"project.description": "monthly readers", "scale.workload": None}, "content_site")
            self.assertLessEqual(p, users)
            self.assertGreaterEqual(p, 1)


class PerMessageLines(unittest.TestCase):
    """E8d: per-message services scale with users x a stated usage assumption; a dominant line is named when the budget is far below."""

    def test_email_line_scales_with_the_stated_list_for_three_types(self):
        for typ, desc in [("content_site", "Newsletter for writers; the email list will be about {n}."),
                          ("saas_b2b", "Invoicing tool that sends transactional emails; the email list is about {n}."),
                          ("web_app", "A club site with a mailing list of {n} subscribers.")]:
            outs = []
            for n in ("10,000", "100,000"):
                out = run(**mk(typ, desc.format(n=n), **{"budget.monthly_infra_usd": 5000}))
                text = line(out, "E-mail delivery")
                self.assertIsNotNone(text, (typ, lines(out)))
                outs.append(amount(text))
                self.assertIn("planning estimate", text)
                self.assertIn(f"{n} recipients", text)
                band_is_sum_of_lines(self, out)
            self.assertAlmostEqual(outs[1][1] / outs[0][1], 10, delta=0.5)

    def test_email_line_falls_back_to_every_user_and_never_without_the_component(self):
        out = run(**mk("ecommerce", "Shop that sends order confirmation emails.", **{"scale.users_12_months": 4000}))
        self.assertIn("4,000 users (no list size stated", line(out, "E-mail delivery"))
        out = run(**mk("ecommerce", "Shop with a checkout.", **{"scale.users_12_months": 4000}))
        self.assertIsNone(line(out, "E-mail delivery"))
        out = run(**mk("ecommerce", "Shop that sends order confirmation emails.", **{"infrastructure.deployment_model": "on_premise", "infrastructure.cloud_preference": "none"}))
        self.assertIsNone(line(out, "E-mail delivery"))

    def test_budget_far_below_names_the_dominant_line_and_what_to_cut(self):
        for typ in ("marketplace", "fintech", "healthtech"):
            with self.subTest(typ=typ):
                out = run(**mk(typ, "App with phone sign-in.", **{"requirements.auth": "phone_otp", "scale.users_12_months": 3_000_000,
                                                                  "scale.users_at_launch": 100000, "scale.peak_concurrent_users": 30000,
                                                                  "budget.monthly_infra_usd": 0, "infrastructure.data_residency": "india"}))
                w = warn(out, "BUDGET_EXCEEDED")[0]
                self.assertEqual(w["severity"], "critical")
                self.assertIn("Dominant line: ", w["message"])
                self.assertIn("What to cut:", w["message"])
                self.assertIn("Nothing was removed from the stack", w["message"])
                otp = line(out, "Phone OTP")
                self.assertIsNotNone(otp)
                self.assertIn("0.3-1.0 OTP logins/month", otp)  # the stated usage assumption
                band_is_sum_of_lines(self, out)

    def test_dominant_line_not_added_when_the_budget_holds_or_is_only_a_little_short(self):
        out = run(**mk("marketplace", "Small marketplace.", **{"budget.monthly_infra_usd": 5000}))
        self.assertFalse(warn(out, "BUDGET_EXCEEDED"))
        out = run(**mk("marketplace", "Small marketplace.", **{"budget.monthly_infra_usd": 20, "scale.users_12_months": 3000}))
        for w in warn(out, "BUDGET_EXCEEDED"):
            if w["severity"] == "warning":
                self.assertNotIn("Dominant line", w["message"])

    def test_single_line_above_ten_times_the_budget_gets_a_sanity_note(self):
        for typ in ("marketplace", "fintech", "social"):
            with self.subTest(typ=typ):
                out = run(**mk(typ, "App with phone sign-in.", **{"requirements.auth": "phone_otp", "scale.users_12_months": 2_000_000,
                                                                  "scale.users_at_launch": 50000, "scale.peak_concurrent_users": 20000,
                                                                  "budget.monthly_infra_usd": 100, "infrastructure.data_residency": "india"}))
                text = " ".join(w["message"] for w in out["warnings"] if w["code"].startswith("BUDGET"))
                self.assertIn("Sanity check:", text)
                self.assertIn("10x the budget", text)

    def test_no_sanity_note_when_no_single_line_is_that_large(self):
        out = run(**mk("marketplace", "Small marketplace.", **{"budget.monthly_infra_usd": 200, "scale.users_12_months": 3000}))
        self.assertNotIn("Sanity check:", " ".join(w["message"] for w in out["warnings"]))

    def test_llm_token_line_scales_with_users_for_three_types(self):
        for typ in ("ai_ml_product", "saas_b2b", "web_app"):
            with self.subTest(typ=typ):
                cost = []
                for users in (4000, 40000):
                    out = run(**mk(typ, "Assistant that answers from our documents.", **{
                        "requirements.ml_features": "llm_rag", "scale.users_12_months": users, "scale.users_at_launch": 1000,
                        "scale.peak_concurrent_users": 100, "budget.monthly_infra_usd": 50000, "infrastructure.cloud_preference": "aws"}))
                    ml = next(s for s in out["stack"]["supporting"] if s["layer"] == "ml")
                    text = line(out, "ml:")
                    self.assertIn("planning estimate", text)
                    self.assertIn(f"{users:,} users x 5-20 questions", text)
                    cost.append(amount(text)[1])
                    band_is_sum_of_lines(self, out)
                self.assertGreater(cost[1], cost[0] * 5)

    def test_self_hosted_llm_has_no_token_line(self):
        out = run(**mk("ai_ml_product", "Assistant.", **{"requirements.ml_features": "llm_rag", "infrastructure.deployment_model": "air_gapped",
                                                          "infrastructure.cloud_preference": "none", "scale.users_12_months": 4000}))
        text = line(out, "ml:") or ""
        self.assertNotIn("Token basis", text)


class TrainingFloor(unittest.TestCase):
    """E8b: managed training gets a floor from data_volume and no 'budget far above need' remark."""

    def base(self, typ, gb, **kw):
        d = {"requirements.ml_features": "training", "scale.data_volume_gb_12_months": gb, "budget.monthly_infra_usd": 50000,
             "infrastructure.cloud_preference": "aws", "scale.users_12_months": 300, "scale.users_at_launch": 100,
             "scale.peak_concurrent_users": 30, "project.platforms": ["web"]}
        d.update(kw)
        return run(**mk(typ, "Models are trained on our data.", **d))

    def test_floor_for_three_types_and_no_far_above_need(self):
        for typ in ("ai_ml_product", "data_analytics", "saas_b2b"):
            with self.subTest(typ=typ):
                out = self.base(typ, 20000)
                text = line(out, "ml:")
                lo, hi = amount(text)
                self.assertGreaterEqual(lo, round(20000 * costreal.TRAIN_GPU_HOURS_PER_GB[0] * costreal.TRAIN_GPU_RATE))
                self.assertIn("Floor from the stored data", text)
                self.assertIn("planning heuristic", text)
                self.assertNotIn("BUDGET_FAR_ABOVE_NEED", codes(out))
                band_is_sum_of_lines(self, out)

    def test_small_volume_keeps_the_tier_table_and_the_far_above_need_remark(self):
        out = self.base("ai_ml_product", 10)
        self.assertNotIn("Floor from the stored data", line(out, "ml:"))
        self.assertIn("BUDGET_FAR_ABOVE_NEED", codes(out))

    def test_non_training_never_gets_the_floor(self):
        out = self.base("ai_ml_product", 20000, **{"requirements.ml_features": "inference_api"})
        self.assertNotIn("Floor from the stored data", " ".join(lines(out)))
        self.assertIn("BUDGET_FAR_ABOVE_NEED", codes(out))


class OnPremHardware(unittest.TestCase):
    """E8c: on-premises and air-gapped outputs carry an indicative amortised hardware line."""

    def onprem(self, typ, deploy="on_premise", **kw):
        d = {"infrastructure.deployment_model": deploy, "infrastructure.cloud_preference": "none", "budget.monthly_infra_usd": 3000}
        d.update(kw)
        return run(**mk(typ, "An internal system.", **d))

    def test_line_is_labelled_and_positive_for_three_types_and_both_models(self):
        for typ, deploy in [("internal_tool", "on_premise"), ("healthtech", "air_gapped"), ("saas_b2b", "on_premise"), ("ecommerce", "air_gapped")]:
            with self.subTest(typ=typ, deploy=deploy):
                out = self.onprem(typ, deploy)
                text = line(out, "Hardware (indicative")
                self.assertIsNotNone(text, lines(out))
                self.assertIn("indicative, not a quote", text)
                self.assertIn("planning heuristic", text)
                lo, hi = amount(text)
                self.assertGreater(lo, 0)
                self.assertGreater(hi, lo)
                c = out["estimated_monthly_cost_usd"]
                self.assertGreater(c["max"], 0)
                self.assertIn("indicative amortised hardware", out["summary"])
                band_is_sum_of_lines(self, out)

    def test_line_grows_with_scale_and_gpu_and_team(self):
        small = amount(line(self.onprem("internal_tool", **{"scale.users_12_months": 100, "scale.users_at_launch": 50}), "Hardware (indicative"))[1]
        big = amount(line(self.onprem("internal_tool", **{"scale.users_12_months": 400000, "scale.users_at_launch": 100000,
                                                          "scale.peak_concurrent_users": 30000}), "Hardware (indicative"))[1]
        self.assertGreater(big, small * 3)
        plain = amount(line(self.onprem("saas_b2b"), "Hardware (indicative"))[1]
        gpu = amount(line(self.onprem("saas_b2b", **{"requirements.ml_features": "llm_rag"}), "Hardware (indicative"))[1]
        self.assertGreater(gpu, plain)
        t1 = amount(line(self.onprem("saas_b2b", **{"team.size": 2}), "Hardware (indicative"))[1]
        t2 = amount(line(self.onprem("saas_b2b", **{"team.size": 9}), "Hardware (indicative"))[1]
        self.assertGreater(t2, t1)

    def test_hardware_only_excess_is_a_warning_not_a_critical_conflict(self):
        out = self.onprem("internal_tool", **{"budget.monthly_infra_usd": 0})
        w = warn(out, "BUDGET_EXCEEDED")
        self.assertEqual(len(w), 1)
        self.assertEqual(w[0]["severity"], "warning")
        self.assertIn("servers", w[0]["message"])
        self.assertNotIn("critical", [x["severity"] for x in out["warnings"] if x["code"].startswith("BUDGET")])

    def test_no_hardware_line_in_a_managed_cloud_or_vm_deployment(self):
        for deploy in ("managed_cloud", "self_hosted_cloud_vm"):
            with self.subTest(deploy=deploy):
                out = run(**mk("saas_b2b", "A system.", **{"infrastructure.deployment_model": deploy}))
                self.assertIsNone(line(out, "Hardware (indicative"))


class IotAndStoredData(unittest.TestCase):
    """E8a: device counts size ingestion; write-heavy IoT readings are database rows; self-run and existing databases are not free."""

    def iot(self, desc, typ="iot", **kw):
        d = {"scale.workload": "write_heavy", "scale.data_volume_gb_12_months": 3000, "budget.monthly_infra_usd": 20000,
             "scale.users_12_months": 800, "scale.users_at_launch": 200, "scale.peak_concurrent_users": 100, "infrastructure.cloud_preference": "aws"}
        d.update(kw)
        return run(**mk(typ, desc, **d))

    def test_device_count_without_interval_sizes_ingestion_for_three_types(self):
        for typ in ("iot", "data_analytics", "other"):
            with self.subTest(typ=typ):
                small = self.iot("2,000 sensors send readings to the cloud.", typ)
                big = self.iot("200,000 sensors send readings to the cloud.", typ)
                a, b = (amount(line(o, "other: Device ingestion")) for o in (small, big))
                self.assertGreater(b[1], a[1] * 50)
                text = line(big, "other: Device ingestion")
                self.assertIn("no reporting interval", " ".join(s["justification"] for s in big["stack"]["supporting"] if "Device ingestion" in s["choice"]))
                self.assertIn("million messages", text)
                band_is_sum_of_lines(self, big)

    def test_azure_iot_hub_is_priced_as_a_planning_estimate(self):
        out = self.iot("50,000 sensors report every 30 seconds.", **{"infrastructure.cloud_preference": "azure"})
        text = line(out, "other: Device ingestion")
        self.assertIn("planning estimate", text)
        self.assertGreater(amount(text)[0], 0)

    def test_self_run_broker_scales_with_message_rate(self):
        small = self.iot("100 sensors report every 60 seconds.", **{"infrastructure.cloud_preference": "gcp"})
        big = self.iot("500,000 sensors report every 10 seconds.", **{"infrastructure.cloud_preference": "gcp"})
        self.assertGreater(amount(line(big, "other: Device ingestion"))[1], amount(line(small, "other: Device ingestion"))[1] * 5)

    def test_write_heavy_iot_with_object_storage_costs_rows_at_database_rates(self):
        for typ in ("iot",):
            out = self.iot("Sensors send readings and photos.", typ, **{"requirements.file_media_storage": True})
            text = line(out, "Stored data")
            self.assertIn("append-only rows in the managed database", text)
            self.assertIn("planning heuristic", text)
            lo, hi = amount(text)
            self.assertGreater(hi, 3000 * 0.5 * 0.25)
            band_is_sum_of_lines(self, out)

    def test_other_write_heavy_types_with_object_storage_keep_object_rates(self):
        for typ in ("data_analytics", "social", "web_app"):
            with self.subTest(typ=typ):
                out = self.iot("Users upload photos and files.", typ, **{"requirements.file_media_storage": True})
                text = line(out, "Stored data")
                self.assertNotIn("append-only rows", text)
                self.assertIn("object storage", text)

    def test_self_run_database_disk_and_existing_database_are_named(self):
        out = run(**mk("saas_b2b", "A system.", **{"infrastructure.deployment_model": "self_hosted_cloud_vm", "scale.data_volume_gb_12_months": 500,
                                                  "infrastructure.cloud_preference": "aws"}))
        text = line(out, "Stored data")
        self.assertIsNotNone(text, lines(out))
        self.assertIn("planning estimate", text)
        out = run(**mk("iot", "Sensors send readings.", **{"infrastructure.existing_systems": ["MongoDB 6 replica set (must stay)"],
                                                          "scale.data_volume_gb_12_months": 3000}))
        text = line(out, "Stored data")
        self.assertIn("grows inside the existing database", text)
        self.assertNotRegex(text, RANGE)


class Invariants(unittest.TestCase):
    def test_band_equals_lines_across_rules(self):
        cases = [mk("content_site", "Newsletter; email list about 5,000.", **{"scale.users_12_months": 100000}),
                 mk("ai_ml_product", "Models.", **{"requirements.ml_features": "training", "scale.data_volume_gb_12_months": 2000}),
                 mk("iot", "800 sensors every 60 s.", **{"scale.workload": "write_heavy", "scale.data_volume_gb_12_months": 900}),
                 mk("internal_tool", "Staff tool.", **{"infrastructure.deployment_model": "air_gapped", "infrastructure.cloud_preference": "none"}),
                 mk("marketplace", "Shop.", **{"requirements.auth": "phone_otp", "scale.users_12_months": 40000})]
        for kw in cases:
            with self.subTest(type=kw["project.type"]):
                band_is_sum_of_lines(self, run(**kw))

    def test_no_scenario_ids_or_names_in_the_new_module(self):
        with open(os.path.join(ROOT, "engine", "costreal.py"), encoding="utf-8") as f:
            src = f.read()
        self.assertIsNone(re.search(r"\b[PBCDEFHW]\d{1,2}\b", src.replace("D17", "").replace("E8", "")))
        for bad in ("SchoolOne", "InkLetter", "DroneScan", "SensorGrid"):
            self.assertNotIn(bad, src)


if __name__ == "__main__":
    unittest.main()
