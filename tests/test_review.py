"""11 Nov review regressions; each class was run failing before its fix."""
import copy
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from engine.load import parse_text
from engine.run import evaluate

PUBLIC = json.loads((ROOT / 'scenarios/stacksense_public_scenarios.json').read_text())


class InputBoundary(unittest.TestCase):
    def test_deep_json_is_reported_instead_of_crashing(self):
        out = parse_text('[' * 1500 + '0' + ']' * 1500)[0]
        self.assertEqual(out['status'], 'invalid_input')
        self.assertEqual(out['validation_errors'][0]['field'], '$')

    def test_unrepresentable_numeric_fields_are_reported(self):
        for field in ('budget.monthly_infra_usd', 'scale.data_volume_gb_12_months',
                      'scale.users_12_months', 'team.size', 'requirements.rto_minutes'):
            with self.subTest(field=field):
                s = copy.deepcopy(PUBLIC[1])
                group, key = field.split('.')
                s[group][key] = 10 ** 400
                out = evaluate(s)
                self.assertEqual(out['status'], 'invalid_input')
                self.assertIn(field, [e['field'] for e in out['validation_errors']])

    def test_large_representable_values_remain_accepted(self):
        s = copy.deepcopy(PUBLIC[1])
        s['budget']['monthly_infra_usd'] = 10 ** 100
        self.assertNotEqual(evaluate(s)['status'], 'invalid_input')


if __name__ == '__main__':
    unittest.main()
