"""Description-signal hygiene: a signal fires only for the thing it names, honours negation in its own clause, and its
prose uses no noun absent from the input; score numbers never appear as "points" in prose.
Each rule is stated without a scenario and tested on several project types plus inputs where it must not fire.
Written before the change; inputs are inline (nothing outside source/ is read)."""
import copy
import glob
import json
import os
import re
import sys
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from engine.run import evaluate  # noqa: E402
from engine.context import desc_signals  # noqa: E402

with open(os.path.join(ROOT, "scenarios", "stacksense_public_scenarios.json"), encoding="utf-8") as f:
    PUBLIC = {s["scenario_id"]: s for s in json.load(f)}

BASE = {"scenario_id": "SH", "project": {"type": "web_app", "platforms": ["web"], "description": ""},
        "scale": {"users_at_launch": 800, "users_12_months": 3000, "peak_concurrent_users": 150},
        "team": {"size": 5, "experience": "intermediate", "languages": ["typescript"], "has_devops": True},
        "budget": {"monthly_infra_usd": 2000}, "timeline": {"mvp_weeks": 14},
        "infrastructure": {"cloud_preference": "any", "deployment_model": "managed_cloud", "data_residency": "none",
                           "existing_systems": []},
        "requirements": {"auth": "email_password"}}


def build(base, desc=None, extra=None, **kw):
    s = copy.deepcopy(base)
    if desc is not None:
        s["project"]["description"] = desc
    if extra:
        s["project"]["description"] = (s["project"].get("description") or "") + " " + extra
    for path, v in kw.items():
        node, parts = s, path.split(".")
        for p in parts[:-1]:
            node = node.setdefault(p, {})
        node[parts[-1]] = v
    return s


def run(base, desc=None, extra=None, **kw):
    return evaluate(build(base, desc, extra, **kw), counterfactuals=False)


def text(out):
    return json.dumps(out, ensure_ascii=False).lower()


def flags(desc):
    return desc_signals(desc)[0]


def supporting(out, word):
    return [s for s in out["stack"]["supporting"] if word.lower() in s["choice"].lower()]


GEO_WORDS = re.compile(r"gps|postgis|geography")


class GpsIsNotMedia(unittest.TestCase):
    """Rule: GPS/PostGIS wording appears only when the description names a location; photos and cameras are media."""

    def test_flags_split(self):
        for desc, gps, media in (("Employees upload profile photos.", False, True),
                                 ("Security cameras watch the factory line.", False, True),
                                 ("Listings with photos and prices.", False, True),
                                 ("Field agents record GPS-tagged photos.", True, True),
                                 ("Couriers send GPS coordinates every minute.", True, False),
                                 ("Support GPs book appointments.", False, False),
                                 ("Users geotag their posts.", True, False),
                                 ("Latitude/longitude is stored per site.", True, False),
                                 ("Public API for currency rates and IP geolocation.", False, False)):
            f = flags(desc)
            self.assertEqual((f["gps"], f["media"]), (gps, media), desc)

    def test_internal_tool_with_profile_photos(self):
        out = run(PUBLIC["P5"], extra="Employees upload profile photos.")
        self.assertIsNone(GEO_WORDS.search(text(out)), GEO_WORDS.search(text(out)))
        self.assertTrue(supporting(out, "blob") or supporting(out, "storage") or supporting(out, "s3")
                        or [s for s in out["stack"]["supporting"] if s["layer"] == "storage"])

    def test_negated_cameras_out_of_scope(self):
        base = run(PUBLIC["P5"])
        out = run(PUBLIC["P5"], extra="Security cameras are out of scope.")
        self.assertIsNone(GEO_WORDS.search(text(out)))
        self.assertEqual(out["stack"]["supporting"], base["stack"]["supporting"])

    def test_marketplace_listing_photos(self):
        out = run(BASE, "A marketplace where sellers post listings with photos and buyers pay by card.",
                  **{"project.type": "marketplace", "requirements.payments": True})
        self.assertIsNone(GEO_WORDS.search(text(out)))
        store = [s for s in out["stack"]["supporting"] if s["layer"] == "storage"]
        self.assertTrue(store)
        self.assertIn("photos", store[0]["justification"].lower())

    def test_factory_line_cameras(self):
        out = run(BASE, "Dashboard for factory line cameras and machine status.", **{"project.type": "iot"})
        self.assertIsNone(GEO_WORDS.search(text(out)))

    def test_real_gps_still_fires(self):
        out = run(BASE, "Couriers send GPS coordinates every minute and customers see the van on a map.")
        self.assertIn("PostGIS geography points", out["stack"]["database"]["justification"])
        # no photos in the input: the storage text must not claim them
        self.assertFalse([s for s in out["stack"]["supporting"] if s["layer"] == "storage"
                          and "photo" in s["justification"].lower()])

    def test_public_gps_scenario_keeps_both(self):
        out = evaluate(copy.deepcopy(PUBLIC["P6"]), counterfactuals=False)
        self.assertIn("PostGIS geography points", out["stack"]["database"]["justification"])
        store = [s for s in out["stack"]["supporting"] if s["layer"] == "storage"][0]
        self.assertIn("GPS-tagged photos", store["justification"])


