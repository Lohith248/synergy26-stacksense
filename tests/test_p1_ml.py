"""p1: ML/LLM knowledge rows (kb/ml.json) and rules: self-hosted LLM serving vs classical ML, GPU cost at 730 h from KB rates,
edge computer vision, LLM fine-tuning priced from GPU-hours, tracking + registry."""
import copy
import os
import re
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from engine.run import evaluate  # noqa: E402
from engine import mlstack as mls  # noqa: E402
from engine.kb import ML, SOURCES  # noqa: E402

BASE = {
    "project": {"name": "X", "type": "ai_ml_product", "description": "", "platforms": ["web"]},
    "scale": {"traffic_pattern": "steady", "workload": "balanced", "users_at_launch": 50, "users_12_months": 400,
              "peak_concurrent_users": 100, "data_volume_gb_12_months": 50},
    "team": {"has_devops": True, "size": 4, "experience": "senior", "languages": ["python"]},
    "budget": {"monthly_infra_usd": 3000}, "timeline": {"mvp_weeks": 8},
    "infrastructure": {"cloud_preference": "aws", "deployment_model": "managed_cloud", "data_residency": "us", "existing_systems": []},
    "requirements": {"realtime": False, "offline_support": False, "full_text_search": False, "file_media_storage": False, "payments": False,
                     "auth": "email_password", "multi_tenant": False, "ml_features": "inference_api", "seo_critical": False,
                     "availability": "99.9", "p95_latency_ms": None},
    "compliance": [], "priorities": {"cost": 3, "time_to_market": 3, "scalability": 3, "performance": 3, "maintainability": 3, "security": 3},
}


def run(desc, ml="inference_api", cloud="aws", deploy="managed_cloud", res="us", typ="ai_ml_product", **extra):
    s = copy.deepcopy(BASE)
    s["project"]["description"] = desc
    s["project"]["type"] = typ
    s["requirements"]["ml_features"] = ml
    s["infrastructure"].update(cloud_preference=cloud, deployment_model=deploy, data_residency=res)
    for k, v in extra.items():
        sec, key = k.split("__")
        s[sec][key] = v
    return evaluate(s, counterfactuals=False)


def ml_row(out):
    return next(x for x in out["stack"]["supporting"] if x["layer"] == "ml")


def others(out):
    return [x for x in out["stack"]["supporting"] if x["layer"] == "other"]


def ml_cost_line(out):
    return next(a for a in out["estimated_monthly_cost_usd"]["assumptions"] if a.startswith("ml:"))


OPEN_LLM = "Serve an open-weights LLM (Llama 3.1 8B Instruct from Hugging Face) behind an OpenAI-compatible API for our internal apps."


class KbRows(unittest.TestCase):
    def test_every_ml_row_cites_known_sources(self):
        def walk(x):
            if isinstance(x, dict):
                for k, v in x.items():
                    if k in ("src", "lora_src"):
                        for i in v:
                            self.assertIn(i, SOURCES, i)
                    else:
                        walk(v)
            elif isinstance(x, list):
                for v in x:
                    walk(v)
        walk(ML)

    def test_gpu_rows_sorted_and_priced(self):
        for prov, rows in ML["gpu_instances"].items():
            if prov.startswith("_"):
                continue
            self.assertEqual([r["vram_gb"] for r in rows], sorted(r["vram_gb"] for r in rows))
            for r in rows:
                self.assertIn("us", r["usd_per_hour"])
                self.assertTrue(all(v > 0 for v in r["usd_per_hour"].values()))

    def test_saas_only_store_marked(self):
        self.assertTrue(ML["vector_stores"]["pinecone"]["saas_only"])
        self.assertFalse(ML["vector_stores"]["pgvector"]["saas_only"])


class Sizing(unittest.TestCase):
    def test_model_size_parsed(self):
        ctx = {"req": {"project.description": "Llama 3.1 8B or Mistral 7B, later a 70B model"}}
        self.assertEqual(mls.model_params_b(ctx), 70)
        self.assertIsNone(mls.model_params_b({"req": {"project.description": "B2B app for 5,000 users"}}))

    def test_gpu_class_from_vram(self):
        self.assertEqual(mls.gpu_pick("aws", mls.vram_need_gb(8), "us")["row"]["id"], "g6.xlarge")
        self.assertEqual(mls.gpu_pick("aws", mls.vram_need_gb(13), "eu")["row"]["id"], "g6e.xlarge")
        self.assertEqual(mls.gpu_pick("aws", mls.vram_need_gb(70), "india")["row"]["id"], "g6e.12xlarge")
        self.assertEqual(mls.gpu_pick("azure", mls.vram_need_gb(8), "eu")["rate"], 4.775)
        ref = mls.gpu_pick("hetzner", 10, None)
        self.assertTrue(ref["ref_provider"])


