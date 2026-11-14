"""P2: wrong-choice and silent-rule fixes (service region availability, client platform fit, video detection,
skill mismatch, team warnings, every air-gap conflict, single-site availability)."""
import copy
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from engine.run import evaluate  # noqa: E402

BASE = {
    "project": {"name": "Probe", "type": "api_platform", "description": "A public API that partners call from their systems.",
                "platforms": ["api_only"]},
    "scale": {"traffic_pattern": "steady", "workload": "balanced", "users_at_launch": 50, "users_12_months": 500,
              "peak_concurrent_users": 50, "data_volume_gb_12_months": 50},
    "team": {"has_devops": True, "size": 5, "experience": "senior", "languages": ["python", "typescript"]},
    "budget": {"monthly_infra_usd": 2000},
    "timeline": {"mvp_weeks": 12},
    "infrastructure": {"cloud_preference": "gcp", "deployment_model": "managed_cloud", "data_residency": "india",
                       "existing_systems": []},
    "requirements": {"realtime": False, "offline_support": False, "full_text_search": False, "file_media_storage": False,
                     "payments": False, "auth": "email_password", "multi_tenant": False, "ml_features": "none",
                     "seo_critical": False, "availability": "99.9", "p95_latency_ms": 500},
    "compliance": [],
    "priorities": {"cost": 3, "time_to_market": 3, "scalability": 3, "security": 3, "maintainability": 3, "performance": 3},
}


def scen(**kw):
    s = copy.deepcopy(BASE)
    for path, v in kw.items():
        sec, key = path.split("__")
        s[sec][key] = v
    return s


def run(s):
    return evaluate(s, counterfactuals=False)


def codes(out):
    return [w["code"] for w in out["warnings"]]


def gateway(out):
    g = [x for x in out["stack"]["supporting"] if x["choice"].startswith("API gateway:")]
    return g[0] if g else None


class ServiceRegion(unittest.TestCase):
    def test_gcp_gateway_not_in_india_region(self):
        out = run(scen())
        g = gateway(out)
        self.assertNotIn("Google Cloud API Gateway", g["choice"])
        self.assertIn("asia-south1", g["choice"])
        self.assertIn("SERVICE_REGION_UNAVAILABLE", codes(out))
        self.assertIn("Google Cloud API Gateway", [a["choice"] for a in g["alternatives"]])

    def test_fintech_api_with_payments_switzerland(self):
        out = run(scen(project__type="fintech", requirements__payments=True, infrastructure__data_residency="other",
                       project__description="A payments API for Swiss banks; all data must stay in Switzerland."))
        g = gateway(out)
        self.assertIsNotNone(g)
        self.assertNotIn("Google Cloud API Gateway", g["choice"])
        self.assertIn("europe-west6", g["choice"])
        self.assertIn("SERVICE_REGION_UNAVAILABLE", codes(out))

    def test_healthtech_api_south_korea(self):
        out = run(scen(project__type="healthtech", requirements__payments=True, infrastructure__data_residency="other",
                       project__description="A clinic booking API for South Korea; patient data must stay in South Korea."))
        g = gateway(out)
        self.assertNotIn("Google Cloud API Gateway", g["choice"])
        self.assertIn("SERVICE_REGION_UNAVAILABLE", codes(out))

    def test_not_fired_where_offered_or_unconstrained(self):
        for kw in ({"infrastructure__data_residency": "eu"}, {"infrastructure__data_residency": "none"},
                   {"infrastructure__cloud_preference": "aws"}):
            out = run(scen(**kw))
            self.assertNotIn("SERVICE_REGION_UNAVAILABLE", codes(out), kw)
        g = gateway(run(scen(infrastructure__data_residency="eu")))
        self.assertIn("Google Cloud API Gateway", g["choice"])


if __name__ == "__main__":
    unittest.main()


def desk(ptype, desc, langs, plats=("desktop",), offline=False, realtime=False):
    s = copy.deepcopy(BASE)
    s["project"].update({"type": ptype, "description": desc, "platforms": list(plats)})
    s["team"]["languages"] = list(langs)
    s["infrastructure"].update({"data_residency": "none", "cloud_preference": "any"})
    s["requirements"].update({"offline_support": offline, "realtime": realtime})
    return run(s)


def fe(out):
    return out["stack"]["frontend"]["choice"]


