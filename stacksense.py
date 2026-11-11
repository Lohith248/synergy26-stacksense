#!/usr/bin/env python3
"""StackSense command line.

  python stacksense.py run <scenario.json> [--out outputs] [--no-llm] [--explain]
  python stacksense.py interactive [--out outputs]
  python stacksense.py serve [--port 8765]     optional local web UI (http://127.0.0.1:8765/)

`run` accepts a single scenario object or an array of scenarios (like stacksense_public_scenarios.json)
and writes <scenario_id>_output.json per scenario. The engine never calls an LLM; --no-llm and
STACKSENSE_LLM=off are accepted so the judge's LLM-off test is explicit (they change nothing).
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from engine.load import parse_text  # noqa: E402
from engine import ENGINE_VERSION  # noqa: E402


def dump_doc(doc):
    """Exact text of an output file; engine/web.py reuses it so UI exports match the CLI byte for byte."""
    return json.dumps(doc, indent=2, ensure_ascii=False) + "\n"


def write_atomic(path, doc):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(dump_doc(doc))
    os.replace(tmp, path)


def out_name(doc, index, total):
    sid = doc.get("scenario_id")
    safe = "".join(ch for ch in sid if ch.isalnum() or ch in "-_") if isinstance(sid, str) else ""
    if not safe:
        safe = f"scenario_{index + 1}" if total > 1 else "scenario"
    return f"{safe}_output.json"


def explain(doc):
    lines = [f"\n=== {doc.get('scenario_id') or 'scenario'}  status: {doc['status']}  style: {doc['architecture_style']}",
             doc["summary"]]
    if doc["stack"]:
        for layer in ("frontend", "backend", "database", "hosting"):
            c = doc["stack"][layer]
            lines.append(f"\n[{layer}] {c['choice']}\n  why: {c['justification']}\n  driven_by: {', '.join(c['driven_by'])}")
            for a in c["alternatives"][:2]:
                lines.append(f"  instead of {a['choice']}: {a['why_not']}")
            st = c.get("stability")
            if st:
                fp = st["flip_point"]
                lines.append(f"  stability {st['score']:.2f} ({st['label']}, {st['vectors_tested']} priority vectors)"
                             + (f"; flips to {fp['new_choice']} if priorities.{fp['priority']} {fp['from']} -> {fp['value']}" if fp else "; no single priority change flips it"))
            if c.get("confidence"):
                lines.append(f"  confidence {c['confidence']['label']}: {c['confidence']['basis']}")
            if c.get("pareto") and not c["pareto"]["optimal"]:
                lines.append(f"  pareto: {c['pareto']['note']}")
            if c.get("contrast"):
                lines.append(f"  decision: {c['contrast']}")
            for e in c.get("what_would_change", [])[:2]:
                if e["path"]:
                    lines.append(f"  would change if {e['edit']} -> {e['new_choice']}")
        for s in doc["stack"].get("supporting", []):
            lines.append(f"\n[{s['layer']}] {s['choice']}\n  why: {s['justification']}")
    c = doc["estimated_monthly_cost_usd"]
    lines.append(f"\nCost: {c['min']} - {c['max']} USD/month")
    for w in doc["warnings"]:
        lines.append(f"  {w['severity'].upper():8} {w['code']}: {w['message']}")
    for e in doc["validation_errors"]:
        lines.append(f"  ERROR {e['field']}: {e['message']}")
    return "\n".join(lines)


def adr(doc):
    """Markdown Architecture Decision Records, one per core layer, from the output document alone."""
    def cell(s):
        return str(s).replace("|", "\\|").replace("\n", " ")
    c = doc["estimated_monthly_cost_usd"]
    status = "Accepted (relaxed: see assumptions)" if doc["summary"].startswith("Relaxed") else "Accepted"
    md = [f"# Architecture decisions: {doc.get('scenario_id') or 'scenario'}", "", doc["summary"], "",
          f"Style: {doc['architecture_style']}. Estimated cost: {c['min']}-{c['max']} USD/month (order of magnitude).", ""]
    for n, layer in enumerate(("frontend", "backend", "database", "hosting"), 1):
        x = doc["stack"][layer]
        md += [f"## ADR-{n}: {layer}", "", f"**Status:** {status}", "",
               f"**Context:** driven by {', '.join(x['driven_by'])}.", "",
               f"**Decision:** {x['choice']}. {x['justification']}", "",
               "| Option | Outcome | Why |", "|---|---|---|", f"| {cell(x['choice'])} | chosen | {cell(x['justification'])} |"]
        md += [f"| {cell(a['choice'])} | {'excluded' if a['why_not'].startswith('Excluded') else 'rejected'} | {cell(a['why_not'])} |"
               for a in x["alternatives"]]
        md += ["", "**Consequences:**", ""] + [f"- Trade-off: {t}" for t in x["tradeoffs"]]
        if x.get("confidence"):
            md.append(f"- Confidence {x['confidence']['label']}: {x['confidence']['basis']}")
        md += [f"- Revisit if {e['edit']} (would give {e['new_choice']})" for e in x.get("what_would_change", []) if e["path"]]
        md.append("")
    serious = [w for w in doc["warnings"] if w["severity"] != "info"]
    if serious:
        md += ["## Warnings that apply across decisions", ""] + [f"- **{w['code']}** ({w['severity']}): {w['message']}" for w in serious]
    return "\n".join(md) + "\n"


def cmd_run(args):
    try:
        with open(args.file, encoding="utf-8") as f:
            text = f.read()
    except (OSError, UnicodeDecodeError) as e:
        print(f"error: cannot read {args.file}: {e}", file=sys.stderr)
        return 2
    docs = parse_text(text)
    names = [out_name(doc, i, len(docs)) for i, doc in enumerate(docs)]
    if len({name.casefold() for name in names}) != len(names):
        print("error: scenario IDs produce duplicate output filenames; give each scenario a unique ID.", file=sys.stderr)
        return 2
    os.makedirs(args.out, exist_ok=True)
    rc = 0
    for i, doc in enumerate(docs):
        path = os.path.join(args.out, names[i])
        write_atomic(path, doc)
        print(f"{doc['status']:17} -> {path}")
        if args.explain:
            print(explain(doc))
        if getattr(args, "adr", False) and doc["stack"]:
            with open(path[:-len("_output.json")] + "_adr.md", "w", encoding="utf-8", newline="\n") as f:
                f.write(adr(doc))
        if doc["status"] == "invalid_input":
            rc = 1
    return rc


def ask(prompt, default=None, kind="str", choices=None):
    hint = f" [{default}]" if default is not None else ""
    if choices:
        hint = f" ({'/'.join(choices)}){hint}"
    while True:
        raw = input(f"{prompt}{hint}: ").strip()
        if not raw:
            if default is not None:
                raw = str(default)
            else:
                print("  required")
                continue
        try:
            if kind == "int":
                return int(raw)
            if kind == "num":
                return float(raw) if "." in raw else int(raw)
            if kind == "bool":
                if raw.lower() in ("y", "yes", "true", "1"):
                    return True
                if raw.lower() in ("n", "no", "false", "0"):
                    return False
                raise ValueError
            if kind == "list":
                return [x.strip() for x in raw.split(",") if x.strip()] if raw != "-" else []
            if kind == "optint":
                return None if raw.lower() in ("none", "null", "-") else int(raw)
        except ValueError:
            print("  invalid value, try again")
            continue
        if choices and kind == "str" and raw not in choices:
            print("  choose one of the listed values")
            continue
        if choices and kind == "list" and not all(x in choices for x in raw.split(",")):
            pass
        return raw


def cmd_interactive(args):
    from engine.validate import PROJECT_TYPES, PLATFORMS
    print(f"StackSense {ENGINE_VERSION} interactive input. Enter keeps the default; lists are comma-separated ('-' for empty).")
    s = {"scenario_id": ask("Scenario id", "INTERACTIVE")}
    s["project"] = {"name": ask("Project name", ""), "type": ask("Project type", "web_app", choices=PROJECT_TYPES),
                    "description": ask("Description", ""), "platforms": ask("Platforms", "web", "list", PLATFORMS)}
    s["scale"] = {"users_at_launch": ask("Users at launch", kind="int"), "users_12_months": ask("Users after 12 months", kind="int"),
                  "peak_concurrent_users": ask("Peak concurrent users", 0, "int"),
                  "traffic_pattern": ask("Traffic pattern", "steady", choices=["steady", "spiky", "seasonal"]),
                  "workload": ask("Workload", "balanced", choices=["read_heavy", "balanced", "write_heavy"]),
                  "data_volume_gb_12_months": ask("Data volume after 12 months (GB)", 1, "num")}
    s["team"] = {"size": ask("Team size", kind="int"), "experience": ask("Experience", "intermediate", choices=["beginner", "intermediate", "senior", "mixed"]),
                 "languages": ask("Languages", "-", "list"), "has_devops": ask("Has DevOps (y/n)", "n", "bool")}
    s["budget"] = {"monthly_infra_usd": ask("Monthly infra budget USD", kind="num")}
    s["timeline"] = {"mvp_weeks": ask("MVP weeks", kind="int")}
    s["infrastructure"] = {"cloud_preference": ask("Cloud preference", "any", choices=["any", "aws", "gcp", "azure", "none"]),
                           "deployment_model": ask("Deployment model", "managed_cloud", choices=["managed_cloud", "self_hosted_cloud_vm", "on_premise", "air_gapped"]),
                           "data_residency": ask("Data residency", "none", choices=["none", "india", "eu", "us", "other"]),
                           "existing_systems": ask("Existing systems", "-", "list")}
    s["requirements"] = {k: ask(k.replace("_", " ").capitalize() + " (y/n)", "n", "bool") for k in
                         ("realtime", "offline_support", "full_text_search", "file_media_storage", "payments", "multi_tenant", "seo_critical")}
    s["requirements"]["auth"] = ask("Auth", "none", choices=["none", "email_password", "social", "phone_otp", "enterprise_sso"])
    s["requirements"]["ml_features"] = ask("ML features", "none", choices=["none", "inference_api", "llm_rag", "training"])
    s["requirements"]["availability"] = ask("Availability", "99.9", choices=["99", "99.9", "99.95", "99.99"])
    s["requirements"]["p95_latency_ms"] = ask("p95 latency ms (or none)", "none", "optint")
    s["compliance"] = ask("Compliance", "-", "list")
    s["priorities"] = {k: ask(f"Priority {k} (1-5)", 3, "int") for k in
                       ("cost", "time_to_market", "scalability", "performance", "maintainability", "security")}
    if ask("Add optional extra inputs (request rate, user geography, hiring plan, lock-in tolerance, RTO/RPO)? (y/n)", "n", "bool"):
        rps = ask("Peak requests per second (or none)", "none", "optint")
        if rps is not None:
            s["scale"]["peak_rps"] = rps
        geo = ask("User geography", "single_region", choices=["single_region", "multi_region", "global"])
        s["scale"]["geo_spread"] = geo
        s["team"]["hiring_languages"] = ask("Languages you plan to hire for", "-", "list")
        s["infrastructure"]["lock_in_tolerance"] = ask("Vendor lock-in tolerance", "medium", choices=["low", "medium", "high"])
        for key, label in (("rto_minutes", "Recovery time objective, minutes"), ("rpo_minutes", "Recovery point objective, minutes")):
            v = ask(f"{label} (or none)", "none", "optint")
            if v is not None:
                s["requirements"][key] = v
    os.makedirs(args.out, exist_ok=True)
    scen = os.path.join(args.out, out_name(s, 0, 1)[:-len("_output.json")] + "_input.json")
    write_atomic(scen, s)
    print(f"Saved input -> {scen}")
    args.file = scen
    args.explain = True
    return cmd_run(args)


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):  # redirected output on a cp1252 Windows console must not crash on arrows
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    ap =argparse.ArgumentParser(prog="stacksense", description="Deterministic tech-stack recommendation engine (no LLM).")
    ap.add_argument("--version", action="version", version=f"StackSense {ENGINE_VERSION}")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="evaluate a scenario JSON file (object or array)")
    r.add_argument("file")
    r.add_argument("--out", default="outputs")
    r.add_argument("--explain", action="store_true", help="also print a readable explanation")
    r.add_argument("--adr", action="store_true", help="also write <id>_adr.md: one decision record per core layer")
    r.add_argument("--no-llm", action="store_true", help="LLM-off switch (the engine never uses an LLM; accepted for the judge test)")
    i = sub.add_parser("interactive", help="answer prompts for every standard field, then evaluate")
    i.add_argument("--out", default="outputs")
    i.add_argument("--no-llm", action="store_true")
    w = sub.add_parser("serve", help="optional local web UI on 127.0.0.1 (standard library only)")
    w.add_argument("--port", type=int, default=8765)
    w.add_argument("--no-llm", action="store_true")
    f = sub.add_parser("fields", help="list every input with type, default, rule and the decisions it affects")
    f.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args(argv)
    if args.cmd == "fields":
        from engine.fields import render
        print(render(args.json))
        return 0
    if args.cmd == "serve":
        from engine.web import serve
        return serve(args.port)
    try:
        return cmd_run(args) if args.cmd == "run" else cmd_interactive(args)
    except OSError as e:
        print(f"error: cannot write output: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
