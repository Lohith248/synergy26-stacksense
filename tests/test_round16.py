"""Round 16 (12 Nov session): blind round 5 misses - team experience phrasing names the team's language or framework
(D03), "GPs" is not GPS (D12), and a residency requirement stated in prose while data_residency is 'none' (D12).
Each test written before the change."""
import copy
import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

from engine.run import evaluate  # noqa: E402
from engine.context import desc_signals, primary_langs  # noqa: E402
from test_round9 import PUBLIC, dump  # noqa: E402

BLIND5 = os.path.join(ROOT, "..", "research", "blind5")


def blind(fn):
    with open(os.path.join(BLIND5, fn), encoding="utf-8") as f:
        return json.load(f)


def P(sid, **kw):
    s = copy.deepcopy(PUBLIC[sid])
    for path, v in kw.items():
        node, parts = s, path.split(".")
        for p in parts[:-1]:
            node = node.setdefault(p, {})
        node[parts[-1]] = v
    return evaluate(s, counterfactuals=False)


def warn(out, code):
    return next((w for w in out["warnings"] if w["code"] == code), None)


class Item1ExperiencePhrasing(unittest.TestCase):
    def test_unit_experience_names_language_or_framework(self):
        for desc, want in (("Our three developers have built and maintained Laravel apps for years.", ["php"]),
                           ("We have shipped Django services for six years.", ["python"]),
                           ("Our team has years of Spring Boot experience.", ["java"]),
                           ("Our engineers are experienced with Phoenix.", ["elixir"]),
                           ("We've been writing Rails for a decade.", ["ruby"]),
                           ("The team has built ASP.NET Core APIs and Symfony sites.", ["csharp", "php"]),
                           ("We have deep experience in FastAPI and Flask.", ["python"])):
            self.assertEqual(primary_langs(desc), want, desc)

    def test_unit_exclusions_still_hold(self):
        for desc in ("We have never built Rails apps.", "Our previous team had built Laravel apps for years.",
                     "We will hire developers with years of Django experience.", "The client has run Spring campaigns for years.",
                     "We have run Spring sales every year.", "We have built Rails-style admin screens.",
                     "Our consultants have years of Java experience.", "We are not experienced with Laravel."):
            self.assertEqual(primary_langs(desc), [], desc)

    def test_d03_picks_laravel(self):
        self.assertEqual(evaluate(blind("D03_FixItLaravel.json"), counterfactuals=False)["stack"]["backend"]["kb_id"], "php-laravel")

    def test_only_listed_language_promoted(self):
        b2 = P("P2")["stack"]["backend"]["choice"]
        out = P("P2", **{"project.description": PUBLIC["P2"]["project"]["description"] + " Our developers have built Laravel apps for years."})
        self.assertEqual(out["stack"]["backend"]["choice"], b2)


class Item2GpsAcronym(unittest.TestCase):
    def test_unit(self):
        g = lambda d: any(desc_signals(d)[0][k] for k in ("gps", "media"))  # noqa: E731  (signal split into gps + media, 13 Nov)
        for d in ("Appointment booking for independent GPs and physiotherapists.", "Our gps practice list.",
                  "Phototherapy clinic bookings.", "A telephoto lens shop catalogue."):
            self.assertFalse(g(d), d)
        for d in ("Field staff upload GPS-tagged photos.", "Vans report gps coordinates every minute.", "Track gps location of riders.",
                  "Users share a photo of the damage.", "Photographs of meters are attached.", "Inspectors geotag each site."):
            self.assertTrue(g(d), d)

    def test_d12_no_postgis(self):
        self.assertNotIn("PostGIS", dump(evaluate(blind("D12_RdvSante.json"), counterfactuals=False)))


class Item3ResidencyStatedInDescription(unittest.TestCase):
    def test_enum_place_pins_and_warns(self):
        out = P("P1", **{"project.description": PUBLIC["P1"]["project"]["description"] + " Customer records must stay in Germany."})
        w = warn(out, "RESIDENCY_STATED_IN_DESCRIPTION")
        self.assertIsNotNone(w)
        self.assertIn("Customer records must stay in Germany.", w["message"])
        self.assertIn("infrastructure.data_residency", w["fields"])
        self.assertIn("project.description", w["fields"])
        self.assertIn("the EU", w["message"])
        out = P("P3", **{"project.description": PUBLIC["P3"]["project"]["description"] + " Customer data must be stored in the United States."})
        self.assertIn("the US", warn(out, "RESIDENCY_STATED_IN_DESCRIPTION")["message"])
        self.assertEqual(out["stack"]["database"]["data_location"], "us")

    def test_country_pins(self):
        out = P("P3", **{"project.description": PUBLIC["P3"]["project"]["description"] + " All patient data must be stored in Japan."})
        w = warn(out, "RESIDENCY_STATED_IN_DESCRIPTION")
        self.assertIsNotNone(w)
        self.assertIn("Japan", w["message"])
        self.assertIsNone(warn(out, "RESIDENCY_FROM_DESCRIPTION"))
        self.assertIn("Japan", dump(out["stack"]))

    def test_ambiguous_warns_only(self):
        out = evaluate(blind("D12_RdvSante.json"), counterfactuals=False)
        w = warn(out, "RESIDENCY_STATED_IN_DESCRIPTION")
        self.assertIsNotNone(w)
        self.assertIn("Patient data has to stay in Europe", w["message"])
        self.assertIn("'none'", w["message"])
        self.assertIn("not pinned", w["message"])
        self.assertIn("plausible: the EU, United Kingdom, Switzerland", w["message"])
        self.assertNotIn('.".', w["message"])

    def test_hds_info(self):
        w = warn(evaluate(blind("D12_RdvSante.json"), counterfactuals=False), "HEALTH_DATA_HOSTING_CERT")
        self.assertIsNotNone(w)
        self.assertEqual(w["severity"], "info")

    def test_negated_or_field_set_no_warning(self):
        out = P("P1", **{"project.description": PUBLIC["P1"]["project"]["description"] + " Data does not need to stay in India."})
        self.assertIsNone(warn(out, "RESIDENCY_STATED_IN_DESCRIPTION"))
        out = P("P2", **{"project.description": PUBLIC["P2"]["project"]["description"] + " Customer records must stay in Germany."})
        self.assertIsNone(warn(out, "RESIDENCY_STATED_IN_DESCRIPTION"))

    def test_public_unaffected(self):
        for sid in PUBLIC:
            out = P(sid)
            self.assertIsNone(warn(out, "RESIDENCY_STATED_IN_DESCRIPTION"), sid)
            self.assertIsNone(warn(out, "HEALTH_DATA_HOSTING_CERT"), sid)


if __name__ == "__main__":
    unittest.main()
