"""q4: the description is read against the structured fields (conflicts in both directions) and capabilities it names are
declared with a plan instead of being dropped silently. Synthetic inputs only."""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_round9 import run, sup, codes  # noqa: E402


def warn(out, code):
    return next((w for w in out["warnings"] if w["code"] == code), None)


class DescriptionAsksForWhatAFlagDenies(unittest.TestCase):
    def test_sign_in_wording_with_auth_none(self):
        for typ, desc in (("web_app", "Club members log in with their Google account to book courts."),
                          ("content_site", "Readers create an account to save articles."),
                          ("internal_tool", "Each technician has a password and sees only their own jobs.")):
            out = run(**{"project.type": typ, "project.description": desc, "requirements.auth": "none"})
            w = warn(out, "DESC_VS_FLAG_AUTH")
            self.assertTrue(w, (typ, codes(out)))
            self.assertEqual(w["severity"], "warning")
            self.assertIn("requirements.auth", w["fields"])
            self.assertFalse(sup(out, "auth"), "the flag is a hard input: no auth component is added")

    def test_sign_in_wording_must_not_fire(self):
        for desc in ("Visitors read the menu; nobody needs to sign in.", "Footer has a newsletter signup link.",
                     "Staff log in.",  # auth is set below
                     "A sign-up form for the volunteer day."):
            auth = "email_password" if desc.startswith("Staff") else "none"
            out = run(**{"project.type": "content_site", "project.description": desc, "requirements.auth": auth})
            self.assertNotIn("DESC_VS_FLAG_AUTH", codes(out), desc)

    def test_model_wording_with_ml_none(self):
        for typ, desc in (("internal_tool", "A trained classifier sorts incoming tickets into queues."),
                          ("ecommerce", "We train a recommendation model on past orders."),
                          ("iot", "Image recognition spots damaged parcels on the belt.")):
            out = run(**{"project.type": typ, "project.description": desc})
            w = warn(out, "DESC_VS_FLAG_ML")
            self.assertTrue(w, (typ, codes(out)))
            self.assertIn("requirements.ml_features", w["fields"])
            self.assertFalse(sup(out, "ml"))

    def test_model_wording_must_not_fire(self):
        for desc, ml in (("We train new staff on the till.", "none"), ("No machine learning is needed.", "none"),
                         ("A data model with orders and customers.", "none"), ("We train a churn model.", "training")):
            out = run(**{"project.description": desc, "requirements.ml_features": ml})
            self.assertNotIn("DESC_VS_FLAG_ML", codes(out), desc)

    def test_assistant_row_is_not_doubled(self):
        out = run(**{"project.description": "A chatbot built on a fine-tuned language model answers questions from our manuals."})
        self.assertIn("DESC_VS_FLAG_ASSISTANT", codes(out))
        self.assertNotIn("DESC_VS_FLAG_ML", codes(out))


class DescriptionDeniesWhatAFlagSets(unittest.TestCase):
    def test_no_payments_wording_with_payments_true(self):
        for typ, desc in (("marketplace", "Buyers contact the seller directly. We do not take any payments on the platform."),
                          ("web_app", "Booking tool for a community hall; no payments, the fee is settled in cash."),
                          ("saas_b2b", "Payments are out of scope for this release.")):
            out = run(**{"project.type": typ, "project.description": desc, "requirements.payments": True})
            w = warn(out, "DESC_DENIES_FLAG_PAYMENTS")
            self.assertTrue(w, (typ, codes(out)))
            self.assertEqual(w["severity"], "warning")
            self.assertIn("requirements.payments is true", w["message"])
            self.assertTrue(sup(out, "payments"), "the flag is a hard input: the payments component stays")
            self.assertEqual(out["status"], "ok_with_warnings")

    def test_no_payments_must_not_fire(self):
        for desc, pay in (("We do not take any payments.", False), ("No card payments, only UPI.", True),
                          ("Customers pay at checkout.", True), ("No payment gateway is chosen yet.", True)):
            out = run(**{"project.type": "ecommerce", "project.description": desc, "requirements.payments": pay})
            self.assertNotIn("DESC_DENIES_FLAG_PAYMENTS", codes(out), desc)

    def test_no_sign_in_wording_with_auth_set(self):
        out = run(**{"project.type": "content_site", "project.description": "Anyone can read the guides without logging in.",
                     "requirements.auth": "email_password"})
        w = warn(out, "DESC_DENIES_FLAG_AUTH")
        self.assertTrue(w, codes(out))
        self.assertIn("email_password", w["message"])
        out = run(**{"project.description": "Members sign in to see their bookings.", "requirements.auth": "email_password"})
        self.assertNotIn("DESC_DENIES_FLAG_AUTH", codes(out))