class ClientPlatformFit(unittest.TestCase):
    def test_game_engine_covers_desktop_with_ios(self):
        out = desk("gaming", "Co-op action game with matchmaking on PC and iOS.", ["csharp", "go"], ("desktop", "ios"), realtime=True)
        self.assertIn("Unity", fe(out))
        self.assertIn("desktop", fe(out))
        self.assertNotIn("WPF", fe(out))

    def test_game_engine_covers_desktop_with_android(self):
        out = desk("gaming", "Puzzle game for Android phones and PCs.", ["csharp"], ("desktop", "android"))
        self.assertNotIn("WPF", fe(out))
        self.assertIn("Android + desktop", fe(out))

    def test_desktop_only_game_gets_engine(self):
        out = desk("gaming", "Single-player strategy game for PC.", ["typescript", "python"])
        self.assertIn("Godot", fe(out))
        self.assertNotIn("Tauri", fe(out))
        out = desk("gaming", "Racing game for PC.", ["csharp"])
        self.assertIn("Unity", fe(out))

    def test_non_windows_desktop_csharp_gets_avalonia(self):
        for ptype, desc in (("other", "Windows/macOS desktop tool for surveyors that syncs to the office server."),
                            ("internal_tool", "Desktop app for staff on Windows and Linux workstations, data on the company server."),
                            ("healthtech", "Clinic desktop app used on Macs and PCs; records are shared through our server.")):
            out = desk(ptype, desc, ["csharp"])
            self.assertIn("Avalonia", fe(out), desc)
            self.assertNotIn("WPF", fe(out), desc)

    def test_windows_only_desktop_keeps_wpf(self):
        out = desk("internal_tool", "Windows desktop app for warehouse staff; data on the company server.", ["csharp"])
        self.assertIn("WPF", fe(out))
        out = desk("gaming", "Browser and PC game.", ["typescript"], ("web", "desktop"))
        self.assertIn("PWA", fe(out))

    def test_negated_mac_or_linux_keeps_wpf(self):
        for ptype, desc in (("internal_tool", "Windows-only internal desktop tool for the finance team to reconcile invoices; it will never run on Mac or Linux."),
                            ("other", "Desktop kiosk app for our Windows PCs; no Linux or macOS support is planned."),
                            ("healthtech", "Clinic desktop app; staff do not use Macs, only Windows workstations.")):
            out = desk(ptype, desc, ["csharp"])
            self.assertIn("WPF", fe(out), desc)
            self.assertNotIn("Avalonia", fe(out), desc)

    def test_mac_named_after_an_unrelated_negation_still_avalonia(self):
        out = desk("other", "No installer needed. Runs on Windows and macOS laptops for field surveyors.", ["csharp"])
        self.assertIn("Avalonia", fe(out))

    def test_native_desktop_offline_not_browser_storage(self):
        for ptype, desc in (("other", "Desktop tool for field surveyors; syncs to the office server when back online."),
                            ("internal_tool", "Desktop app for inspectors; uploads to the company server when online."),
                            ("iot", "Desktop console for technicians that syncs readings to our cloud server later.")):
            out = desk(ptype, desc, ["csharp"], offline=True)
            text = " ".join(x["choice"] for x in out["stack"]["supporting"])
            self.assertNotIn("Service worker", text, desc)
            self.assertNotIn("IndexedDB", text, desc)

    def test_web_offline_keeps_service_worker(self):
        out = desk("web_app", "Field notes web app that syncs to the server.", ["typescript"], ("web",), offline=True)
        text = " ".join(x["choice"] for x in out["stack"]["supporting"])
        self.assertIn("Service worker", text)


def web(ptype, desc, cloud="aws", **req):
    s = copy.deepcopy(BASE)
    s["project"].update({"type": ptype, "description": desc, "platforms": ["web"]})
    s["infrastructure"].update({"cloud_preference": cloud, "data_residency": "us"})
    s["requirements"].update(req)
    return run(s)


def video(out):
    return [x for x in out["stack"]["supporting"] if x["choice"].startswith(("Video calls:", "Live audio/video:"))]


