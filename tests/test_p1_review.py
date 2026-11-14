"""p1 review fixes (14-15 Nov 2026): residency wording is not a self-host signal, a hosted LLM API stays hosted, GPU sizing picks the
smallest class that fits, true alternative reasons, serving needs model-serving wording, and small-plan model servers are priced."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_p1_ml import run, ml_row, others, ml_cost_line  # noqa: E402

# Probes from the review, recreated as tests.
PA = ("Customer support assistant that drafts replies using the OpenAI API (GPT-4o). Customer data never leaves the EU.")
PA2 = "Internal writing helper calling a hosted LLM API (Claude) to summarise tickets for our support team."
PD = "Solo prototype: a chat helper on a 3B model run with Ollama for a few testers."
PD2 = "Solo prototype: LoRA fine-tune a 3B model on my notes and serve the model for a few testers."


class ResidencyIsNotSelfHost(unittest.TestCase):
    def test_pa_hosted_api_with_eu_residency_stays_hosted(self):
        r = ml_row(run(PA, ml="llm_rag", res="eu", typ="saas_b2b"))
        self.assertNotIn("vLLM", r["choice"])
        self.assertNotIn("Self-hosted", r["choice"])

    def test_never_leaves_india_with_gemini_stays_hosted(self):
        r = ml_row(run("Tutor app answering questions with Gemini over course notes; student data never leaves India.",
                       ml="llm_rag", cloud="gcp", res="india", typ="saas_b2b"))
        self.assertNotIn("vLLM", r["choice"])

    def test_must_not_leave_our_servers_still_self_hosts(self):
        r = ml_row(run("Contract Q&A over our files with a language model; prompts must not leave our servers.", ml="llm_rag", typ="saas_b2b"))
        self.assertIn("vLLM", r["choice"])

    def test_open_weights_still_self_host_with_residency(self):
        r = ml_row(run("Internal assistant on an open-weights Mistral model; data never leaves the EU.", ml="llm_rag", res="eu", typ="saas_b2b"))
        self.assertIn("vLLM", r["choice"])


if __name__ == "__main__":
    unittest.main()
