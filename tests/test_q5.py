"""q5: a content site with owner-published media is still a static site (statement section 6, over-engineering traps:
"high traffic that is actually static"), plus description-lexicon fixes. Synthetic inputs only."""
import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_round9 import run, sup, codes  # noqa: E402
from engine import context as cx  # noqa: E402

SITE = {"project.type": "content_site", "requirements.auth": "none", "requirements.file_media_storage": True,
        "team.size": 1, "team.has_devops": False, "budget.monthly_infra_usd": 150,
        "scale.users_at_launch": 400000, "scale.users_12_months": 1200000, "scale.peak_concurrent_users": 20000,
        "scale.data_volume_gb_12_months": 300, "scale.traffic_pattern": "spiky", "scale.workload": "read_heavy"}


def site(desc, **kw):
    return run(**{**SITE, "project.description": desc, **kw})


def core(out):
    st = out["stack"]
    return st["backend"]["choice"], st["database"]["choice"]


def flags(text, *names):
    f = cx.desc_signals(text)[0]
    return [f[n] for n in names]


class PublishedMediaIsStatic(unittest.TestCase):
    """file_media_storage=true on a content site with no sign-in and no visitor uploads: media the owner publishes."""

    def check_static(self, out):
        self.assertEqual(core(out), ("None", "None"), out["summary"])
        self.assertEqual(out["architecture_style"] if "architecture_style" in out else "static", "static")
        st = sup(out, "storage")
        self.assertEqual(len(st), 1)
        j = st[0]["justification"]
        self.assertIn("site owner publishes", j)
        self.assertNotIn("signed upload/download", j)
        self.assertNotIn("go straight from clients", j)
        self.assertIn("requirements.file_media_storage", st[0]["driven_by"])
        self.assertTrue(any("site owner publishes" in a for a in out["assumptions"]))
        self.assertIn("visitor uploads", out["stack"]["backend"]["justification"])
        lines = out["estimated_monthly_cost_usd"]["assumptions"]
        self.assertTrue(any(a.startswith("Media delivery") for a in lines), lines)
        self.assertFalse(sup(out, "cache"))
        return st[0]

    def test_photo_portfolio(self):
        out = site("Portfolio of a travel photographer: galleries of large photos and a short bio.")
        self.check_static(out)

    def test_documentation_site_with_pdf_downloads(self):
        out = site("Product documentation with versioned guides and PDF manuals to download.", **{"requirements.full_text_search": True})
        self.check_static(out)
        self.assertIn("Pagefind", sup(out, "search")[0]["choice"])

    def test_news_site_with_images_at_high_traffic_fits_small_budget(self):
        out = site("Regional news site: articles with images, read by about a million people a month.")
        st = self.check_static(out)
        self.assertIn("Cloudflare R2", st["choice"])
        self.assertIn("no egress fee", st["justification"])
        self.assertNotIn("BUDGET_EXCEEDED", codes(out))
        self.assertLessEqual(out["estimated_monthly_cost_usd"]["max"], 150)

    def test_event_microsite_with_promo_video(self):
        out = site("Microsite for a design conference with the schedule, speaker pages and a promo video.",
                   **{"scale.users_12_months": 30000, "scale.users_at_launch": 5000, "scale.peak_concurrent_users": 800})
        st = self.check_static(out)
        self.assertIn("videos", st["justification"])

    def test_no_description_states_the_assumption(self):
        out = run(**{k: v for k, v in SITE.items()})
        self.check_static(out)

    def test_explicit_aws_prices_egress_on_cloudfront_tiers(self):
        out = site("Weekly radio show archive with audio files for every programme.", **{"infrastructure.cloud_preference": "aws"})
        st = self.check_static(out)
        self.assertIn("Amazon S3", st["choice"])
        line = next(a for a in out["estimated_monthly_cost_usd"]["assumptions"] if a.startswith("Media delivery"))
        self.assertIn("CloudFront", line)
        self.assertIn("Cloudflare R2", [a["choice"] for a in st["alternatives"]])

    # ---- must not fire
    def assert_backend(self, out):
        self.assertNotEqual(out["stack"]["backend"]["choice"], "None", out["summary"])
        self.assertFalse(any("site owner publishes" in a for a in out["assumptions"]))

    def test_visitor_uploads_keep_the_backend(self):
        self.assert_backend(site("Community recipe site: members upload photos of their dishes."))
        self.assert_backend(site("Local history archive where residents submit scanned photographs and stories."))
        self.assert_backend(site("Fan site with user-generated galleries."))

    def test_negated_visitor_upload_is_still_static(self):
        out = site("Museum collection site with high-resolution images. Visitors cannot upload anything.")
        self.assertEqual(core(out), ("None", "None"))

    def test_sign_in_keeps_the_backend(self):
        self.assert_backend(site("Magazine with image-rich articles for subscribers.", **{"requirements.auth": "email_password"}))

    def test_server_side_payments_keep_the_backend(self):
        self.assert_backend(site("Magazine with image-rich articles and paid issues.", **{"requirements.payments": True}))

    def test_other_types_unchanged(self):
        for typ in ("marketplace", "web_app", "social"):
            self.assert_backend(site("Listings with photos.", **{"project.type": typ}))

    def test_self_hosted_unchanged(self):
        self.assert_backend(site("Company knowledge pages with diagrams.", **{"infrastructure.deployment_model": "on_premise"}))

    def test_content_site_without_media_text_unchanged(self):
        out = site("Simple blog.", **{"requirements.file_media_storage": False})
        self.assertEqual(core(out), ("None", "None"))
        self.assertIn("payments, uploads or dynamic data", out["stack"]["backend"]["justification"])
        self.assertFalse(sup(out, "storage"))
        self.assertFalse(any(a.startswith("Media delivery") for a in out["estimated_monthly_cost_usd"]["assumptions"]))