class NegationGuard(unittest.TestCase):
    """Rule: a signal word inside a negated clause does not fire; a negation in another clause does not suppress it."""

    NEGATED = (("We do not need a ledger.", "ledger"), ("There is no ledger.", "ledger"),
               ("The product works without KYC.", "kyc"), ("No UPI support is planned.", "upi"),
               ("Chat is out of scope.", "chat"), ("We never use markdown.", "markdown"),
               ("Photos are not needed.", "media"), ("The app must work without GPS tracking.", "gps"),
               ("No need for offline reports.", "analytics"), ("Not for low-end devices.", "low_end"),
               ("It isn't an intranet.", "internal_only"), ("Excluding subscriptions.", "recurring"),
               ("We don't need KYC checks and chat.", "chat"))
    POSITIVE = (("No downtime is allowed, so every ledger entry is immutable.", "ledger"),
                ("We do not need chat, but we do need KYC.", "kyc"),
                ("We do not need a ledger and we need photos of receipts.", "media"),
                ("Not only a ledger but also payouts.", "ledger"),
                ("There is no manager approval step, yet staff upload photos.", "media"),
                ("Without a doubt we need a double-entry ledger.", "ledger"),
                ("Chat is not optional.", "chat"),
                ("Never lose an upload: photos of receipts are stored.", "media"))

    def test_negated_signals_do_not_fire(self):
        for desc, key in self.NEGATED:
            self.assertFalse(flags(desc)[key], desc)

    def test_other_clause_keeps_signal(self):
        for desc, key in self.POSITIVE:
            self.assertTrue(flags(desc)[key], desc)

    def test_negated_ledger_leaves_no_trace(self):
        base = run(PUBLIC["P5"])
        out = run(PUBLIC["P5"], extra="We do not need a ledger.")
        self.assertFalse(supporting(out, "ledger"))
        self.assertNotIn("ledger", text(out).replace("we do not need a ledger.", ""))
        self.assertNotIn("requirements.payments", out["stack"]["database"]["driven_by"])
        self.assertEqual([out["stack"][k]["choice"] for k in ("frontend", "backend", "database", "hosting")],
                         [base["stack"][k]["choice"] for k in ("frontend", "backend", "database", "hosting")])

    def test_negated_kyc_and_upi_in_other_types(self):
        for sc, extra in (("P2", "No KYC is required."), ("P3", "We do not need UPI."), ("P1", "No chat widget.")):
            out = run(PUBLIC[sc], extra=extra)
            base = run(PUBLIC[sc])
            self.assertEqual(text(out).replace(extra.lower(), ""), text(base).replace(extra.lower(), ""), sc)

    def test_affirmed_ledger_still_fires(self):
        out = run(PUBLIC["P5"], extra="Keep a double-entry ledger of every asset assignment.")
        self.assertTrue(supporting(out, "ledger"))


