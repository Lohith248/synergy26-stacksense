"""F4/A5 (blind8): a subscription or purchase sold through the app stores on a mobile client is billed by the stores, whatever the
project type; Stripe per-seat wording only for a B2B SaaS or a description that prices per seat or team.
Each rule is tested on several project types plus inputs where it must not fire. Inputs are inline."""
import copy
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from engine.run import evaluate  # noqa: E402

BASE = {"scenario_id": "F4A5", "project": {"type": "other", "platforms": ["android", "ios"], "description": "x"},
        "scale": {"users_at_launch": 800, "users_12_months": 6000, "peak_concurrent_users": 150},
        "team": {"size": 3, "experience": "intermediate", "languages": ["typescript"], "has_devops": False},
        "budget": {"monthly_infra_usd": 300}, "timeline": {"mvp_weeks": 14},
        "infrastructure": {"cloud_preference": "any", "deployment_model": "managed_cloud", "data_residency": "none", "existing_systems": []},
        "requirements": {"auth": "email_password", "payments": True}}


def run(desc, typ="other", plats=("android", "ios")):
    s = copy.deepcopy(BASE)
    s["project"].update(type=typ, platforms=list(plats), description=desc)
    return evaluate(s, counterfactuals=False)


def pay(out):
    return [s for s in out["stack"]["supporting"] if s["layer"] == "payments"]


class StoreBilling(unittest.TestCase):
    def test_subscription_through_the_app_stores_uses_store_billing(self):
        cases = (("other", "Music practice tracker. Monthly subscription through the app stores."),
                 ("ai_ml_product", "Language tutor with AI feedback for students. The premium plan is billed via the Play Store and the App Store."),
                 ("social", "Photo journal for friends. Pro pass sold on the App Store and Google Play."),
                 ("web_app", "Meditation timer with a yearly subscription charged in the app stores."),
                 ("marketplace", "Second-hand books in a local area. Optional premium plan purchased through the app stores."))
        for typ, desc in cases:
            with self.subTest(typ=typ):
                p = pay(run(desc, typ))
                self.assertTrue(p, typ)
                self.assertIn("Google Play Billing", p[0]["choice"])
                self.assertIn("StoreKit", p[0]["choice"])
                self.assertNotIn("Stripe Billing", p[0]["choice"])
                self.assertIn("project.description", p[0]["driven_by"])

    def test_web_in_the_platforms_adds_a_gateway_for_web_purchases_only(self):
        p = pay(run("Habit tracker. Monthly subscription through the app stores.", "other", ("android", "ios", "web")))
        self.assertIn("for web purchases", p[0]["choice"])

    def test_store_route_not_named_or_not_mobile_does_not_fire(self):
        cases = (("Users pay by card; the app is published in the app stores.", "other", ("android", "ios")),
                 ("Free app available in the app stores and a card subscription for the web version.", "web_app", ("android", "ios")),
                 ("Ride marketplace with in-app payments to drivers.", "marketplace", ("android", "ios")),
                 ("Monthly subscription through the app stores.", "other", ("web",)),
                 ("Store listing needs screenshots; subscription by card.", "social", ("android", "ios")))
        for desc, typ, plats in cases:
            with self.subTest(desc=desc):
                p = pay(run(desc, typ, plats))
                self.assertTrue(p)
                self.assertNotIn("Google Play Billing", p[0]["choice"])


class SeatWording(unittest.TestCase):
    def test_per_seat_only_for_b2b_saas_or_seat_pricing(self):
        for typ, desc in (("saas_b2b", "Project tool for agencies with a monthly subscription."),
                          ("other", "Time sheets for teams, subscription priced per seat."),
                          ("web_app", "Reporting tool with a team subscription billed monthly.")):
            with self.subTest(typ=typ):
                self.assertIn("per-seat", pay(run(desc, typ, ("web",)))[0]["choice"])

    def test_consumer_subscription_has_no_seat_wording(self):
        for typ, desc in (("other", "Podcast hosting where creators sell paid subscriptions."),
                          ("social", "A hobby network with a monthly subscription for supporters."),
                          ("web_app", "Recipe site with a recurring supporter membership.")):
            with self.subTest(typ=typ):
                c = pay(run(desc, typ, ("web",)))[0]["choice"]
                self.assertNotIn("per-seat", c)
                self.assertIn("Stripe Billing for recurring subscriptions", c)


if __name__ == "__main__":
    unittest.main()
