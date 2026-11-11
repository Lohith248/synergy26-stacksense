"""Judge oracle: per scenario, which core choices a senior architect would accept and which are clearly wrong.

Written from the scenario inputs and general engineering judgment, not copied from engine output.
Each layer entry: ok = any substring must match (empty = no constraint), bad = none may match,
must = any substring must match (platform / region facts). All matching is case-insensitive on the choice text.
`sup_has` = some supporting item's choice contains one of the substrings; `sup_absent` = no supporting
item of that layer exists. `no_cloud` (air-gapped) = no supporting choice names a public-cloud product.
"""
import glob
import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from engine.run import evaluate  # noqa: E402


def _load():
    sc = {}
    with open(os.path.join(ROOT, "scenarios", "stacksense_public_scenarios.json"), encoding="utf-8") as f:
        for i, s in enumerate(json.load(f), 1):
            sc["P%d" % i] = s
    for pat in ("edge_cases/*.json", "hidden_like/*.json", "extras/*.json"):
        for p in sorted(glob.glob(os.path.join(ROOT, "scenarios", pat))):
            with open(p, encoding="utf-8") as f:
                d = json.load(f)
            sc[os.path.basename(p).split("_")[0]] = d[0] if isinstance(d, list) else d
    return sc


SC = _load()
_CACHE = {}


def _eval(sid):
    if sid not in _CACHE:
        _CACHE[sid] = evaluate(SC[sid])
    return _CACHE[sid]
DYNAMIC_BAD = ["Pages", "Static", "Netlify", "Vercel", "Firebase Hosting", "CloudFront", "On-premises"]
STATIC_OK = ["Cloudflare Pages", "Netlify", "Vercel", "Firebase Hosting", "CloudFront", "Static Web Apps", "GitHub Pages"]
STATIC_BAD = ["App Service", "Lambda", "Cloud Run", "ECS", "Fargate", "Beanstalk", "Kubernetes", "Container Apps", "On-premises"]
INDIA = ["Pune", "Mumbai", "India", "asia-south", "ap-south", "Hyderabad"]
US = ["East US", "Virginia", "us-east", "Ohio", "us-central", "Iowa"]
EU = ["Netherlands", "Frankfurt", "Ireland", "Europe", "Paris", "Stockholm", "eu-", "Belgium"]
CLOUD_NAMES = ["Azure", "Amazon", "AWS", "Google", "Cloud SQL", "Supabase", "Cloudflare", "Firebase", "Stripe", "Razorpay",
               "Vercel", "Netlify", "GitHub Actions"]
OTHER_LANGS = ["PHP", "Rails", "Django", "FastAPI", ".NET", "Spring", "Go 1", "Node", "NestJS"]


def w(ok=None, bad=None, must=None):
    return {"ok": ok or [], "bad": bad or [], "must": must or []}


def langs_except(*keep):
    return [x for x in OTHER_LANGS if not any(k in x for k in keep)]


