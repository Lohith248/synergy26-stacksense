"""Development-time helper: download endoflife.date cycle data into a local snapshot file.

NOT part of the engine. The engine never imports this module and makes no network call at run time; it reads only
kb/technologies.json. This script was used once (15 Nov 2026) to read the public endoflife.date API, a community-maintained
aggregator (repository licence MIT), as the starting point for lifecycle rows. Rows built from it cite one kb/sources.json
entry per product (url https://endoflife.date/<product>, marked as an aggregator snapshot, not the vendor's page).

Usage: python tools/fetch_eol_snapshot.py OUT.json product [product ...]
Python standard library only; generic User-Agent; no personal details are sent.
"""
import json
import sys
import urllib.error
import urllib.request

API = "https://endoflife.date/api/{}.json"


def fetch(product):
    req = urllib.request.Request(API.format(product), headers={"User-Agent": "kb-lifecycle-snapshot/1.0", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def main(argv):
    out, products = argv[1], argv[2:]
    snap, missing = {}, []
    for p in products:
        try:
            snap[p] = fetch(p)
        except (urllib.error.URLError, ValueError) as e:
            missing.append(f"{p}: {e}")
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"products": snap, "missing": missing}, f, indent=1)
    print(f"{len(snap)} products, {len(missing)} missing", *missing, sep="\n")


if __name__ == "__main__":
    main(sys.argv)