class NamedCapabilities(unittest.TestCase):
    def test_whatsapp_sent_by_the_app(self):
        out = run(**{"project.type": "healthtech", "project.description": "The clinic sends WhatsApp reminders the day before each appointment."})
        self.assertEqual(warn(out, "DESC_WHATSAPP_CHANNEL")["severity"], "info")
        out = run(**{"project.type": "internal_tool", "infrastructure.deployment_model": "on_premise",
                     "project.description": "Drivers are notified of route changes via WhatsApp."})
        w = warn(out, "WHATSAPP_EXTERNAL_SERVICE")
        self.assertEqual(w["severity"], "warning")
        self.assertIn("infrastructure.deployment_model", w["fields"])
        out = run(**{"project.type": "web_app", "infrastructure.deployment_model": "air_gapped", "requirements.auth": "none",
                     "project.description": "Shift supervisors get WhatsApp alerts when a line stops."})
        self.assertEqual(warn(out, "WHATSAPP_NEEDS_NETWORK")["severity"], "critical")

    def test_whatsapp_must_not_fire(self):
        for desc in ("Enquiries go out through a WhatsApp link.", "Orders come by WhatsApp today and are typed in by hand.",
                     "We do not send WhatsApp messages.", "Customers share the page in a WhatsApp group."):
            out = run(**{"project.description": desc})
            self.assertFalse([c for c in codes(out) if "WHATSAPP" in c], desc)

    def test_crash_reports(self):
        for typ, desc in (("gaming", "The game client uploads crash reports after a failure."), ("web_app", "We want error tracking for the mobile web app."),
                          ("iot", "Gateways send crash dumps to the server.")):
            self.assertTrue(warn(run(**{"project.type": typ, "project.description": desc}), "DESC_CRASH_REPORTING"), typ)
        self.assertNotIn("DESC_CRASH_REPORTING", codes(run(**{"project.description": "A crash course in statistics with weekly quizzes."})))

    def test_streaming_protection(self):
        for typ, desc in (("social", "Films play with adaptive-bitrate streaming and DRM against piracy."), ("web_app", "Course videos need Widevine and FairPlay."),
                          ("ecommerce", "We sell concert recordings and must prevent piracy.")):
            w = warn(run(**{"project.type": typ, "project.description": desc}), "DESC_STREAMING_PROTECTION")
            self.assertTrue(w, typ)
            self.assertEqual(w["severity"], "warning")
            self.assertIn("NOT covered", w["message"])
        self.assertNotIn("DESC_STREAMING_PROTECTION", codes(run(**{"project.description": "A promo video plays on the home page."})))

    def test_firmware_updates(self):
        for typ, desc in (("iot", "Meters receive OTA firmware updates."), ("internal_tool", "Technicians push new firmware to the kiosks remotely."),
                          ("web_app", "Over-the-air updates for the trackers are scheduled from the dashboard.")):
            self.assertTrue(warn(run(**{"project.type": typ, "project.description": desc}), "DESC_FIRMWARE_UPDATES"), typ)
        self.assertNotIn("DESC_FIRMWARE_UPDATES", codes(run(**{"project.description": "A rota for the night shift."})))

    def test_inbound_email(self):
        for typ, desc in (("internal_tool", "The tool reads incoming customer-support emails and files them as tickets."),
                          ("saas_b2b", "Invoices arrive in a shared mailbox and are parsed."), ("web_app", "We ingest inbound e-mails from suppliers.")):
            self.assertTrue(warn(run(**{"project.type": typ, "project.description": desc}), "DESC_INBOUND_EMAIL"), typ)
        for desc in ("Users enter an e-mail address to register.", "Order confirmation emails are sent to buyers."):
            self.assertNotIn("DESC_INBOUND_EMAIL", codes(run(**{"project.description": desc})), desc)