class VideoDetection(unittest.TestCase):
    def test_telehealth_wordings_add_video(self):
        for ptype, desc in (("healthtech", "Video visits between patients and doctors, plus appointment booking."),
                            ("web_app", "A telemedicine portal for rural clinics."),
                            ("marketplace", "Tutors offer virtual appointments to students and get paid per session."),
                            ("saas_b2b", "Recruiters run live video interviews with candidates inside the hiring pipeline.")):
            v = video(web(ptype, desc))
            self.assertEqual(len(v), 1, desc)

    def test_managed_video_names_a_product(self):
        v = video(web("healthtech", "Video appointments with therapists."))[0]
        self.assertTrue(v["choice"].startswith("Video calls: Daily (managed WebRTC video API)"), v["choice"])
        self.assertNotIn("for example", v["choice"])

    def test_no_video_without_live_video_wording(self):
        for desc in ("Appointment booking for clinics with reminders.", "Clinic visits are logged by staff after each appointment.",
                     "A virtual tour of homes for sale with photos."):
            self.assertEqual(video(web("healthtech", desc)), [], desc)

    def test_text_only_or_no_video_gets_no_call_service(self):
        for ptype, desc in (("healthtech", "Teletherapy chat app: clients message their therapist by text only, no video."),
                            ("healthtech", "A telehealth triage service over secure messaging, without video."),
                            ("web_app", "Telemedicine follow-ups by text-only chat between patients and nurses.")):
            self.assertEqual(video(web(ptype, desc)), [], desc)

    def test_video_call_kept_when_only_recording_or_reminders_ruled_out(self):
        for desc in ("Video visits with doctors; no video recordings are stored.",
                     "Telehealth video consultations; appointment reminders are text only."):
            self.assertEqual(len(video(web("healthtech", desc))), 1, desc)

    def test_recorded_sessions_or_interviews_are_not_calls(self):
        for ptype, desc in (("other", "Video editing tool: import recorded video sessions from conferences, trim, caption and export."),
                            ("content_site", "An archive of video interviews with founders, searchable by topic."),
                            ("saas_b2b", "Teachers upload video sessions for students to replay later.")):
            self.assertEqual(video(web(ptype, desc)), [], desc)


def team_run(ptype, langs, plats=("web",), exp="senior", size=8, ml="none", desc="Customers manage orders and reports online."):
    s = copy.deepcopy(BASE)
    s["project"].update({"type": ptype, "description": desc, "platforms": list(plats)})
    s["team"].update({"languages": list(langs), "experience": exp, "size": size})
    s["infrastructure"].update({"data_residency": "none", "cloud_preference": "any"})
    s["requirements"]["ml_features"] = ml
    return run(s)


def skill(out, prefix=""):
    return [w["message"] for w in out["warnings"] if w["code"] == "SKILL_MISMATCH" and w["message"].startswith(prefix)]


class SkillMismatch(unittest.TestCase):
    def test_senior_team_without_js_gets_web_ui_gap(self):
        out = team_run("saas_b2b", ["rust"])
        m = skill(out, "Web UI")
        self.assertEqual(len(m), 1)
        self.assertIn("team.experience=senior", m[0])

    def test_senior_mobile_team_without_its_language(self):
        out = team_run("social", ["cobol"], plats=("ios", "android"))
        self.assertEqual(len(skill(out, "Mobile UI")), 1)

    def test_training_without_python(self):
        for ptype, langs in (("ai_ml_product", ["rust"]), ("data_analytics", ["java"]), ("fintech", ["go", "typescript"])):
            out = team_run(ptype, langs, ml="training", desc="Train a forecasting model on our history and show predictions.")
            m = skill(out, "ML training")
            self.assertEqual(len(m), 1, (ptype, langs))
            self.assertIn("Python", m[0])

    def test_no_warning_when_team_has_language_or_lists_none(self):
        out = team_run("ai_ml_product", ["python", "typescript"], ml="training", desc="Train a forecasting model on our history.")
        self.assertEqual(skill(out), [])
        out = team_run("ai_ml_product", [], ml="training", desc="Train a forecasting model on our history.")
        self.assertEqual(skill(out), [])
        s = copy.deepcopy(BASE)
        del s["team"]["languages"]
        s["requirements"]["ml_features"] = "training"
        self.assertEqual(skill(run(s)), [])


def ops_run(ptype, size, devops, avail, plats=("web",), dep="managed_cloud", exp="intermediate", desc="Customers sign in and manage their records."):
    s = copy.deepcopy(BASE)
    s["project"].update({"type": ptype, "description": desc, "platforms": list(plats)})
    s["team"].update({"size": size, "has_devops": devops, "experience": exp, "languages": ["typescript", "python"]})
    s["infrastructure"].update({"deployment_model": dep, "data_residency": "none", "cloud_preference": "any"})
    s["requirements"]["availability"] = avail
    return run(s)


def sev(out, code):
    return [w["severity"] for w in out["warnings"] if w["code"] == code]


