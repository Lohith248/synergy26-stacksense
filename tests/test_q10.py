"""q10: two wording gaps measured on paraphrase twins. (1) "WhatsApp appointment reminders" (a word between the channel and the
message noun) is an app-sent WhatsApp message like "WhatsApp reminders". (2) "text messages sent through <provider>" is SMS.
Synthetic inputs only."""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_round9 import run, codes  # noqa: E402
from engine import context as cx  # noqa: E402


def warn(out, code):
    return next((w for w in out["warnings"] if w["code"] == code), None)


def sms(text):
    return cx.desc_signals(text)[0]["sms"]


class WhatsAppWithAWordBetween(unittest.TestCase):
    def test_on_premise_is_an_external_service_warning(self):
        for typ, desc in (("healthtech", "Management wants patients to get WhatsApp appointment reminders."),
                          ("internal_tool", "Supervisors receive WhatsApp shift alerts when a machine stops."),
                          ("ecommerce", "Buyers get WhatsApp order confirmations after checkout.")):
            out = run(**{"project.type": typ, "project.description": desc, "infrastructure.deployment_model": "on_premise",
                         "infrastructure.cloud_preference": "none"})
            w = warn(out, "WHATSAPP_EXTERNAL_SERVICE")
            self.assertTrue(w, (typ, codes(out)))
            self.assertEqual(w["severity"], "warning")

    def test_cloud_is_an_info_note_and_air_gapped_is_critical(self):
        out = run(**{"project.type": "web_app", "project.description": "Members get WhatsApp class reminders."})
        self.assertEqual(warn(out, "DESC_WHATSAPP_CHANNEL")["severity"], "info")
        out = run(**{"project.type": "web_app", "project.description": "Members get WhatsApp class reminders.", "requirements.auth": "none",
                     "infrastructure.deployment_model": "air_gapped", "infrastructure.cloud_preference": "none"})
        self.assertEqual(warn(out, "WHATSAPP_NEEDS_NETWORK")["severity"], "critical")

    def test_must_not_fire(self):
        for desc in ("Customers share the page in a WhatsApp group and send messages there.",
                     "Enquiries go out through a WhatsApp link, with reminders by e-mail.",
                     "A WhatsApp number is printed on the receipt; alerts are shown in the app.",
                     "Orders come by WhatsApp today and are typed in by hand.",
                     "We do not send WhatsApp appointment reminders.",
                     "The chat looks like WhatsApp, with read receipts."):
            out = run(**{"project.description": desc})
            self.assertFalse([c for c in codes(out) if "WHATSAPP" in c], desc)


class TextMessagesSentThroughAProvider(unittest.TestCase):
    def test_sms_wording(self):
        for t in ("Supervisors also want text messages sent through Twilio.",
                  "Appointment text messages are sent via an SMS gateway.",
                  "Delivery text messages go out through MSG91."):
            self.assertTrue(sms(t), t)

    def test_must_not_fire(self):
        for t in ("Users exchange text messages in group chats.",
                  "Text messages sent through the in-app chat are end-to-end encrypted.",
                  "Text messages sent by users are stored for 30 days.",
                  "We do not want text messages sent through Twilio.",
                  "Plain text editor for notes."):
            self.assertFalse(sms(t), t)


if __name__ == "__main__":
    unittest.main()