ORACLE = {
    "P1": dict(frontend=w(["Astro", "Eleventy", "Hugo", "Next.js", "Nuxt", "SvelteKit"], ["React Native", "Kotlin", "Flutter"]),
               backend=w(["None"]), database=w(["None"]), hosting=w(STATIC_OK, STATIC_BAD),
               sup_absent=["auth", "payments", "realtime", "cache", "queue"]),
    "P2": dict(frontend=w(["React Native", "Flutter", "Kotlin"], ["Unity", "WPF", "Electron"], ["Android"]),
               backend=w(["Node", "NestJS", "Python", "FastAPI", "Django"], [".NET", "Spring", "Rails", "PHP", "Rust"]),
               database=w(["PostgreSQL", "Postgres"], ["SQLite", "Firestore", "DynamoDB", "Cosmos", "Mongo"], INDIA),
               hosting=w(["App Service", "Cloud Run", "ECS", "Fargate", "Container Apps", "App Runner", "Beanstalk"],
                         ["Lambda", "Kubernetes", "Pages", "Static", "On-premises"], INDIA),
               sup_has={"payments": ["Razorpay", "Cashfree", "PayU"], "realtime": ["Socket.IO", "SignalR", "WebSocket", "Ably", "Pusher"]}),
    "P3": dict(frontend=w(["React", "Next.js", "Svelte", "Vue"], ["React Native", "Kotlin", "Unity"]),
               backend=w(["Go 1", "Node", "NestJS"], [".NET", "Rails", "Laravel", "Django", "Spring", "PHP"]),
               database=w(["PostgreSQL", "Postgres"], ["SQLite"]),
               hosting=w([], ["Lambda", "Pages", "Static", "On-premises", "Functions"]),
               sup_has={"realtime": ["Yjs", "CRDT", "Liveblocks", "WebSocket"]}),
    "P4": dict(frontend=w([], ["Unity", "Electron"], ["Android", "iOS"]),
               backend=w(["Spring", "Java", "Kotlin"], ["PHP", "Rails", "Django", ".NET", "Go 1"]),
               database=w(["PostgreSQL", "Aurora"], ["SQLite", "Mongo", "Dynamo", "Firestore", "Cosmos"], ["Mumbai", "ap-south"]),
               hosting=w(["ECS", "Fargate", "EKS", "Beanstalk", "App Runner"], ["Lambda", "Pages", "Static", "Azure", "Cloud Run", "Google"], ["Mumbai", "ap-south"]),
               sup_has={"payments": ["Razorpay", "Cashfree", "PayU", "Juspay"]}),
    "P5": dict(frontend=w([], ["React Native", "Kotlin", "Unity"]),
               backend=w([".NET"], langs_except(".NET")),
               database=w(["Azure SQL", "SQL Server", "PostgreSQL"], ["SQLite", "Mongo", "Cosmos"], INDIA),
               hosting=w(["App Service", "Container Apps"], ["Lambda", "AWS", "Google", "Cloud Run", "Functions", "Kubernetes"], INDIA),
               sup_has={"auth": ["Entra"]}),
    "P6": dict(frontend=w(["React Native", "Kotlin", "Flutter"], ["Next.js", "Electron", "WPF", "Unity", "SwiftUI"], ["Android"]),
               backend=w(["Python", "Django", "FastAPI", "Node", "NestJS"], [".NET", "Spring", "Rails", "PHP"]),
               database=w(["PostgreSQL", "Postgres"], ["Cosmos", "Dynamo"], INDIA),
               hosting=w([], ["Kubernetes", "AKS", "EKS", "GKE", "Pages", "Static", "On-premises"], INDIA)),
    "E3": dict(frontend=w([], ["Unity", "WPF"], ["Android", "iOS"]),
               backend=w(["Node", "NestJS"], [".NET", "Spring", "Rails", "PHP"]),
               database=w([], ["SQLite", "None"]), hosting=w([], ["Pages", "Static", "On-premises", "Lambda"])),
    "E4": dict(frontend=w(["Astro", "Next.js", "Eleventy", "Hugo"]), backend=w(["None"]), database=w(["None"]),
               hosting=w(STATIC_OK, STATIC_BAD)),
    "E5": dict(backend=w(["Node", "NestJS", "Go 1"], ["PHP", "Rails"]),
               database=w(["PostgreSQL"], ["SQLite"], US),
               hosting=w([], ["Lambda", "Pages", "Static", "On-premises", "India", "Europe", "Mumbai"], US)),
    "E6": dict(backend=w([".NET"], langs_except(".NET")),
               database=w(["Azure SQL", "SQL Server", "PostgreSQL"], ["SQLite", "Mongo"], INDIA),
               hosting=w(["App Service", "Container Apps"], ["Lambda", "AWS", "Google", "Cloud Run", "Kubernetes"], INDIA)),
    "E7": dict(backend=w([".NET"], langs_except(".NET")),
               database=w(["PostgreSQL", "SQL Server"], CLOUD_NAMES), hosting=w(["On-premises", "Docker", "Kubernetes"], CLOUD_NAMES),
               no_cloud=True),
    "E8": dict(backend=w(["Laravel", "PHP", "Node", "NestJS"], ["Rails", ".NET", "Spring", "Django"]),
               hosting=w([], ["Lambda", "Pages", "Static", "On-premises"])),
    "E9": dict(frontend=w([], ["AngularJS", "Angular"], ["Android"]),
               backend=w(["Node", "NestJS", "Python", "FastAPI", "Django"], [".NET", "Spring", "Rails", "PHP"]),
               database=w(["PostgreSQL"], ["SQLite", "Mongo", "Cosmos", "Dynamo"], INDIA),
               hosting=w([], ["Lambda", "Pages", "Static", "On-premises"], INDIA)),
    "X1": dict(frontend=w(["React Native", "Kotlin", "Flutter"], ["Next.js", "Electron", "WPF", "Unity"], ["Android"]),
               backend=w(["Python", "Django", "FastAPI", "Node", "NestJS"], [".NET", "Spring", "Rails", "PHP"]),
               database=w(["PostgreSQL"], ["Cosmos", "Dynamo"], INDIA),
               hosting=w([], ["Kubernetes", "AKS", "EKS", "GKE", "Pages", "Static", "On-premises"], INDIA)),
    "H01": dict(frontend=w(["Unity", "Godot"], ["React", "Electron", "WPF"], ["Android", "iOS"]),
                backend=w([".NET", "ASP.NET"], ["Node", "Python", "PHP", "Rails", "Spring", "Django"]),
                database=w(["PostgreSQL", "Redis", "Cosmos"], ["SQLite"]),
                hosting=w([], ["Lambda", "Pages", "Static", "Functions", "On-premises"]),
                sup_has={"realtime": ["PlayFab", "GameLift", "Agones", "Nakama", "Photon", "game server"],
                         "payments": ["Google Play Billing"]}),
    "H02": dict(frontend=w(["React", "Next.js", "Vue", "Svelte"], ["Unity", "WPF", "Kotlin"]),
                backend=w(["Node", "NestJS", "Python", "FastAPI", "Django"], [".NET", "Spring", "PHP", "Rails"]),
                database=w(["PostgreSQL", "Timescale", "Timestream", "RDS", "Aurora"], ["SQLite"]),
                hosting=w(["ECS", "Fargate", "App Runner", "Beanstalk", "EKS"], ["Azure", "Google", "Cloud Run", "Pages", "Static", "On-premises"]),
                sup_has={"other": ["IoT Core", "MQTT"]}),
    "H03": dict(backend=w(["Python", "Django", "FastAPI"], ["Spring", ".NET", "PHP", "Rails", "Go 1"]),
                database=w(["BigQuery", "PostgreSQL"], ["SQLite"]),
                hosting=w(["Cloud Run", "GKE", "App Engine"], ["Azure", "AWS", "Amazon", "Lambda", "Pages"]),
                sup_has={"other": ["BigQuery"]}),
    "H04": dict(backend=w(["Python", "Django", "FastAPI", "Node", "NestJS"], [".NET", "Spring", "PHP", "Rails"]),
                database=w(["PostgreSQL"], ["SQLite"], EU),
                hosting=w([], ["Lambda", "Pages", "Static", "On-premises"], EU),
                sup_has={"ml": ["OpenAI", "Bedrock", "Vertex", "AI Search"]}),
    "H05": dict(backend=w(["Node", "NestJS", "Spring", "Java", "Kotlin"], ["PHP", "Rails", "Django", ".NET", "Go 1"]),
                database=w(["PostgreSQL"], ["SQLite", "Mongo"], US),
                hosting=w([], ["Lambda", "Pages", "Static", "Netlify", "Vercel", "On-premises"], US),
                sup_has={"realtime": ["SignalR", "WebSocket", "Twilio", "Socket.IO", "Daily", "Chime", "Agora"]}),
    "H06": dict(frontend=w(["None"]), backend=w(["Go 1"], ["PHP", "Rails", "Django", ".NET", "Spring"]),
                database=w(["PostgreSQL", "Postgres"], ["SQLite"]), hosting=w([], ["Pages", "Static", "On-premises"]),
                sup_has={"other": ["gateway"]}, sup_absent=["auth"]),
    "H07": dict(backend=w(["Node", "NestJS"], ["Django", ".NET", "Spring", "Rails", "PHP"]),
                database=w(["PostgreSQL"], ["SQLite"], US),
                hosting=w([], ["Lambda", "Pages", "Static", "On-premises"], US),
                sup_has={"auth": ["SAML", "brokering", "federation", "External ID", "Cognito", "Identity Platform"]}),
    "H08": dict(frontend=w(["Next.js", "Nuxt"], ["Vite SPA", "Unity"], ["Android"]),
                backend=w(["Node", "NestJS", "Laravel", "PHP"], [".NET", "Spring", "Rails", "Django"]),
                database=w(["PostgreSQL", "MySQL"], ["SQLite", "Cosmos", "Dynamo"], INDIA),
                hosting=w(["Cloud Run", "App Service", "ECS", "Fargate", "App Runner", "Lambda", "Container Apps"],
                          ["Premium v3", "Pages", "Static", "On-premises"], INDIA),
                sup_has={"payments": ["Razorpay", "Cashfree", "PayU"]}),
    "H09": dict(backend=w(["Node", "NestJS", "Python", "FastAPI", "Django"], [".NET", "Spring", "Rails", "PHP"]),
                database=w(["Supabase", "PostgreSQL", "Firestore"], ["Cloud SQL", "RDS", "Azure Database", "Aurora"]),
                hosting=w(["Cloud Run", "Vercel", "Netlify", "Render", "Fly", "Cloudflare", "Firebase", "Lambda"],
                          ["App Service", "Kubernetes", "Premium", "Beanstalk", "ECS", "On-premises"])),
    "H10": dict(frontend=w([], ["Unity", "Electron", "WPF"], ["Android", "iOS"]),
                backend=w(["Node", "NestJS", "Spring", "Kotlin"], ["PHP", "Rails", "Django", ".NET", "Go 1"]),
                database=w(["PostgreSQL"], ["SQLite"]), hosting=w([], ["Pages", "Static", "On-premises"]),
                sup_has={"search": ["Elasticsearch", "OpenSearch", "Meilisearch", "Typesense", "PostgreSQL full-text"],
                         "realtime": ["Socket.IO", "WebSocket", "SignalR", "Pub/Sub", "Ably", "Pusher", "Firebase"]},
                sup_absent=["payments"]),
    "H11": dict(frontend=w(["WPF", "MAUI", "WinUI", "Avalonia", "Windows Forms"], ["Electron", "Tauri", "React", "Flutter"]),
                backend=w([".NET"], langs_except(".NET")),
                database=w(["PostgreSQL", "SQL Server", "SQLite"], CLOUD_NAMES),
                hosting=w(["On-premises"], CLOUD_NAMES)),
    "H12": dict(frontend=w(["Astro", "Next.js", "Eleventy", "Hugo"]), backend=w(["None"]), database=w(["None"]),
                hosting=w(STATIC_OK, STATIC_BAD)),
}