class TeamWarnings(unittest.TestCase):
    def test_availability_vs_team_consistent_for_small_no_devops(self):
        self.assertEqual(sev(ops_run("web_app", 3, False, "99.99"), "AVAILABILITY_VS_TEAM"), ["warning"])
        self.assertEqual(sev(ops_run("saas_b2b", 2, False, "99.95"), "AVAILABILITY_VS_TEAM"), ["warning"])
        self.assertEqual(sev(ops_run("marketplace", 5, False, "99.95"), "AVAILABILITY_VS_TEAM"), ["info"])
        self.assertEqual(sev(ops_run("fintech", 4, False, "99.99"), "AVAILABILITY_VS_TEAM"), ["warning"])

    def test_availability_vs_team_not_for_static_or_staffed(self):
        s = copy.deepcopy(BASE)
        s["project"].update({"type": "content_site", "description": "A marketing site with pre-built pages.", "platforms": ["web"]})
        s["team"].update({"size": 2, "has_devops": False})
        s["requirements"].update({"auth": "none", "availability": "99.95"})
        s["infrastructure"].update({"data_residency": "none", "cloud_preference": "any"})
        out = run(s)
        self.assertNotIn("backend", [k for k, v in out["stack"].items() if isinstance(v, dict) and v.get("deployment") not in (None, "none")])
        self.assertEqual(sev(out, "AVAILABILITY_VS_TEAM"), [])
        self.assertEqual(sev(ops_run("web_app", 3, True, "99.99"), "AVAILABILITY_VS_TEAM"), [])
        self.assertEqual(sev(ops_run("web_app", 8, False, "99.95"), "AVAILABILITY_VS_TEAM"), [])
        self.assertEqual(sev(ops_run("web_app", 2, False, "99.9"), "AVAILABILITY_VS_TEAM"), [])

    def test_self_run_without_devops(self):
        for ptype, dep in (("iot", "self_hosted_cloud_vm"), ("internal_tool", "on_premise"), ("healthtech", "self_hosted_cloud_vm")):
            out = ops_run(ptype, 2, False, "99.9", dep=dep)
            self.assertEqual(sev(out, "SELF_RUN_WITHOUT_DEVOPS"), ["info"], (ptype, dep))
            m = next(w["message"] for w in out["warnings"] if w["code"] == "SELF_RUN_WITHOUT_DEVOPS")
            self.assertIn(dep, m)

    def test_info_band_text_is_soft(self):
        for ptype, size in (("ecommerce", 5), ("marketplace", 4), ("saas_b2b", 3)):
            out = ops_run(ptype, size, False, "99.95")
            self.assertEqual(sev(out, "AVAILABILITY_VS_TEAM"), ["info"], ptype)
            m = next(w["message"] for w in out["warnings"] if w["code"] == "AVAILABILITY_VS_TEAM")
            self.assertNotIn("rarely sustains", m)
            self.assertIn("can staff an on-call rota", m)

    def test_warning_band_keeps_strong_text(self):
        out = ops_run("web_app", 3, False, "99.99")
        m = next(w["message"] for w in out["warnings"] if w["code"] == "AVAILABILITY_VS_TEAM")
        self.assertIn("rarely sustains", m)
        self.assertIn("relax the target", m)

    def test_self_run_managed_cloud_advice_only_for_cloud_vms(self):
        for ptype, dep in (("internal_tool", "on_premise"), ("healthtech", "air_gapped"), ("iot", "on_premise")):
            out = ops_run(ptype, 2, False, "99.9", dep=dep)
            m = next(w["message"] for w in out["warnings"] if w["code"] == "SELF_RUN_WITHOUT_DEVOPS")
            self.assertNotIn("managed_cloud", m, dep)
        out = ops_run("iot", 2, False, "99.9", dep="self_hosted_cloud_vm")
        m = next(w["message"] for w in out["warnings"] if w["code"] == "SELF_RUN_WITHOUT_DEVOPS")
        self.assertIn("reconsider managed_cloud", m)

    def test_self_run_with_devops_or_managed_is_silent(self):
        self.assertEqual(sev(ops_run("iot", 2, True, "99.9", dep="self_hosted_cloud_vm"), "SELF_RUN_WITHOUT_DEVOPS"), [])
        self.assertEqual(sev(ops_run("iot", 2, False, "99.9"), "SELF_RUN_WITHOUT_DEVOPS"), [])


def gap_run(ptype, cloud, dep, **req):
    s = copy.deepcopy(BASE)
    s["project"].update({"type": ptype, "description": "Internal system inside our own network.", "platforms": ["web"]})
    s["infrastructure"].update({"cloud_preference": cloud, "deployment_model": dep, "data_residency": "none"})
    s["requirements"].update(req)
    return run(s)


