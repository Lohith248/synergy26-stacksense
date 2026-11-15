"""p5 (Fable review): remove false statements a judge marks down; synthetic inputs only."""
import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_round9 import run, sup, codes  # noqa: E402


def text(out):
    return json.dumps(out, ensure_ascii=False)


class PaymentProviderItself(unittest.TestCase):
    """Item 1: a gateway / processor / switch is the payment provider: no merchant checkout, no SAQ A, network link in scope."""

    def test_provider_shapes(self):
        cases = [
            ("fintech", "Payment gateway for online merchants: we store and process card data, tokenise cards and route payments to acquiring banks.", ["pci_dss"]),
            ("fintech", "UPI and IMPS payment switch for cooperative banks: connects member banks to NPCI, routes and settles transactions.", []),
            ("other", "Card processor for regional banks: authorises card transactions from POS terminals and routes them to Visa and Mastercard.", ["pci_dss"]),
            ("api_platform", "Payments API that connects small lenders to the card networks and settles card repayments.", []),
        ]
        for typ, desc, comp in cases:
            out = run(**{"project.type": typ, "project.description": desc, "requirements.payments": True, "compliance": comp})
            pay = sup(out, "payments")
            self.assertEqual(len(pay), 1, desc)
            self.assertIn("In-house payment core", pay[0]["choice"], desc)
            self.assertNotIn("Stripe (Checkout)", pay[0]["choice"])
            self.assertNotIn("Razorpay (UPI", pay[0]["choice"])
            self.assertNotIn("can qualify for PCI DSS SAQ A", pay[0]["justification"])
            self.assertIn("part of this design", pay[0]["justification"])
            self.assertNotRegex(text(out), r"official-unverified|not confirmed in the knowledge base|source mastercard-sdp", desc)  # item 0

    def test_scheme_link_is_in_scope(self):
        out = run(**{"project.type": "fintech", "requirements.payments": True, "infrastructure.existing_systems": ["Visa network link (legacy)"],
                     "project.description": "Card processor for credit unions that routes card transactions to card networks."})
        self.assertNotIn("assumed to sit outside this design", text(out))

    def test_shops_keep_hosted_checkout(self):
        for typ, desc in (("ecommerce", "Online store for a weavers' cooperative; UPI and card payments through a payment gateway."),
                          ("marketplace", "Marketplace where designers sell templates; buyers pay by card and sellers get payouts."),
                          ("web_app", "Event ticketing site; we never store card data, the gateway's checkout does.")):
            out = run(**{"project.type": typ, "project.description": desc, "requirements.payments": True})
            pay = sup(out, "payments")
            self.assertTrue(pay and "In-house payment core" not in pay[0]["choice"], desc)


class MobileMoney(unittest.TestCase):
    """Item 2: mobile-money wallets need a mobile-money API or aggregator, not a card checkout; East Africa is not South Africa."""

    def test_wallet_payments(self):
        for typ, desc in (("fintech", "Savings-group app for chamas in Kenya: members contribute through M-Pesa."),
                          ("web_app", "School-fees portal for schools in Uganda; parents pay with MTN MoMo or Airtel Money."),
                          ("ecommerce", "Grocery delivery shop in East Africa accepting mobile money payments at checkout."),
                          ("other", "Offline-first point-of-sale app for kiosks in Tanzania that accepts mobile-money payments.")):
            out = run(**{"project.type": typ, "project.description": desc, "requirements.payments": True, "infrastructure.data_residency": "other"})
            pay = sup(out, "payments")
            self.assertEqual(len(pay), 1, desc)
            self.assertIn("Mobile-money", pay[0]["choice"], desc)
            self.assertNotEqual(pay[0]["provider"], "stripe")
            self.assertNotIn("SAQ A", pay[0]["justification"])
            self.assertNotIn("South Africa", text(out), desc)

    def test_card_shop_keeps_gateway(self):
        out = run(**{"project.type": "ecommerce", "project.description": "Online bookshop in Cape Town, South Africa, taking card payments.",
                     "requirements.payments": True, "infrastructure.data_residency": "other"})
        self.assertNotIn("Mobile-money", sup(out, "payments")[0]["choice"])
        self.assertIn("South Africa", text(out))