def _judge(sid, out):
    """Return a list of misses (empty = the output is acceptable)."""
    miss, spec, st = [], ORACLE[sid], out["stack"]
    for layer in ("frontend", "backend", "database", "hosting"):
        r = spec.get(layer)
        if not r:
            continue
        txt = st[layer]["choice"].lower()
        has = lambda subs: [s for s in subs if s.lower() in txt]
        if r["ok"] and not has(r["ok"]):
            miss.append("%s: %r not in acceptable set %s" % (layer, st[layer]["choice"], r["ok"]))
        if has(r["bad"]):
            miss.append("%s: %r is clearly wrong (%s)" % (layer, st[layer]["choice"], has(r["bad"])))
        if r["must"] and not has(r["must"]):
            miss.append("%s: %r lacks one of %s" % (layer, st[layer]["choice"], r["must"]))
    sup = st["supporting"]
    for layer, subs in spec.get("sup_has", {}).items():
        texts = [x["choice"].lower() for x in sup if x["layer"] == layer]
        if not any(s.lower() in t for t in texts for s in subs):
            miss.append("supporting %s lacks one of %s (has %s)" % (layer, subs, texts))
    for layer in spec.get("sup_absent", []):
        if any(x["layer"] == layer for x in sup):
            miss.append("supporting %s should be absent" % layer)
    if spec.get("no_cloud"):
        for x in sup:
            hit = [c for c in CLOUD_NAMES if c.lower() in x["choice"].lower()]
            if hit:
                miss.append("air-gapped but supporting %s names %s" % (x["layer"], hit))
    return miss


