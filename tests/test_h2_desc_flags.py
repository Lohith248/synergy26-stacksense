"""H2 (blind9 A2/A3): a description that needs live updates, search, an assistant, offline tolerance or a reminder sender while the hard
flag says no gets a quoted warning (the flag is never overridden); an existing identity provider that staff sign in through is used for staff.
Each rule: several project types plus inputs where it must not fire. Inputs are inline."""
import copy
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from engine.run import evaluate  # noqa: E402

BASE = {"scenario_id": "H2", "project": {"type": "web_app", "platforms": ["web"], "description": "x"},
        "scale": {"users_at_launch": 800, "users_12_months": 6000, "peak_concurrent_users": 150},
        "team": {"size": 3, "experience": "intermediate", "languages": ["typescript"], "has_devops": False},
        "budget": {"monthly_infra_usd": 600}, "timeline": {"mvp_weeks": 14},
        "infrastructure": {"cloud_preference": "any", "deployment_model": "managed_cloud", "data_residency": "none", "existing_systems": []},
        "requirements": {"auth": "email_password", "realtime": False, "full_text_search": False, "offline_support": False, "ml_features": "none",
                         "payments": False}}


def run(desc, typ="web_app", plats=("web",), req=None, infra=None):
    s = copy.deepcopy(BASE)
    s["project"].update(type=typ, platforms=list(plats), description=desc)
    s["requirements"].update(req or {})
    s["infrastructure"].update(infra or {})
    return evaluate(s, counterfactuals=False)


def codes(out):
    return {w["code"] for w in out["warnings"]}


def warn(out, code):
    return next(w for w in out["warnings"] if w["code"] == code)


def layers(out):
    return [s["layer"] + "=" + s["choice"] for s in out["stack"]["supporting"]]