if __name__ == "__main__":
    unittest.main()


class ReviewFalsePositives(unittest.TestCase):
    """Review of q4: wording that only looks like a conflict or a capability stays silent; the real cases still fire."""

    def quiet(self, code, **kw):
        out = run(**kw)
        self.assertNotEqual(out["status"], "invalid_input", out.get("validation_errors"))
        self.assertFalse(warn(out, code), (code, kw.get("project.description")))

    def test_payments_handled_by_a_provider_are_not_denied(self):
        for d in ("We never process payments ourselves; Stripe Checkout handles card entry.",
                  "No payments are stored on our servers."):
            self.quiet("DESC_DENIES_FLAG_PAYMENTS", **{"project.type": "ecommerce", "requirements.payments": True, "project.description": d})
        out = run(**{"project.type": "marketplace", "requirements.payments": True, "project.description": "We do not take payments; buyers pay sellers in cash."})
        self.assertIn("DESC_DENIES_FLAG_PAYMENTS", codes(out))

    def test_sign_in_later_is_not_no_sign_in(self):
        out = run(**{"project.type": "ecommerce", "requirements.auth": "email_password",
                     "project.description": "Shoppers browse without an account and sign in only at checkout."})
        self.assertNotIn("DESC_DENIES_FLAG_AUTH", codes(out))

    def test_wifi_password_and_rule_based_recommendations(self):
        self.quiet("DESC_VS_FLAG_AUTH", **{"project.type": "content_site", "requirements.auth": "none",
                                         "project.description": "Cafe menu site; the Wi-Fi password is printed on each table."})
        out = run(**{"project.type": "ecommerce", "requirements.ml_features": "none",
                     "project.description": "A simple rule-based recommendation engine shows bestsellers from the same category."})
        self.assertNotIn("DESC_VS_FLAG_ML", codes(out))

    def test_capability_notes_need_the_capability(self):
        cases = (("marketplace", "Boutique hotel booking site; rooms are also listed on an OTA.", "DESC_FIRMWARE_UPDATES"),
                 ("ecommerce", "Customers message us on WhatsApp with questions.", "DESC_WHATSAPP_CHANNEL"),
                 ("ecommerce", "Checkout processing payments and email receipts.", "DESC_INBOUND_EMAIL"),
                 ("saas_b2b", "We monitor email deliverability for campaigns.", "DESC_INBOUND_EMAIL"),
                 ("fintech", "Daily exception reporting for unmatched ledger entries.", "DESC_CRASH_REPORTING"))
        for typ, d, word in cases:  # word = the code that must not fire
            with self.subTest(d=d):
                out = run(**{"project.type": typ, "project.description": d})
                self.assertNotEqual(out["status"], "invalid_input")
                self.assertNotIn(word, codes(out))


    def test_real_capabilities_still_noted(self):
        for typ, d, code in (("iot", "Thermostats receive OTA firmware updates every month.", "DESC_FIRMWARE_UPDATES"),
                             ("healthtech", "The clinic sends appointment reminders via WhatsApp.", "DESC_WHATSAPP_CHANNEL"),
                             ("saas_b2b", "We parse incoming support emails into tickets.", "DESC_INBOUND_EMAIL"),
                             ("gaming", "The game collects crash reports from users' phones.", "DESC_CRASH_REPORTING")):
            with self.subTest(d=d):
                self.assertIn(code, codes(run(**{"project.type": typ, "project.description": d})))
