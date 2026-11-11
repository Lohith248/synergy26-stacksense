"""11 Nov review regressions; each class was run failing before its fix."""
import copy
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from engine.load import parse_text
from engine.run import evaluate
import stacksense

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


class ExportBoundary(unittest.TestCase):
    def test_interactive_id_cannot_write_outside_output_directory(self):
        answers = ['../outside', '', '', '', '', '10', '20', '', '', '', '',
                   '1', '', 'python', '', '10', '4', '', '', '', '-']
        answers += ['n'] * 7 + ['none', 'none', '99.9', 'none', '-'] + ['3'] * 6 + ['n']
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sentinel = root / 'outside_input.json'
            sentinel.write_text('keep this')
            with mock.patch('builtins.input', side_effect=answers), contextlib.redirect_stdout(io.StringIO()):
                rc = stacksense.main(['interactive', '--out', str(root / 'out')])
            self.assertEqual(rc, 0)
            self.assertEqual(sentinel.read_text(), 'keep this')
            self.assertTrue((root / 'out' / 'outside_input.json').exists())

    def test_colliding_ids_fail_before_any_output_is_replaced(self):
        for ids in (['same', 'same'], ['a/b', 'ab'], ['Case', 'case']):
            with self.subTest(ids=ids), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                source = root / 'input.json'
                source.write_text(json.dumps([{'scenario_id': sid} for sid in ids]))
                output = root / 'out'
                output.mkdir()
                sentinel = output / stacksense.out_name({'scenario_id': ids[0]}, 0, 2)
                sentinel.write_text('previous valid result')
                with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    rc = stacksense.main(['run', str(source), '--out', str(output)])
                self.assertEqual(rc, 2)
                self.assertEqual(sentinel.read_text(), 'previous valid result')
                self.assertEqual(len(list(output.iterdir())), 1)

    def test_unwritable_output_is_a_cli_error_not_a_traceback(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / 'input.json'
            source.write_text('{}')
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                rc = stacksense.main(['run', str(source), '--out', str(source)])
            self.assertEqual(rc, 2)
            self.assertEqual(source.read_text(), '{}')


if __name__ == '__main__':
    unittest.main()