class Oracle(unittest.TestCase):
    def test_invalid_inputs_rejected_cleanly(self):
        for sid in ("E1", "E2"):
            out = evaluate(SC[sid])
            self.assertEqual(out["status"], "invalid_input", sid)
            self.assertTrue(out["validation_errors"], sid)

    def test_every_scenario_is_covered(self):
        self.assertEqual(set(SC) - {"E1", "E2"}, set(ORACLE))

    def test_oracle(self):
        problems = {}
        for sid in ORACLE:
            m = _judge(sid, _eval(sid))
            if m:
                problems[sid] = m
        self.assertFalse(problems, "\n" + "\n".join("%s: %s" % (k, "; ".join(v)) for k, v in problems.items()))


PROVIDER_WORDS = {"aws": ["amazon", "aws"], "azure": ["azure", "entra", "microsoft"], "gcp": ["google", "cloud run", "cloud sql", "gke", "firebase", "bigquery"]}
PLATFORM_WORDS = {"android": ["android"], "ios": ["ios"], "web": ["web"], "desktop": ["desktop", "wpf", "maui", "pwa", "electron", "tauri"]}
RESIDENCY = {"india": INDIA, "us": US, "eu": EU}


class Invariants(unittest.TestCase):
    """Cross-scenario rules a senior architect holds regardless of the exact stack."""

    def _each(self):
        for sid, s in SC.items():
            if sid in ("E1", "E2"):
                continue
            yield sid, s, _eval(sid)

    def test_explicit_cloud_is_honoured(self):
        for sid, s, o in self._each():
            pref = s.get("infrastructure", {}).get("cloud_preference")
            if pref in PROVIDER_WORDS:
                for layer in ("database", "hosting"):
                    txt = o["stack"][layer]["choice"].lower()
                    if txt != "none":
                        self.assertTrue(any(w in txt for w in PROVIDER_WORDS[pref]), (sid, layer, txt))

    def test_residency_region_is_named_for_data_bearing_layers(self):
        for sid, s, o in self._each():
            res = s.get("infrastructure", {}).get("data_residency")
            if res in RESIDENCY and s["infrastructure"].get("deployment_model") == "managed_cloud":
                for layer in ("database", "hosting"):
                    txt = o["stack"][layer]["choice"].lower()
                    self.assertTrue(any(r.lower() in txt for r in RESIDENCY[res]), (sid, layer, txt))

    def test_every_platform_is_served(self):
        for sid, s, o in self._each():
            fe = o["stack"]["frontend"]["choice"].lower()
            for p in s["project"].get("platforms", []):
                if p in PLATFORM_WORDS:
                    self.assertTrue(any(w in fe for w in PLATFORM_WORDS[p]), (sid, p, fe))

    def test_budget_overrun_is_never_silent(self):
        for sid, s, o in self._each():
            budget = s.get("budget", {}).get("monthly_infra_usd")
            if budget is not None:
                codes = {w["code"] for w in o["warnings"]}
                if o["estimated_monthly_cost_usd"]["min"] > budget:
                    self.assertIn("BUDGET_EXCEEDED", codes, sid)

    def test_high_availability_names_redundancy(self):
        for sid, s, o in self._each():
            if float(s.get("requirements", {}).get("availability", "99")) >= 99.95 and s["infrastructure"].get("deployment_model") == "managed_cloud":
                text = " ".join(o["stack"][k]["choice"] + o["stack"][k]["justification"] for k in ("database", "hosting")).lower()
                self.assertTrue(any(w in text for w in ("multi-az", "zone", "standby", "replica", "failover")), sid)

    def test_no_backend_means_no_database(self):
        for sid, s, o in self._each():
            if o["stack"]["backend"]["choice"] == "None":
                self.assertEqual(o["stack"]["database"]["choice"], "None", sid)


if __name__ == "__main__":
    unittest.main()