class SelfHostedLlmServing(unittest.TestCase):
    def test_inference_api_open_weights_on_gcp_vm(self):
        out = run(OPEN_LLM + " No prompts may leave our own VMs.", cloud="gcp", deploy="self_hosted_cloud_vm")
        m = ml_row(out)
        self.assertIn("vLLM", m["choice"])
        self.assertNotIn("scikit", m["choice"])
        self.assertIn("g2-standard-8", m["choice"])
        line = ml_cost_line(out)
        self.assertIn("730 hours", line)
        lo = int(re.search(r"\$([\d,]+)-", line).group(1).replace(",", ""))
        self.assertGreaterEqual(lo, 700)  # one L4-class GPU all month, not $0-10

    def test_inference_api_open_weights_managed_aws_eu_uses_region_rate(self):
        out = run("Internal chatbot on a self-hosted Mistral 7B model; customer data must not leave our AWS account.", res="eu", typ="saas_b2b")
        m = ml_row(out)
        self.assertIn("g6.xlarge", m["choice"])
        self.assertIn("$1.0064/hour", ml_cost_line(out))

    def test_rag_on_premise_sized_and_off_the_cloud_bill(self):
        out = run("Question answering over our manuals with a Qwen 14B model.", ml="llm_rag", cloud="none", deploy="on_premise", typ="internal_tool")
        m = ml_row(out)
        self.assertIn("vLLM", m["choice"])
        self.assertIn("at least 40 GB of GPU memory", m["choice"])
        self.assertIn("$0/month cloud bill", ml_cost_line(out))
        self.assertTrue(any("GPU server" in a for a in out["estimated_monthly_cost_usd"]["assumptions"]))

    def test_rag_managed_cloud_with_open_weights_goes_to_gpu_vm(self):
        out = run("Clinic assistant over guidelines using an open-weight Llama model; documents must never leave our cloud account.",
                  ml="llm_rag", cloud="azure", typ="healthtech")
        m = ml_row(out)
        self.assertTrue(m["choice"].startswith("Self-hosted open-weight LLM (vLLM"), m["choice"])
        self.assertIn("Standard_NC24ads_A100_v4", m["choice"])
        self.assertIn("730 hours", ml_cost_line(out))

    # must-not-fire
    def test_tabular_churn_prediction_stays_classical(self):
        out = run("Churn-prediction API: a gradient-boosted model scores customer accounts nightly from billing data.", typ="saas_b2b")
        self.assertIn("ONNX Runtime", ml_row(out)["choice"])
        self.assertNotIn("vLLM", ml_row(out)["choice"])

    def test_hosted_llm_chatbot_stays_hosted(self):
        out = run("Customer support chatbot that answers from our help-centre articles with an LLM.", ml="llm_rag", typ="saas_b2b")
        self.assertTrue(ml_row(out)["choice"].startswith("Amazon Bedrock"), ml_row(out)["choice"])

    def test_ai_in_passing_is_not_an_llm(self):
        out = run("Recipe app with AI-powered recommendations of what to cook next.", typ="web_app")
        self.assertNotIn("vLLM", ml_row(out)["choice"])
        self.assertIn("ONNX Runtime", ml_row(out)["choice"])

    def test_negated_llm_wording_does_not_fire(self):
        out = run("Fraud scoring model on card transactions; no LLM is used anywhere.", typ="fintech")
        self.assertNotIn("vLLM", ml_row(out)["choice"])


class EdgeVision(unittest.TestCase):
    def test_air_gapped_jetson_cameras(self):
        out = run("Computer vision at the edge: 40 cameras detect weld defects on NVIDIA Jetson-class edge devices next to the line.",
                  cloud="none", deploy="air_gapped", res="india", typ="iot", requirements__p95_latency_ms=100)
        m = ml_row(out)
        self.assertIn("DeepStream", m["choice"])
        self.assertNotIn("scikit", m["choice"])
        self.assertIn("5-10 edge devices", m["justification"])
        self.assertIn("$0/month cloud bill", ml_cost_line(out))
        mq = next((x for x in others(out) if "MQTT" in x["choice"]), None)
        if mq:
            self.assertNotIn("one message per device every", mq["justification"])
            self.assertIn("not video frames", mq["justification"])

    def test_managed_cloud_edge_cameras_without_nvidia(self):
        out = run("Retail shelf analytics: cameras run object detection on edge devices in each store; results sync to the cloud.", typ="ecommerce")
        m = ml_row(out)
        self.assertIn("ONNX Runtime with the TensorRT execution provider", m["choice"])

    def test_on_premise_factory_on_device_vision(self):
        out = run("Quality control with image classification of parts on-device at each station.", cloud="none", deploy="on_premise", typ="internal_tool")
        self.assertIn("Edge inference", ml_row(out)["choice"])

    def test_cloud_photo_classification_is_not_edge(self):
        out = run("Users upload photos and an image classification model tags them in the cloud.", typ="web_app")
        self.assertNotIn("Edge inference", ml_row(out)["choice"])