class LiveQuizWording(unittest.TestCase):
    """Item 3: a live timed quiz is not turn-based; a p95 target under the threshold is never contradicted."""

    def test_live_quiz(self):
        for desc, lat in (("Live multiplayer trivia quiz: players answer timed questions at the same moment.", 80),
                          ("Quiz show app where thousands answer each question within 10 seconds simultaneously.", 150),
                          ("Classroom quiz game played live: the teacher starts a countdown and pupils buzz in.", 90)):
            out = run(**{"project.type": "gaming", "project.description": desc, "requirements.realtime": True, "requirements.p95_latency_ms": lat})
            t = text(out)
            self.assertNotIn("turn-based", t, desc)
            self.assertIn("live, timed quiz", t, desc)
            if lat <= 100:
                self.assertNotIn("needs p95 latency of 100 ms or less", t, desc)

    def test_turn_based_kept(self):
        out = run(**{"project.type": "gaming", "project.description": "Trivia game where friends take their turns whenever they like.",
                     "requirements.realtime": True, "requirements.p95_latency_ms": 300})
        self.assertIn("turn-based", text(out))


class GpuCount(unittest.TestCase):
    """Item 4: more than ~730 GPU-hours a month is never priced on one GPU."""

    def _basis(self, typ, gb):
        out = run(**{"project.type": typ, "project.description": "Train a model on the collected data and retrain it every week.",
                     "requirements.ml_features": "training", "scale.data_volume_gb_12_months": gb, "budget.monthly_infra_usd": 20000})
        return text(out)

    def test_many_hours_name_gpu_count(self):
        for typ, gb in (("ai_ml_product", 60000), ("data_analytics", 40000), ("iot", 20000)):
            t = self._basis(typ, gb)
            self.assertIn("T4-class GPUs in parallel", t, typ)
            self.assertNotRegex(t, r"\d,\d{3} GPU-hours a month on one ", typ)

    def test_small_job_one_gpu(self):
        self.assertIn("on one T4-class GPU", self._basis("ai_ml_product", 200))

    def test_helper(self):
        from engine import costreal
        self.assertEqual(costreal.gpu_count_text(100, 700, "T4-class"), "on one T4-class GPU")
        self.assertIn("across 2-7 T4-class GPUs", costreal.gpu_count_text(1200, 4800, "T4-class"))


class WrittenDatabaseIsKept(unittest.TestCase):
    """Item 8: an existing database the app must read and write stays the system of record (reused as the database layer)."""

    def _db(self, typ, desc, systems, langs=("java", "sql")):
        out = run(**{"project.type": typ, "project.description": desc, "infrastructure.existing_systems": systems,
                     "team.languages": list(langs)})
        return out["stack"]["database"]

    def test_write_path_reuses(self):
        cases = [
            ("internal_tool", "Claims screens for back-office staff. Must read and write the existing Oracle policy database.", ["Oracle Database 19c (policy data)"]),
            ("saas_b2b", "Customer portal that writes orders back to our SQL Server ERP database.", ["Microsoft SQL Server 2019 (ERP)"]),
            ("ecommerce", "Storefront that reads and writes stock levels in the existing MySQL inventory database.", ["MySQL 8.0 inventory database"]),
            ("web_app", "Field inspection app for municipal staff.", ["PostgreSQL 15 (read/write by the new app)"]),
        ]
        for typ, desc, systems in cases:
            db = self._db(typ, desc, systems)
            self.assertIn("reused", db["choice"], desc)
            self.assertIn("system of record", db["justification"], desc)

    def test_read_only_or_leaving_not_kept(self):
        cases = [
            ("internal_tool", "Dashboard that reads the existing Oracle policy database nightly.", ["Oracle Database 19c"]),
            ("saas_b2b", "We migrate off the existing MySQL database; the new app must read and write a new store.", ["MySQL 5.7 (to be retired)"]),
            ("data_analytics", "Reports read and write a reporting copy of the Oracle database.", ["Oracle Database 19c"]),
        ]
        for typ, desc, systems in cases:
            self.assertNotIn("reused", self._db(typ, desc, systems)["choice"], desc)


class ProviderCdnAndCognitoTiers(unittest.TestCase):
    """Item 6: CDN egress priced on the chosen provider's own CDN tiers; Cognito per-MAU tiers at very large user counts."""

    def _video(self, typ, cloud, res, users=20000000):
        out = run(**{"project.type": typ, "project.description": "Users upload and watch short videos.", "infrastructure.cloud_preference": cloud,
                     "infrastructure.data_residency": res, "scale.users_12_months": users, "requirements.file_media_storage": True,
                     "budget.monthly_infra_usd": 50000})
        return next(a for a in out["estimated_monthly_cost_usd"]["assumptions"] if a.startswith("Video egress"))

    def test_own_cdn_tiers(self):
        self.assertIn("Amazon CloudFront pay-as-you-go", self._video("social", "aws", "us"))
        self.assertIn("Azure Front Door edge-to-client", self._video("content_site", "azure", "india"))
        self.assertIn("Amazon CloudFront pay-as-you-go", self._video("ai_ml_product", "aws", "india", 5000000))

    def test_gcp_keeps_reference(self):
        self.assertIn("Google Cloud CDN cache egress tiers", self._video("social", "gcp", "us"))

    def test_tier_math(self):
        from engine import costreal
        t = costreal.provider_tiers("aws", "us")
        self.assertAlmostEqual(costreal.tiered_egress(1024, t), 0.0)
        self.assertAlmostEqual(costreal.tiered_egress(2048, t), 1024 * 0.085)
        self.assertEqual(costreal.provider_tiers("cloudflare", "us"), None)

    def test_cognito_large(self):
        for typ in ("social", "ecommerce", "saas_b2b"):
            out = run(**{"project.type": typ, "project.description": "Members sign in.", "infrastructure.cloud_preference": "aws",
                         "scale.users_12_months": 20000000, "requirements.auth": "email_password", "budget.monthly_infra_usd": 100000})
            line = next(a for a in out["estimated_monthly_cost_usd"]["assumptions"] if "Cognito" in a)
            self.assertIn("lower bound counts only the first 1,000,000 MAU", line, typ)
            self.assertNotIn("$300-2,000", line)


