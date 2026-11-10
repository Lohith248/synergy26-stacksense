"""Loads the curated knowledge base (kb/*.json) once."""
import json
import os

_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "kb")


def _load(name):
    with open(os.path.join(_DIR, name), encoding="utf-8") as f:
        return json.load(f)


TECH = _load("technologies.json")
SOURCES = _load("sources.json")
AS_OF = TECH["as_of"]


def cite(ids):
    """Source ids -> list of URLs. An unknown id is a KB bug and fails loudly (exercised by the test suite)."""
    return [SOURCES[i]["url"] for i in ids]