class Lexicon(unittest.TestCase):
    def test_newsletter_signup_is_not_sending(self):
        for t in ("Show notes and a newsletter signup link.", "Footer has a mailing-list sign-up form.", "A link to our newsletter on every page.",
                  "Subscribe box for the newsletter in the sidebar."):
            self.assertEqual(flags(t, "email_out"), [False], t)

    def test_sending_wording_still_fires(self):
        for t in ("We send a weekly newsletter to 20,000 subscribers.", "Newsletter signup form; the app mails out a monthly newsletter.",
                  "Order confirmation emails go to buyers.", "Reminders are sent by email."):
            self.assertEqual(flags(t, "email_out"), [True], t)

    def test_no_email_line_for_a_signup_link(self):
        for typ, extra in (("content_site", {"requirements.auth": "none"}), ("web_app", {}), ("ecommerce", {"requirements.payments": True})):
            out = run(**{"project.type": typ, "project.description": "Catalogue pages and a newsletter signup link in the footer.", **extra})
            self.assertFalse([s for s in out["stack"]["supporting"] if s["choice"].startswith("Email delivery")], typ)
            self.assertFalse(any(a.startswith("Email") for a in out["estimated_monthly_cost_usd"]["assumptions"]), typ)

    def test_sms_wording(self):
        for t in ("Send text messages to patients the day before.", "Delivery updates by text.", "Parents get reminders via text message."):
            self.assertEqual(flags(t, "sms"), [True], t)
        for t in ("Users exchange text messages in group chats.", "Plain text editor for notes.", "We do not send text messages to customers."):
            self.assertEqual(flags(t, "sms"), [False], t)

    def test_live_video_sessions(self):
        for t in ("Clients join live video therapy sessions.", "Video counselling for students.", "Tutors run live video lessons."):
            self.assertEqual(flags(t, "video_call"), [True], t)
        for t in ("Editors import recorded video sessions.", "A promo video on the home page."):
            self.assertEqual(flags(t, "video_call"), [False], t)

    def test_game_tick_rate_is_not_time_series(self):
        for t in ("Authoritative servers simulate at 30 ticks per second.", "The server tick drives hit detection."):
            self.assertEqual(flags(t, "time_series"), [False], t)
        for t in ("Store market ticks for back-testing.", "Sensor readings every 10 seconds."):
            self.assertEqual(flags(t, "time_series"), [True], t)


if __name__ == "__main__":
    unittest.main()