class AllAirGapConflicts(unittest.TestCase):
    def test_infeasible_lists_every_air_gap_conflict(self):
        out = gap_run("healthtech", "aws", "air_gapped", auth="social", payments=True, ml_features="llm_rag")
        self.assertEqual(out["status"], "infeasible")
        c = codes(out)
        for code in ("CLOUD_PROVIDER_VS_ONPREM", "SOCIAL_LOGIN_NEEDS_NETWORK", "PAYMENTS_NEED_NETWORK", "LLM_API_NEEDS_NETWORK"):
            self.assertIn(code, c)
        self.assertIn("social login, card payments, a hosted LLM API", out["summary"])

    def test_other_types_and_clouds(self):
        out = gap_run("ecommerce", "azure", "air_gapped", payments=True)
        self.assertIn("PAYMENTS_NEED_NETWORK", codes(out))
        out = gap_run("social", "gcp", "air_gapped", auth="phone_otp")
        self.assertIn("PHONE_OTP_NEEDS_NETWORK", codes(out))
        self.assertEqual(out["status"], "infeasible")

    def test_not_for_on_premise_or_without_such_requirements(self):
        out = gap_run("ecommerce", "aws", "on_premise", auth="social", payments=True)
        self.assertEqual(out["status"], "infeasible")
        self.assertEqual([x for x in codes(out) if x.endswith(("NEEDS_NETWORK", "NEED_NETWORK"))], [])
        out = gap_run("internal_tool", "aws", "air_gapped")
        self.assertEqual(codes(out), ["CLOUD_PROVIDER_VS_ONPREM"])


def vm_run(ptype, res, avail, desc="Customers sign in and manage their records."):
    s = copy.deepcopy(BASE)
    s["project"].update({"type": ptype, "description": desc, "platforms": ["web"]})
    s["infrastructure"].update({"deployment_model": "self_hosted_cloud_vm", "cloud_preference": "any", "data_residency": res})
    s["team"].update({"size": 10, "has_devops": True, "experience": "mixed", "languages": ["java", "javascript"]})
    s["priorities"].update({"cost": 4})
    s["requirements"]["availability"] = avail
    if res == "other":
        s["infrastructure"]["residency_country"] = "singapore"
    return run(s)


def cost_text(out):
    return " ".join(out["estimated_monthly_cost_usd"]["assumptions"])


class SingleSiteAvailability(unittest.TestCase):
    def test_single_datacenter_region_never_claims_another_zone(self):
        for ptype, res, desc in (("fintech", "india", "Loan servicing portal for an Indian lender."),
                                 ("saas_b2b", "eu", "Scheduling tool for European clinics."),
                                 ("web_app", "other", "Booking app for Singapore gyms; data must stay in Singapore.")):
            out = vm_run(ptype, res, "99.95", desc)
            if not out["stack"]["hosting"]["choice"].startswith("DigitalOcean"):
                self.skipTest("host is not a single-datacenter VM for this input: " + out["stack"]["hosting"]["choice"])
            self.assertIn("SINGLE_SITE_AVAILABILITY", codes(out), ptype)
            self.assertNotIn("another zone", cost_text(out), ptype)
            self.assertIn("same datacenter", cost_text(out), ptype)

    def test_single_region_warning_says_one_datacenter(self):
        for ptype, res, desc in (("fintech", "eu", "Customer portal for an EU insurer, high availability required."),
                                 ("saas_b2b", "india", "Payroll tool for Indian firms."),
                                 ("web_app", "other", "Booking app for Singapore gyms; data must stay in Singapore.")):
            out = vm_run(ptype, res, "99.99", desc)
            if "SINGLE_SITE_AVAILABILITY" not in codes(out):
                self.skipTest("host is not a single-datacenter VM for this input: " + out["stack"]["hosting"]["choice"])
            m = " ".join(w["message"] for w in out["warnings"] if w["code"] == "AVAILABILITY_SINGLE_REGION")
            self.assertIn("one datacenter", m, ptype)
            self.assertNotIn("multi-zone", m, ptype)

    def test_multi_zone_region_keeps_multi_zone_wording(self):
        s = copy.deepcopy(BASE)
        s["project"].update({"type": "web_app", "description": "Customers sign in and manage their records.", "platforms": ["web"]})
        s["infrastructure"].update({"cloud_preference": "aws", "data_residency": "eu"})
        s["requirements"]["availability"] = "99.99"
        out = run(s)
        self.assertNotIn("SINGLE_SITE_AVAILABILITY", codes(out))
        m = " ".join(w["message"] for w in out["warnings"] if w["code"] == "AVAILABILITY_SINGLE_REGION")
        self.assertNotIn("one datacenter", m)

    def test_not_for_lower_target_or_multi_datacenter_region(self):
        out = vm_run("fintech", "india", "99.9")
        self.assertNotIn("SINGLE_SITE_AVAILABILITY", codes(out))
        out = vm_run("saas_b2b", "us", "99.95")
        self.assertNotIn("SINGLE_SITE_AVAILABILITY", codes(out))
