"""Loads the curated knowledge base (kb/*.json) once."""
import json
import os

_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "kb")


def _no_duplicate_keys(pairs):
    """A repeated key silently drops the earlier entry (J1: four source ids were duplicated), so it is a load error."""
    keys = [k for k, _ in pairs]
    dup = sorted({k for k in keys if keys.count(k) > 1})
    if dup:
        raise ValueError(f"duplicate key(s) in the knowledge base: {', '.join(dup)}")
    return dict(pairs)


def _load(name):
    with open(os.path.join(_DIR, name), encoding="utf-8") as f:
        return json.load(f, object_pairs_hook=_no_duplicate_keys)


TECH = _load("technologies.json")
SOURCES = _load("sources.json")
ML = _load("ml.json")  # p1: ML/LLM serving, vector stores, tracking, GPU instance rows
AS_OF = TECH["as_of"]


def cite(ids):
    """Source ids -> list of URLs. An unknown id is a KB bug and fails loudly (exercised by the test suite)."""
    return [SOURCES[i]["url"] for i in ids]


def region_offered(service, region_label):
    """True/False when kb service_regions lists the service, None when the KB makes no claim.
    region_label is the host's region text, e.g. 'asia-south1 (Mumbai)'."""
    row = TECH.get("service_regions", {}).get(service)
    if not row or not region_label:
        return None
    return region_label.split(" ")[0] in row["regions"]
