"""F4/A4 (blind8): a framework or skill the description names as the team's own ("devs already build Flutter apps", "solid
Elixir/Phoenix experience") feeds the language/stack fit of the matching layer, like the existing description-named language.
Tested on several layers and languages plus inputs where it must not fire. Inputs are inline."""
import copy
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from engine.context import primary_langs, team_frameworks  # noqa: E402
from engine.run import evaluate  # noqa: E402

BASE = {"scenario_id": "F4A4", "project": {"type": "web_app", "platforms": ["web"], "description": "x"},
        "scale": {"users_at_launch": 800, "users_12_months": 6000, "peak_concurrent_users": 150},
        "team": {"size": 4, "experience": "intermediate", "languages": ["typescript"], "has_devops": False},
        "budget": {"monthly_infra_usd": 800}, "timeline": {"mvp_weeks": 12},
        "infrastructure": {"cloud_preference": "any", "deployment_model": "managed_cloud", "data_residency": "none", "existing_systems": []},
        "requirements": {"auth": "email_password"}}


def run(desc, langs, plats=("web",), typ="web_app"):
    s = copy.deepcopy(BASE)
    s["project"].update(description=desc, platforms=list(plats), type=typ)
    s["team"]["languages"] = langs
    o = evaluate(s, counterfactuals=False)
    return o["stack"]["frontend"]["choice"], o["stack"]["backend"]["choice"], o


class Detection(unittest.TestCase):
    def test_phrasings_that_name_the_team_skill(self):
        cases = (("Both devs already build Flutter apps.", ["dart"], ("flutter",)),
                 ("Team has solid Elixir/Phoenix experience.", ["elixir"], ("elixir-phoenix",)),
                 ("Our team has strong Laravel experience.", ["php"], ("php-laravel",)),
                 ("Our developers have built React Native apps for years.", ["javascript"], ("react-native-expo",)),
                 ("The team writes Kotlin and SwiftUI.", ["kotlin", "swift"], ("swiftui",)))
        for desc, langs, fws in cases:
            with self.subTest(desc=desc):
                self.assertEqual(primary_langs(desc), langs)
                self.assertEqual(team_frameworks(desc), fws)

    def test_missing_thin_or_future_skills_are_not_named(self):
        for desc in ("We have no Elixir experience.", "The team has some Django experience.", "Plan to hire Flutter developers.",
                     "We are not a Laravel shop and want to avoid Rails.", "Unlike last year, nobody here uses Phoenix.",
                     "Flutter is trendy this year.", "A fast and swift checkout flow."):
            with self.subTest(desc=desc):
                self.assertEqual(team_frameworks(desc), (), desc)


class ChoiceEffect(unittest.TestCase):
    def test_mobile_named_framework_wins_a_near_tie(self):
        for desc, langs, want in (("Habit app. Both devs already build Flutter apps.", ["dart", "kotlin"], "Flutter"),
                                  ("Habit app. Our developers have built Flutter apps and Kotlin services.", ["dart", "kotlin"], "Flutter")):
            with self.subTest(desc=desc):
                self.assertIn(want, run(desc, langs, ("android", "ios"))[0])

    def test_without_the_sentence_the_choice_is_unchanged(self):
        self.assertIn("Kotlin Multiplatform", run("Habit app.", ["dart", "kotlin"], ("android", "ios"))[0])
        self.assertIn("Next.js", run("Booking tool.", ["elixir", "typescript"])[1])

    def test_backend_named_framework_beats_one_language_everywhere(self):
        for desc, langs, want in (("Booking tool. Team has solid Elixir/Phoenix experience.", ["elixir", "typescript"], "Phoenix"),
                                  ("Booking tool. The team knows Laravel well and uses it daily.", ["php", "typescript"], "Laravel")):
            with self.subTest(want=want):
                self.assertIn(want, run(desc, langs)[1])

    def test_negated_or_hiring_mentions_do_not_change_the_choice(self):
        base = run("Habit app.", ["dart", "kotlin"], ("android", "ios"))[0]
        for desc in ("Habit app. Plan to hire Flutter developers.", "Habit app. We do not build Flutter apps."):
            with self.subTest(desc=desc):
                self.assertEqual(run(desc, ["dart", "kotlin"], ("android", "ios"))[0], base)
        self.assertEqual(run("Booking tool. We have no Elixir experience.", ["elixir", "typescript"])[1],
                         run("Booking tool.", ["elixir", "typescript"])[1])

    def test_the_bonus_is_explained_in_the_justification(self):
        out = run("Habit app. Both devs already build Flutter apps.", ["dart", "kotlin"], ("android", "ios"))[2]
        self.assertIn("names Flutter as a framework the team already builds the mobile app with", out["stack"]["frontend"]["justification"])


if __name__ == "__main__":
    unittest.main()