class SignalTextUsesInputNouns(unittest.TestCase):
    """Rule: prose produced by a signal names only things the description (or the structured input) contains."""

    LEND = re.compile(r"\bloans?\b|\bemi\b|disburs|borrower|lending|rbi digital lending")

    def ledger_text(self, out):
        return [s["justification"] for s in supporting(out, "ledger")]

    def test_ledger_bookkeeping_has_no_lending_words(self):
        for base, desc, kw in ((BASE, "Small shop bookkeeping app with a double-entry ledger.", {}),
                               (PUBLIC["P5"], "Asset tracking with a double-entry ledger of every transfer.", {}),
                               (BASE, "Wallet app with a ledger; users send money to friends.",
                                {"project.type": "fintech", "requirements.payments": True})):
            out = run(base, desc if base is BASE else None, extra=None if base is BASE else desc, **kw)
            texts = self.ledger_text(out)
            self.assertTrue(texts, desc)
            self.assertIsNone(self.LEND.search(text(out)), (desc, self.LEND.search(text(out))))

    def test_ledger_without_payments_does_not_cite_payments(self):
        out = run(BASE, "Club accounts app with a double-entry ledger.")
        self.assertNotIn("requirements.payments", out["stack"]["database"]["driven_by"])
        self.assertNotIn("gateway", self.ledger_text(out)[0].lower())

    def test_lending_words_present_keep_lending_text(self):
        out = evaluate(copy.deepcopy(PUBLIC["P4"]), counterfactuals=False)
        self.assertIn("Loan disbursals and EMI collections post balanced debit/credit entries", self.ledger_text(out)[0])

    def test_payout_text_names_no_loans_without_loan_words(self):
        out = run(BASE, "Money app: users pay out balances to friends.", **{"project.type": "fintech",
                                                                              "requirements.payments": True,
                                                                              "infrastructure.data_residency": "india"})
        self.assertNotIn("loan", text(out))
        self.assertNotIn("lending", text(out))

    def test_payout_payee_follows_the_input(self):
        india = {"infrastructure.data_residency": "india", "requirements.payments": True}
        for desc, typ, want in (("Riders book bike mechanics. Mechanics get paid.", "marketplace", "service providers"),
                                ("Sellers list crafts and get paid after delivery.", "marketplace", "sellers"),
                                ("Prepaid wallet with merchant payouts.", "fintech", "merchants"),
                                ("Prepaid wallet with partner payouts.", "fintech", "recipients")):
            out = run(BASE, desc, **{"project.type": typ, **india})
            pay = [s for s in out["stack"]["supporting"] if s["layer"] == "payments"][0]["choice"]
            self.assertIn("pay " + want, pay, desc)
            self.assertNotIn("loan", pay.lower(), desc)

    def test_kyc_vault_only_when_kyc_named(self):
        out = run(PUBLIC["P5"], extra="Employees upload scanned receipts.")
        self.assertFalse(supporting(out, "KYC"))


class NegationScope(unittest.TestCase):
    """Rules: (a) a double negation ("cannot ... without KYC") affirms; (b) a loss or omission verb ("must not lose a ledger
    entry", "no messages are lost") is a requirement, not a negation; (c) "without/unless/until" later in the clause affirms.
    Plus: clause breaks at so/because/since/who/which/that, and past experience ("never used one before") is no negation."""

    DOUBLE = (("Loans cannot be disbursed without KYC.", "kyc"), ("Loans cannot be disbursed without KYC.", "payouts"),
              ("Borrowers cannot apply without completing KYC.", "kyc"), ("No loan is approved without KYC.", "kyc"),
              ("Customers can't pay without UPI.", "upi"), ("No order ships without photos of the parcel.", "media"),
              ("Field staff cannot submit a report without GPS coordinates.", "gps"),
              ("Users cannot chat without verifying their phone.", "chat"),
              ("Without approval nothing ships; the workflow is key.", "approvals"))
    LOSS = (("Must not lose a single ledger entry.", "ledger"), ("Never delete ledger rows.", "ledger"),
            ("cannot lose any chat history", "chat"), ("Never lose a chat message.", "chat"),
            ("Users never miss a message.", "chat"), ("Never miss a chat.", "chat"), ("No messages are lost", "chat"),
            ("We must not skip KYC for any customer.", "kyc"), ("Never drop a photo upload.", "media"))
    LATER_WITHOUT = (("We do not need chat unless users ask for it.", "chat"),
                     ("Photos are not needed until the second release.", "media"),
                     ("The ledger is not required without payments.", "ledger"))
    MUST_NEGATE = (("There is no chat.", "chat"), ("No need for chat.", "chat"), ("NO CHAT", "chat"),
                   ("Works without payments or KYC.", "kyc"), ("Neither chat nor KYC.", "chat"),
                   ("Neither chat nor KYC.", "kyc"), ("We don't need a ledger.", "ledger"),
                   ("We don\u2019t need a ledger.", "ledger"), ("The ledger is out of scope.", "ledger"),
                   ("KYC is not required.", "kyc"), ("There is no Markdown editor.", "markdown"),
                   ("We do not plan to build an in-house ledger.", "ledger"), ("Nobody wants chat.", "chat"),
                   ("None of the users need markdown.", "markdown"))
    CLAUSES = (("We are not a bank so ledger accuracy matters.", "ledger"),
               ("We are not a bank because ledger accuracy matters.", "ledger"),
               ("We have never used a ledger before and now need one.", "ledger"),
               ("Users who don't have smartphones can still chat by SMS.", "chat"),
               ("We do not need chat and now want KYC checks.", "kyc"))

    def check(self, cases, want):
        for desc, key in cases:
            self.assertEqual(flags(desc)[key], want, (desc, key))

    def test_rule_a_double_negation_affirms(self):
        self.check(self.DOUBLE, True)

    def test_rule_b_loss_verbs_are_requirements(self):
        self.check(self.LOSS, True)

    def test_rule_c_later_without_unless_until_affirms(self):
        self.check(self.LATER_WITHOUT, True)

    def test_plain_negations_still_negate(self):
        self.check(self.MUST_NEGATE, False)

    def test_clause_breaks_and_past_experience(self):
        self.check(self.CLAUSES, True)