class DescriptionVersusFlag(unittest.TestCase):
    def test_realtime_wording_with_flag_false_warns_and_quotes(self):
        cases = (("marketplace", "Live auctions. Bids and the countdown timer must update instantly for every watcher of a lot."),
                 ("other", "Dispatchers see driver positions on a map with live tracking of every van."),
                 ("social", "A community board where new comments appear in real time without a page refresh."),
                 ("internal_tool", "Kitchen display: orders show up on the screen immediately and the totals update in real time."))
        for typ, desc in cases:
            with self.subTest(typ=typ):
                out = run(desc, typ)
                w = warn(out, "DESC_VS_FLAG_REALTIME")
                self.assertEqual(w["severity"], "warning")
                self.assertIn("requirements.realtime", w["message"])
                self.assertIn(w["message"].split("('")[1].split("')")[0].replace(" ...", ""), desc)  # the quote comes from the input
                self.assertNotIn("realtime", {s["layer"] for s in out["stack"]["supporting"]})  # the hard flag is not overridden

    def test_realtime_must_not_fire(self):
        for desc, req in (("We do NOT need live updates; supervisors simply refresh the page.", {}),
                          ("No live updates are needed. Staff reload the list when they want new orders.", {}),
                          ("Live auctions: bids must update instantly.", {"realtime": True}),
                          ("Booking site for a dentist. Patients pick a slot from a calendar.", {})):
            with self.subTest(desc=desc):
                self.assertNotIn("DESC_VS_FLAG_REALTIME", codes(run(desc, req=req)))

    def test_search_wording_with_flag_false_warns(self):
        cases = (("marketplace", "Buyers search lots by model, lens mount and keywords."),
                 ("content_site", "Readers can search the archive of articles by keyword."),
                 ("internal_tool", "Staff search the knowledge base for past tickets."))
        for typ, desc in cases:
            with self.subTest(typ=typ):
                w = warn(run(desc, typ), "DESC_VS_FLAG_SEARCH")
                self.assertIn("requirements.full_text_search", w["message"])
                self.assertEqual(w["severity"], "warning")

    def test_search_must_not_fire(self):
        for desc, req in (("Search engines should index the pages; there is no search box and no site search.", {}),
                          ("We do not need search; the list has twelve items.", {}),
                          ("Readers search the archive by keyword.", {"full_text_search": True}),
                          ("Search engine optimisation matters for the brochure pages.", {})):
            with self.subTest(desc=desc):
                self.assertNotIn("DESC_VS_FLAG_SEARCH", codes(run(desc, req=req)))

    def test_assistant_wording_with_ml_none_warns(self):
        cases = (("marketplace", "A chat assistant answers questions grounded in our lot catalogue."),
                 ("healthtech", "A chatbot answers patients' questions about opening hours and preparation."),
                 ("saas_b2b", "An AI assistant summarises each customer's tickets using an LLM."))
        for typ, desc in cases:
            with self.subTest(typ=typ):
                w = warn(run(desc, typ), "DESC_VS_FLAG_ASSISTANT")
                self.assertIn("requirements.ml_features", w["message"])

    def test_assistant_must_not_fire(self):
        for desc, req in (("A chat assistant answers questions grounded in our catalogue.", {"ml_features": "llm_rag"}),
                          ("No chatbot and no AI features; staff answer every question by phone.", {}),
                          ("Members chat with each other in group rooms.", {})):
            with self.subTest(desc=desc):
                self.assertNotIn("DESC_VS_FLAG_ASSISTANT", codes(run(desc, req=req)))

    def test_patchy_connection_with_offline_false_is_noted(self):
        cases = (("web_app", "Pickers scan barcodes. Wi-Fi is patchy on the mezzanine, so a page must survive a dropped connection."),
                 ("healthtech", "Nurses record vitals on wards where the network drops several times a shift."),
                 ("iot", "Field engineers log readings in tunnels with no connectivity; the app must keep working without a connection."))
        for typ, desc in cases:
            with self.subTest(typ=typ):
                w = warn(run(desc, typ), "DESC_VS_FLAG_OFFLINE")
                self.assertEqual(w["severity"], "info")
                self.assertIn("requirements.offline_support", w["message"])

    def test_offline_must_not_fire(self):
        for desc, req in (("Wi-Fi is patchy on the mezzanine, so scans must survive a dropped connection.", {"offline_support": True}),
                          ("Office staff on fibre; the network is reliable and always on.", {}),
                          ("There is no patchy Wi-Fi here: every desk is wired.", {})):
            with self.subTest(desc=desc):
                self.assertNotIn("DESC_VS_FLAG_OFFLINE", codes(run(desc, req=req)))

    def test_reminders_without_a_channel_get_an_assumed_email_sender(self):
        for typ, desc in (("web_app", "Appointment booking and vaccination reminders for a vet clinic."),
                          ("internal_tool", "Leave tracker: managers get reminders to approve pending requests."),
                          ("web_app", "Gym class booking; members get class reminders the day before.")):
            with self.subTest(desc=desc):
                out = run(desc, typ)
                self.assertEqual(warn(out, "REMINDER_SENDER_NOT_SELECTED")["severity"], "info")
                self.assertTrue(any(l.startswith("other=Email delivery") for l in layers(out)))

    def test_reminders_must_not_add_a_sender_when_a_channel_exists(self):
        for typ, plats, desc in (("web_app", ("web",), "Booking site that sends confirmation e-mails and reminders."),
                                 ("web_app", ("android",), "Appointment app with reminders on the phone."),
                                 ("web_app", ("web",), "Booking site that sends SMS reminders the day before."),
                                 ("web_app", ("web",), "Stock list for a shop; no reminders are wanted.")):
            with self.subTest(desc=desc):
                out = run(desc, typ, plats)
                self.assertNotIn("REMINDER_SENDER_NOT_SELECTED", codes(out))

    def test_a_named_channel_or_a_snooze_is_not_a_missing_sender(self):
        for desc in ("Clients get reminder notifications in the browser before each session.",
                     "Tasks can be snoozed: the app will remind me later when I tap snooze.",
                     "Users press remind me later on a task to move it to tomorrow."):
            with self.subTest(desc=desc):
                self.assertNotIn("REMINDER_SENDER_NOT_SELECTED", codes(run(desc)))

    def test_a_clause_that_rules_it_out_or_hands_it_over_does_not_fire(self):
        for desc, code in (("We considered GPT but decided against any AI features.", "DESC_VS_FLAG_ASSISTANT"),
                           ("Search for jobs is handled by the existing LinkedIn integration we link to.", "DESC_VS_FLAG_SEARCH"),
                           ("Updates arrive instantly, rather than polling is something we ruled out.", "DESC_VS_FLAG_REALTIME")):
            with self.subTest(desc=desc):
                self.assertNotIn(code, codes(run(desc)))