class FineTuning(unittest.TestCase):
    FT = ("Fine-tuning pipeline: we fine-tune open-weights 7B models with LoRA adapters, track experiments, version datasets and models, "
          "then deploy the adapter for inference.")

    def test_gcp_lora_priced_from_gpu_hours_with_tracking_and_serving(self):
        out = run(self.FT, ml="training", cloud="gcp")
        m = ml_row(out)
        self.assertIn("Vertex AI custom training on g2-standard-8", m["choice"])
        self.assertIn("GPU-hours a month", ml_cost_line(out))
        names = [x["choice"] for x in others(out)]
        self.assertTrue(any(n.startswith("Adapter serving: vLLM") for n in names), names)
        self.assertTrue(any(n.startswith("ML experiment tracking + model registry: Vertex AI") and "DVC" in n for n in names), names)

    def test_aws_full_fine_tune_needs_bigger_gpu(self):
        out = run("We fine-tune a 7B language model on our support tickets every month.", ml="training", typ="saas_b2b")
        self.assertIn("g6e.12xlarge", ml_row(out)["choice"])
        self.assertIn("(full fine-tuning)", ml_row(out)["choice"])
        self.assertFalse(any(x["choice"].startswith("Adapter serving") for x in others(out)))

    def test_on_premise_fine_tune_uses_mlflow(self):
        out = run("Fine-tune a Llama 8B model with LoRA on internal documents; track experiments.", ml="training", cloud="none",
                  deploy="on_premise", typ="internal_tool")
        names = [x["choice"] for x in others(out)]
        self.assertTrue(any("MLflow" in n for n in names), names)
        self.assertIn("$0/month cloud bill", ml_cost_line(out))

    # must-not-fire
    def test_classical_retrain_keeps_previous_route(self):
        out = run("Demand forecasting model retrained weekly on sales history.", ml="training", typ="saas_b2b")
        self.assertNotIn("LoRA", ml_row(out)["choice"])
        self.assertFalse(any("Adapter serving" in x["choice"] for x in others(out)))


if __name__ == "__main__":
    unittest.main()


class TrainAndServe(unittest.TestCase):
    """1b: requirements.ml_features=training plus wording that the model is served -> a serving component next to training."""

    def servers(self, out):
        return [x for x in out["stack"]["supporting"] if x["choice"].startswith(("Model serving", "Adapter serving"))]

    def test_vision_train_and_serve_gets_triton(self):
        out = run("Train and serve a computer-vision model that detects defects in product photos from five plants; inspectors review flags in a web app.",
                  ml="training", cloud="azure")
        sv = self.servers(out)
        self.assertEqual(len(sv), 1)
        self.assertIn("Triton", sv[0]["choice"])

    def test_tabular_prediction_api_gets_in_process_serving(self):
        out = run("Retrain a churn model nightly on CRM data and expose a prediction API that the sales app calls.", ml="training",
                  typ="saas_b2b")
        sv = self.servers(out)
        self.assertEqual(len(sv), 1)
        self.assertIn("ONNX Runtime", sv[0]["choice"])
        self.assertNotIn("Triton", sv[0]["choice"])

    def test_on_prem_train_serve_has_no_cloud_cost(self):
        out = run("Train demand-forecast models weekly and serve predictions to the planning tool over real-time scoring requests.",
                  ml="training", cloud="any", deploy="on_premise", typ="internal_tool")
        sv = self.servers(out)
        self.assertEqual(len(sv), 1)
        self.assertFalse(any(a.startswith("ml:") and "Model serving" in a and "$0/month" not in a and "$0-0" not in a
                             for a in out["estimated_monthly_cost_usd"]["assumptions"]))

    def test_llm_fine_tune_full_deployed_gets_vllm(self):
        out = run("Fine-tune a 7B open-weights LLM on support tickets and deploy the model for the agents' assistant.", ml="training")
        sv = self.servers(out)
        self.assertEqual(len(sv), 1)
        self.assertIn("vLLM", sv[0]["choice"])

    def test_training_only_gets_no_server(self):
        out = run("Train a weekly demand-forecast model; analysts read the results in a dashboard export.", ml="training", typ="internal_tool")
        self.assertEqual(self.servers(out), [])