class NegationEdgeCases(unittest.TestCase):
    """Requirements that read like negations must fire; list and label forms of a real negation must not."""

    FIRE = (
        # a leading "Without X, consequence" and "nothing ... without" state a requirement
        ("Without KYC, no account can be opened.", "kyc"), ("Without photos, a claim cannot be filed.", "media"),
        ("Without a ledger, audits fail.", "ledger"), ("Nothing goes out without manager approval.", "approvals"),
        ("Nothing is final without a ledger posting.", "ledger"),
        # describing today's problem
        ("Today, staff cannot chat with customers.", "chat"), ("Managers cannot see reports today.", "analytics"),
        ("There is no ledger today, so balances drift.", "ledger"), ("Customers can't message the shop today.", "chat"),
        ("Patients never get reminders today.", "notifications"),
        # a negator more than one word away, or an imperative prohibition
        ("Teachers do not have time and parents want chat.", "chat"),
        ("Users should not have to leave the app to chat.", "chat"),
        ("Never assign two jobs to one rider.", "jobs_dispatch"), ("Do not send alerts at night.", "notifications"),
        ("We do not need a ledger, KYC is mandatory.", "kyc"))
    NO_FIRE = (
        ("An app without chat and without payments.", "chat"), ("An app with payments but without chat.", "chat"),
        ("No in-app chat or messaging.", "chat"), ("We are not adding payments, UPI or cards.", "upi"),
        ("Chat: not needed.", "chat"), ("KYC - out of scope.", "kyc"), ("Chat is not a requirement.", "chat"),
        ("Photos are not a priority.", "media"), ("We have decided against chat.", "chat"), ("Skip chat.", "chat"),
        ("Chat is ruled out.", "chat"), ("We do not need chat today.", "chat"), ("There won't be any chat.", "chat"), ("Chat is not needed yet.", "chat"),
        ("We do not need a ledger, KYC is mandatory.", "ledger"))

    def test_must_fire(self):
        for desc, key in self.FIRE:
            self.assertTrue(flags(desc)[key], (desc, key))

    def test_must_not_fire(self):
        for desc, key in self.NO_FIRE:
            self.assertFalse(flags(desc)[key], (desc, key))

    def test_comment_form_of_known_limit(self):
        # documented limit: a negation separated from its signal by a longer phrase is not seen, so the signal fires
        self.assertTrue(flags("We do not want the extra cost of running a chat service.")["chat"])