class FrontDoorWafTier(unittest.TestCase):
    """Item 7: managed WAF rule sets need Front Door Premium; Standard gets custom rules; no 'CDN not added' beside Front Door."""

    def _run(self, typ, desc, budget, users=2000):
        return run(**{"project.type": typ, "project.description": desc, "requirements.payments": True, "compliance": ["pci_dss"],
                      "infrastructure.cloud_preference": "azure", "budget.monthly_infra_usd": budget, "scale.users_12_months": users})

    def _sec(self, out):
        return next(s for s in out["stack"]["supporting"] if "Front Door" in s["choice"] and s["layer"] == "other")

    def test_premium_when_budget_allows(self):
        for typ, desc in (("fintech", "Wallet app for small merchants."), ("ecommerce", "Online store for handmade goods."),
                          ("saas_b2b", "Invoicing SaaS that takes card payments.")):
            sec = self._sec(self._run(typ, desc, 5000))
            self.assertIn("Premium", sec["choice"], desc)
            self.assertIn("$330/month", sec["justification"])

    def test_standard_custom_rules_on_small_budget(self):
        sec = self._sec(self._run("ecommerce", "Online store for handmade goods.", 500))
        self.assertIn("Standard WAF (custom rules)", sec["choice"])
        self.assertNotIn("managed rule sets plus", sec["justification"])

    def test_no_cdn_not_added_beside_front_door(self):
        out = self._run("fintech", "Internal treasury tool for the finance staff of one company; staff sign in, no public pages.", 5000, users=20000)
        self.assertTrue(any("Front Door" in s["choice"] for s in out["stack"]["supporting"]))
        self.assertFalse([w for w in out["warnings"] if w["code"] == "SERVICE_NOT_ADDED" and w["message"].startswith("CDN not added")])


class StaffOnlySignIn(unittest.TestCase):
    """Item 5: anonymous readers, staff-only sign-in: auth is sized for the staff; the scope-cut sentence agrees with the band."""

    def _run(self, typ, desc, auth="phone_otp", cloud="gcp"):
        return run(**{"project.type": typ, "project.description": desc, "requirements.auth": auth, "infrastructure.cloud_preference": cloud,
                      "scale.users_12_months": 2000000, "scale.users_at_launch": 500000, "budget.monthly_infra_usd": 3000})

    def _otp(self, out):
        return next(a for a in out["estimated_monthly_cost_usd"]["assumptions"] if a.startswith("Phone OTP"))

    def test_staff_sized(self):
        cases = [("content_site", "Regional news site. Editors log in to a CMS; readers do not log in.", "100 staff"),
                 ("other", "Podcast site for a public radio show; listeners don't need accounts. 12 producers sign in to publish episodes.", "12 staff"),
                 ("web_app", "Public notices portal for a city: citizens do not register; 40 officers and admins log in to post notices.", "40 staff")]
        for typ, desc, want in cases:
            self.assertIn(want, self._otp(self._run(typ, desc)), desc)

    def test_cognito_mau_staff(self):
        staff = self._run("content_site", "Magazine site with anonymous readers; 25 editors log in.", auth="email_password", cloud="aws")
        everyone = self._run("content_site", "Magazine site; 25 editors log in and readers log in to save articles.", auth="email_password", cloud="aws")
        self.assertLess(staff["estimated_monthly_cost_usd"]["min"], everyone["estimated_monthly_cost_usd"]["min"])

    def test_readers_log_in_not_fired(self):
        out = self._run("content_site", "News site where editors log in and readers log in to comment.")
        self.assertIn("2,000,000 users", self._otp(out))

    def test_scope_cut_agrees_with_band(self):
        from engine import costreal
        within = costreal.over_multiple_note([(5000, 200, "CDN")], 300, band_min=250)
        self.assertNotIn("no scope cut", within)
        self.assertIn("low end of the band", within)
        self.assertIn("other lines must shrink", costreal.over_multiple_note([(5000, 200, "CDN")], 300, band_min=900))
        self.assertIn("no scope cut", costreal.over_multiple_note([(5000, 400, "CDN")], 300, band_min=900))


