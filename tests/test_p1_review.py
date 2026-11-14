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


class AzureGpuSizing(unittest.TestCase):
    def test_pd_3b_on_azure_picks_t4(self):
        out = run(PD, cloud="azure", deploy="self_hosted_cloud_vm", typ="saas_b2b", budget__monthly_infra_usd=50)
        r = ml_row(out)
        self.assertIn("Standard_NC4as_T4_v3", r["choice"])
        self.assertIn("0.526", ml_cost_line(out))

    def test_default_8b_on_azure_picks_a10(self):
        r = ml_row(run("Self-hosted Llama model behind an OpenAI-compatible API for internal tools.", cloud="azure", typ="saas_b2b"))
        self.assertIn("Standard_NV36ads_A10_v5", r["choice"])

    def test_70b_on_azure_picks_four_a100(self):
        r = ml_row(run("Serve Llama 3.1 70B with vLLM for our analysts.", cloud="azure", typ="saas_b2b"))
        self.assertIn("Standard_NC96ads_A100_v4", r["choice"])

    def test_30b_does_not_fit_t4_or_a10(self):
        r = ml_row(run("Serve a Qwen 30B model with vLLM for our analysts.", cloud="azure", typ="saas_b2b"))
        self.assertIn("Standard_NC24ads_A100_v4", r["choice"])


def t4_alt(row):
    return next((a["why_not"] for a in row["alternatives"] if a["choice"].startswith("A T4-class")), None)


class TrueT4Alternative(unittest.TestCase):
    def test_pd2_small_lora_never_says_too_little_memory(self):
        why = t4_alt(ml_row(run(PD2, ml="training", typ="saas_b2b")))
        self.assertNotIn("too little memory", why)
        self.assertIn("enough memory", why)

    def test_small_lora_on_azure_has_no_t4_alt(self):
        self.assertIsNone(t4_alt(ml_row(run(PD2, ml="training", cloud="azure", typ="saas_b2b"))))

    def test_large_full_fine_tune_keeps_too_little_memory(self):
        why = t4_alt(ml_row(run("Full fine-tuning of a Llama 13B model on our support transcripts.", ml="training", typ="saas_b2b")))
        self.assertIn("too little memory", why)


def serving_rows(out):
    return [x for x in out["stack"]["supporting"] if "serving" in x["choice"].lower() and x["layer"] in ("other", "ml")]


class ServingNeedsModelWording(unittest.TestCase):
    def test_serves_hospitals_is_not_serving(self):
        out = run("LoRA fine-tune a Llama 8B model on de-identified notes; the product serves 200 hospitals.", ml="training", typ="saas_b2b")
        self.assertEqual([x["choice"] for x in others(out) if "vLLM" in x["choice"]], [])

    def test_train_and_serve_our_staff_is_not_serving(self):
        out = run("Retrain a demand forecasting model weekly; we train and serve our staff with the weekly numbers.", ml="training", typ="saas_b2b")
        self.assertEqual([x["choice"] for x in out["stack"]["supporting"] if x["choice"].startswith("Model serving")], [])

    def test_serve_the_model_adds_adapter_serving(self):
        out = run(PD2, ml="training", typ="saas_b2b")
        self.assertTrue([x for x in others(out) if "vLLM" in x["choice"]])

    def test_predictions_in_dashboard_adds_classical_serving(self):
        out = run("Train a churn model weekly and serve predictions in the account dashboard.", ml="training", typ="saas_b2b")
        self.assertTrue([x for x in out["stack"]["supporting"] if x["choice"].startswith("Model serving")])


class AdapterOwnerWording(unittest.TestCase):
    def test_solo_prototype_has_no_customer_wording(self):
        row = next(x for x in others(run(PD2, ml="training", typ="saas_b2b")) if "vLLM" in x["choice"])
        self.assertNotIn("customer", row["justification"] + str(row["alternatives"]))

    def test_multi_tenant_keeps_customer_wording(self):
        out = run("Per-customer LoRA adapters on a Llama 8B base model, deployed for inference behind one API.", ml="training", typ="saas_b2b",
                  requirements__multi_tenant=True)
        row = next(x for x in others(out) if "vLLM" in x["choice"])
        self.assertIn("each customer's adapter", row["justification"])


VISION_TRAIN = "Train and serve a computer-vision model that detects defects in product photos; inspectors review flags in a web app."


def triton(out):
    return next(x for x in out["stack"]["supporting"] if "Triton" in x["choice"])


class TritonOnSmallPlan(unittest.TestCase):
    def test_azure_app_service_prices_triton_as_own_instance(self):
        out = run(VISION_TRAIN, ml="training", cloud="azure", typ="saas_b2b", team__has_devops=False, team__size=2)
        t = triton(out)
        self.assertIn("own small instance", t["choice"])
        line = next(a for a in out["estimated_monthly_cost_usd"]["assumptions"] if "Triton" in a)
        self.assertNotIn("$0-10", line)
        self.assertRegex(line, r"plan")

    def test_classical_serving_keeps_in_api_range(self):
        out = run("Train a churn model weekly and serve predictions in the account dashboard.", ml="training", cloud="azure", typ="saas_b2b")
        row = next(x for x in out["stack"]["supporting"] if x["choice"].startswith("Model serving"))
        self.assertNotIn("own small instance", row["choice"])

    def test_on_premise_triton_stays_beside_api(self):
        t = triton(run(VISION_TRAIN, ml="training", cloud="any", deploy="on_premise", typ="saas_b2b"))
        self.assertIn("container next to the API", t["choice"])


if __name__ == "__main__":
    unittest.main()