class LendingWordsAndPayee(unittest.TestCase):
    def test_ledger_verb_agrees_with_its_subject(self):
        plain = run(BASE, "Small shop bookkeeping app with a double-entry ledger.")
        self.assertIn("Every money movement posts balanced debit/credit entries", supporting(plain, "ledger")[0]["justification"])
        lend = evaluate(copy.deepcopy(PUBLIC["P4"]), counterfactuals=False)
        self.assertIn("EMI collections post balanced", supporting(lend, "ledger")[0]["justification"])

    def test_lending_needs_loan_words(self):
        for desc, want in (("Disburse salaries to employees with a payroll ledger.", False),
                           ("Members borrow books from the library.", False),
                           ("Small personal loans with instalments.", True),
                           ("Borrowers repay monthly.", True), ("Lenders list offers.", True)):
            self.assertEqual(flags(desc)["lending"], want, desc)

    def test_payroll_disbursal_has_no_loan_wording(self):
        out = run(BASE, "Disburse salaries to employees with a payroll ledger.",
                  **{"project.type": "fintech", "requirements.payments": True, "infrastructure.data_residency": "india"})
        self.assertTrue(supporting(out, "ledger"))
        self.assertNotIn("loan", text(out))
        self.assertNotIn("borrower", text(out))

    def test_payee_is_a_whole_word_not_a_cloud_provider(self):
        india = {"infrastructure.data_residency": "india", "requirements.payments": True, "project.type": "fintech"}
        for desc, want in (("We run on a cloud provider. Merchant payouts to shops.", "merchants"),
                           ("We run on a cloud provider. Payouts to partner shops.", "recipients"),
                           ("Our hosting provider is fixed. Payouts go to shops.", "recipients"),
                           ("Payouts go to the providers of each service.", "service providers"),
                           ("Payouts go to the vendors we onboard.", "vendors")):
            out = run(BASE, desc, **india)
            pay = [s for s in out["stack"]["supporting"] if s["layer"] == "payments"][0]["choice"]
            self.assertIn("pay " + want, pay, desc)


class NegationScanIsBounded(unittest.TestCase):
    """The negation scan looks at a bounded window around each hit, so cost stays linear on long unpunctuated text."""

    def test_long_inputs_are_fast(self):
        for unit in ("not chat ", "no chat ", "n't chat ", "no messages ", "never lose a ledger ", "without kyc "):
            desc = (unit * (20000 // len(unit) + 1))[:20000]
            t = time.perf_counter()
            desc_signals(desc)
            self.assertLess(time.perf_counter() - t, 1.0, unit)

    def test_full_evaluate_with_long_description(self):
        for unit in ("not chat ", "no messages "):
            desc = (unit * 2222)[:20000]
            t = time.perf_counter()
            run(PUBLIC["P2"], extra=desc)
            self.assertLess(time.perf_counter() - t, 4.0, unit)


POINTS = re.compile(r"\b\d+(?:\.\d+)?\s+points\b|score points|points (?:behind|ahead|lower|higher)", re.I)


def strings(node, path=""):
    if isinstance(node, str):
        yield path, node
    elif isinstance(node, dict):
        for k, v in node.items():
            yield from strings(v, f"{path}.{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from strings(v, f"{path}[{i}]")


class NoScoreWordingInProse(unittest.TestCase):
    """Rule: prose says close call / clear lead, never a score number in points; the number stays in score_margin."""

    def test_no_points_in_any_output(self):
        files = sorted(glob.glob(os.path.join(ROOT, "scenarios", "stacksense_public_scenarios.json"))
                       + glob.glob(os.path.join(ROOT, "scenarios", "*", "*.json")))
        seen, hits = 0, []
        for fn in files:
            with open(fn, encoding="utf-8") as f:
                data = json.load(f)
            for sc in (data if isinstance(data, list) else [data]):
                out = evaluate(copy.deepcopy(sc), counterfactuals=False)
                seen += 1
                hits += [(fn, p, s[:120]) for p, s in strings(out) if POINTS.search(s)]
        self.assertGreaterEqual(seen, 40)
        self.assertEqual(hits, [])

    def test_low_end_mobile_fallback_has_no_number(self):
        out = evaluate(copy.deepcopy(PUBLIC["P6"]), counterfactuals=False)
        just = out["stack"]["frontend"]["justification"]
        self.assertIn("is the fallback if memory is tight", just)
        self.assertIsNone(POINTS.search(just))

    def test_skill_mismatch_warning_and_band_assumption_have_no_points(self):
        # language outside the band: the SKILL_MISMATCH warning; inside the band: the assumption line
        for langs, kw in ((["cobol"], {}), (["php"], {}), (["go"], {}), (["ruby"], {})):
            out = run(BASE, "Plain app.", **{"team.languages": langs, **kw})
            self.assertEqual([p for p, s in strings(out) if POINTS.search(s)], [], langs)

    def test_web_ui_has_no_score_points_text(self):
        with open(os.path.join(ROOT, "web", "index.html"), encoding="utf-8") as f:
            html = f.read()
        self.assertNotIn("score points", html.lower())
        self.assertIn("close call", html)


if __name__ == "__main__":
    unittest.main()