class ReviewP5aFixes(unittest.TestCase):
    """REVIEW-p5a MUST 1-5 and SHOULD items: a shop that uses a provider is not the provider; poker is not a quiz."""

    def _pay(self, desc, typ="ecommerce"):
        return sup(run(**{"project.type": typ, "project.description": desc, "requirements.payments": True}), "payments")[0]

    def test_psp_regex_pos_neg(self):
        from engine import descflags as dfl, compnotes as cn
        hit = lambda d: dfl.first_live(cn.PSP_RX, d)
        # MUST 1: connecting to Visa/Mastercard needs a provider word in the clause
        self.assertIsNone(hit("Loyalty app that connects with Visa and Mastercard card-linked offers."))
        self.assertTrue(hit("Payments API that connects small lenders to Visa and Mastercard and settles card repayments."))
        self.assertTrue(hit("Acquirer platform that connects merchants with Mastercard."))
        # MUST 2: a vendor named after 'payment processor' is the shop's provider
        self.assertIsNone(hit("Payment processor Stripe handles cards for our candle shop."))
        self.assertTrue(hit("Payment processor for regional banks and their merchants."))
        # MUST 3: a vendor (or 'for us') storing card data is not this system storing it
        self.assertIsNone(hit("Candle shop; Stripe stores card data for us."))
        self.assertIsNone(hit("Online shop; the payment provider stores card data."))
        self.assertTrue(hit("Billing engine for clinics: we store and process card data in our own vault."))

    def test_shops_end_to_end(self):
        for d in ("Loyalty app that connects with Visa and Mastercard card-linked offers.",
                  "Payment processor Stripe handles cards for our candle shop.",
                  "Candle shop; Stripe stores card data for us."):
            self.assertNotIn("In-house payment core", self._pay(d, "web_app")["choice"], d)

    def test_payfac_sponsor_acquirer(self):
        p = self._pay("Payment facilitator that onboards small merchants and processes their card payments.", "fintech")
        self.assertIn("In-house payment core", p["choice"])
        self.assertIn("sponsor acquirer", p["choice"])
        self.assertNotIn("direct connection", p["choice"])
        self.assertIn("direct connection", self._pay("Card processor for regional banks that routes card transactions to card networks.", "fintech")["choice"])

    def test_momo_shop_name(self):
        from engine import descflags as dfl, compnotes as cn
        self.assertIsNone(dfl.first_live(cn.MOBILE_MONEY_RX, "Toy shop called MoMo Kids, card payments."))
        self.assertTrue(dfl.first_live(cn.MOBILE_MONEY_RX, "Parents pay with MoMo for school fees."))

    def test_poker_not_quiz(self):
        out = run(**{"project.type": "gaming", "project.description": "Live multiplayer card game (poker) with real-time tables.",
                     "requirements.realtime": True, "requirements.p95_latency_ms": 150})
        self.assertNotIn("live, timed quiz", text(out))
        out = run(**{"project.type": "gaming", "project.description": "Live trivia night with timed questions.",
                     "requirements.realtime": True, "requirements.p95_latency_ms": 150})
        self.assertIn("live, timed quiz", text(out))

    def test_no_status_jargon(self):
        out = run(**{"project.type": "realtime_collab", "project.description": "Live collaborative whiteboard.", "requirements.realtime": True,
                     "infrastructure.cloud_preference": "azure", "scale.users_12_months": 200000})
        self.assertNotIn("official-unverified", text(out))
        self.assertNotIn("official-unverified", text(run(**{"project.type": "fintech", "requirements.payments": True, "compliance": ["pci_dss"],
                                                          "project.description": "Card processor for credit unions that routes card transactions to card networks."})))

    def test_eastern_africa(self):
        out = run(**{"project.type": "ecommerce", "project.description": "Grocery shop serving customers across eastern Africa, card payments.",
                     "requirements.payments": True, "infrastructure.data_residency": "other"})
        self.assertNotIn("South Africa", text(out))
        out = run(**{"project.type": "ecommerce", "project.description": "Grocery shop serving customers across Africa, card payments.",
                     "requirements.payments": True, "infrastructure.data_residency": "other"})
        self.assertIn("South Africa", text(out))


if __name__ == "__main__":
    unittest.main()
