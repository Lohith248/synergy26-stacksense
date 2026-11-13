"""Track f2, A1: requested hype is declined with the numbers and the stack chosen; the web3 flag is not set by a wish.
Synthetic inputs only: no scenario ids or product titles."""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_round9 import run, sup, codes  # noqa: E402

SMALL = {"scale.users_at_launch": 200, "scale.users_12_months": 900, "scale.peak_concurrent_users": 40,
         "team.size": 2, "budget.monthly_infra_usd": 150}
DECLINED = "OVERENGINEERING_REQUEST_DECLINED"


def warn(out, code):
    return [w for w in out["warnings"] if w["code"] == code]


def others(out):
    return [s["choice"] for s in sup(out, "other")]


class HypeDeclined(unittest.TestCase):
    CASES = [
        ("internal_tool", "Shift swap board for 60 nurses. The CTO has asked for blockchain shift records and microservices on k8s, 'for a modern look'."),
        ("web_app", "Booking pages for a yoga studio. The director read about big-tech architecture and wants microservices and Kubernetes to be future proof."),
        ("saas_b2b", "Invoice reminders for small firms. The board would like an AI agent that chases late payers."),
        ("content_site", "Local news archive with search. Our manager suggested Kubernetes because it is trendy."),
    ]

    def test_fires_for_four_project_types_with_numbers_and_the_stack_chosen(self):
        for typ, desc in self.CASES:
            out = run(**{**SMALL, "project.type": typ, "project.description": desc})
            w = warn(out, DECLINED)
            self.assertEqual(len(w), 1, (typ, codes(out)))
            self.assertEqual(w[0]["severity"], "info")
            self.assertEqual(w[0]["fields"], ["project.description", "scale.peak_concurrent_users"])
            self.assertIn("900 users", w[0]["message"])
            self.assertIn("The stack chosen instead is", w[0]["message"])
            self.assertIn(out["stack"]["backend"]["choice"], w[0]["message"])

    def test_blockchain_wish_adds_no_on_chain_component_or_crypto_caution(self):
        out = run(**{**SMALL, "project.type": "internal_tool",
                     "project.description": "Lunch pre-order for staff. The CTO has asked for blockchain receipts; the real need is a daily pick-list."})
        self.assertNotIn("WEB3_CAUTION", codes(out))
        self.assertFalse([c for c in others(out) if "On-chain" in c])
        self.assertIn("blockchain", warn(out, DECLINED)[0]["message"])

    def test_scalability_five_is_explained_not_built(self):
        out = run(**{**SMALL, "project.description": "Club roster tool. The director wants microservices.", "priorities.scalability": 5})
        self.assertIn("priorities.scalability is 5", warn(out, DECLINED)[0]["message"])

    def test_not_declined_when_not_requested_or_justified(self):
        quiet = [
            ("Warehouse tool. We do not need Kubernetes or microservices; one server is enough.", {}),
            ("Reports portal. The existing system runs on Kubernetes and the director wants it kept.",
             {"infrastructure.existing_systems": ["Kubernetes cluster (existing)"]}),
            ("Support desk. The director asked for an AI agent to draft answers.", {"requirements.ml_features": "llm_rag"}),
            ("Club site. The CTO wants microservices and Kubernetes.",
             {"scale.users_at_launch": 200000, "scale.users_12_months": 900000, "scale.peak_concurrent_users": 30000,
              "budget.monthly_infra_usd": 20000, "team.size": 12}),
            ("Plain member directory with email login.", {}),
        ]
        for desc, extra in quiet:
            out = run(**{**SMALL, "project.description": desc, **extra})
            self.assertEqual(warn(out, DECLINED), [], desc)

    def test_review_f2_fixes(self):
        big = {"scale.users_at_launch": 2000000, "scale.users_12_months": 5000000, "scale.peak_concurrent_users": 200000,
               "team.size": 25, "budget.monthly_infra_usd": 50000}
        # B1: a large project keeps what its stakeholder asked for (on-chain component and caution), no decline at that scale
        for typ in ("web_app", "saas_b2b", "internal_tool"):
            out = run(**{**big, "project.type": typ, "project.description": "The board wants blockchain receipts for every purchase."})
            self.assertIn("WEB3_CAUTION", codes(out), typ)
            self.assertEqual(warn(out, DECLINED), [], typ)
        # B2 / B3: leaving a technology, or reading about it, is not asking for it
        for desc in ["The CTO wants to migrate off Kubernetes.", "The director wants to avoid microservices.",
                     "The board wants to get rid of the old blockchain ledger.", "Our founder wants to stop using Kubernetes.",
                     "Managers read the AI agent transcripts exported by the support desk.",
                     "The CTO heard about microservices at a conference but nothing was decided."]:
            self.assertEqual(warn(run(**{**SMALL, "project.description": desc}), DECLINED), [], desc)
        # ... while replacing something WITH the technology is still a request
        self.assertTrue(warn(run(**{**SMALL, "project.description": "The CTO wants to replace the single server with Kubernetes."}), DECLINED))
        # N1: first-person and founder / client / customer / owner requests are declined at small scale only
        for typ, desc in [("web_app", "We want microservices and Kubernetes."), ("saas_b2b", "Our founder needs an AI agent in the first release."),
                          ("internal_tool", "The client insists on microservices."), ("content_site", "The owner wants Kubernetes.")]:
            out = run(**{**SMALL, "project.type": typ, "project.description": desc})
            w = warn(out, DECLINED)
            self.assertEqual(len(w), 1, desc)
        self.assertEqual(warn(run(**{**SMALL, "project.description": "We want microservices and Kubernetes.", **{
            "scale.users_at_launch": 200000, "scale.users_12_months": 900000, "scale.peak_concurrent_users": 30000,
            "budget.monthly_infra_usd": 20000, "team.size": 12}}), DECLINED), [])
        for desc in ["We do not need Kubernetes.", "We run the club roster; customers pay by card.", "Customers want fast pages, and the site is small."]:
            self.assertEqual(warn(run(**{**SMALL, "project.description": desc}), DECLINED), [], desc)

    def test_decline_message_has_no_doubled_colon(self):
        out = run(**{**SMALL, "project.description": "The CTO wants Kubernetes."})
        msg = warn(out, DECLINED)[0]["message"]
        self.assertNotIn("): Kubernetes:", msg)
        self.assertIn("a team of 2, Kubernetes: ", msg)

    def test_real_web3_products_still_get_on_chain_access(self):
        for typ, desc in [("marketplace", "Collectors mint and trade NFTs; users connect a wallet and ownership is read from the blockchain."),
                          ("gaming", "Card game where players own NFT cards on a public blockchain."),
                          ("marketplace", "The CTO wants an NFT marketplace where artists mint and sell tokens."),
                          ("web_app", "Ticketing with NFT tickets minted on a blockchain; users sign in with wallet connect.")]:
            out = run(**{**SMALL, "project.type": typ, "project.description": desc, "requirements.payments": True})
            self.assertIn("WEB3_CAUTION", codes(out), desc)
            self.assertTrue([c for c in others(out) if "On-chain" in c], desc)
            for w in warn(out, DECLINED):
                self.assertNotIn("asks for blockchain", w["message"], desc)


if __name__ == "__main__":
    unittest.main()