class StaffSso(unittest.TestCase):
    def staff_items(self, out):
        return [s for s in out["stack"]["supporting"] if s["choice"].startswith("Staff sign-in")]

    def test_staff_sign_in_through_an_existing_provider_adds_a_staff_item(self):
        cases = (("healthtech", "Patient portal for a hospital. Staff sign in through the hospital identity provider.", "Okta workforce identity", "Okta"),
                 ("internal_tool", "Parts ordering. Employees log in with their Google Workspace accounts through single sign-on.", "Google Workspace", "Google Workspace"),
                 ("web_app", "Parent portal for a school. Teachers sign in with their domain logins.", "On-prem Active Directory", "Active Directory"),
                 ("ecommerce", "Online shop. Staff sign in through our Ping Identity tenant to manage orders.", "Ping Identity", "Ping Identity"),
                 # holdout2 twin M01 (L05 says "Clinicians already sign in through our Okta tenant"): therapists are staff too
                 ("healthtech", "Patients book live video therapy sessions; therapists sign in via the company's existing Okta.", "Okta workforce identity", "Okta"),
                 ("web_app", "Course platform for students. Instructors sign in through the university's Okta tenant.", "Okta workforce identity", "Okta"))
        for typ, desc, existing, name in cases:
            with self.subTest(existing=existing):
                out = run(desc, typ, infra={"existing_systems": [existing]})
                items = self.staff_items(out)
                self.assertEqual(len(items), 1)
                self.assertIn(name, items[0]["choice"])
                self.assertIn("staff", items[0]["justification"].lower())
                w = warn(out, "STAFF_SIGNIN_VIA_IDP")
                self.assertIn("staff sign in", w["message"])

    def test_must_not_fire(self):
        d = "Patient portal for a hospital. Staff sign in through the hospital identity provider."
        for desc, req, existing in ((d, {"auth": "enterprise_sso"}, ["Okta workforce identity"]),      # enterprise_sso already uses it
                                    (d, {}, []),                                                         # no provider exists
                                    ("Shop for customers. Customers sign in with e-mail.", {}, ["Okta workforce identity"]),  # no staff sign-in sentence
                                    ("Staff do not sign in through the identity provider; they use local accounts.", {}, ["Okta workforce identity"]),
                                    ("Therapy app. Patients sign in with e-mail; therapists are listed in a directory.", {}, ["Okta"])):  # no staff sign-in sentence
            with self.subTest(desc=desc, req=req):
                self.assertEqual(self.staff_items(run(desc, "healthtech", req=req, infra={"existing_systems": existing})), [])

    def test_ordinary_use_sentences_are_not_staff_sign_in(self):
        for desc in ("Managers use the company car booking page to reserve vans.",
                     "Staff use their phones on the work floor to scan parcels.",
                     "Nurses use the existing paper forms.",
                     "Employees use the hospital network drive for documents."):
            with self.subTest(desc=desc):
                self.assertEqual(self.staff_items(run(desc, "healthtech", infra={"existing_systems": ["Okta workforce identity"]})), [])

    def test_domain_login_wording_still_adds_the_staff_item(self):
        out = run("Staff use their domain logins.", "internal_tool", infra={"existing_systems": ["Okta workforce identity"]})
        self.assertEqual(len(self.staff_items(out)), 1)

    def test_existing_directory_without_staff_wording_still_gets_the_note(self):
        out = run("Telehealth scheduling for a clinic group.", "healthtech", infra={"existing_systems": ["Active Directory"]})
        w = warn(out, "EXISTING_IDP_NOT_USED")
        self.assertEqual(w["severity"], "info")
        self.assertIn("Active Directory", w["message"])


if __name__ == "__main__":
    unittest.main()
