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

    def test_bare_llm_with_eu_residency_is_not_self_hosted(self):
        r = ml_row(run("Policy Q&A chatbot with a language model over our handbook; employee data never leaves the EU.",
                       ml="llm_rag", res="eu", typ="saas_b2b"))
        self.assertNotIn("vLLM", r["choice"])

    def test_must_not_leave_our_servers_still_self_hosts(self):
        r = ml_row(run("Contract Q&A over our files with a language model; prompts must not leave our servers.", ml="llm_rag", typ="saas_b2b"))
        self.assertIn("vLLM", r["choice"])

    def test_open_weights_still_self_host_with_residency(self):
        r = ml_row(run("Internal assistant on an open-weights Mistral model; data never leaves the EU.", ml="llm_rag", res="eu", typ="saas_b2b"))
        self.assertIn("vLLM", r["choice"])


class HostedLlmApi(unittest.TestCase):
    def test_pa2_claude_api_is_hosted_per_token(self):
        out = run(PA2, typ="saas_b2b")
        r = ml_row(out)
        self.assertIn("Hosted LLM API", r["choice"])
        self.assertNotIn("scikit", r["choice"])
        self.assertIn("per million", ml_cost_line(out))

    def test_pa_inference_api_eu_is_hosted(self):
        out = run(PA, res="eu", typ="saas_b2b")
        r = ml_row(out)
        self.assertIn("Hosted LLM API", r["choice"])
        self.assertNotIn("vLLM", r["choice"])

    def test_azure_llm_wording_gets_hosted_route(self):
        r = ml_row(run("Our app uses a large language model to classify incoming emails by intent.", cloud="azure", typ="saas_b2b"))
        self.assertIn("Azure OpenAI", r["choice"])

    def test_classical_model_keeps_onnx(self):
        r = ml_row(run("Predict churn from usage events with a gradient-boosted model behind an API.", typ="saas_b2b"))
        self.assertNotIn("Hosted LLM", r["choice"])
        self.assertIn("ONNX", r["choice"])


if __name__ == "__main__":
    unittest.main()
