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


class HardConstraintWarnings(unittest.TestCase):
    def test_unresolved_residency_is_critical_and_never_claimed_satisfied(self):
        s = copy.deepcopy(PUBLIC[5])
        s['infrastructure']['data_residency'] = 'other'
        out = evaluate(s, counterfactuals=False)
        self.assertEqual(next(w['severity'] for w in out['warnings'] if w['code'] == 'RESIDENCY_UNSPECIFIED'), 'critical')
        self.assertNotIn('Satisfies the hard constraints', out['stack']['hosting']['justification'])
        self.assertTrue(out['summary'].startswith('Relaxed recommendation'))

    def test_external_payment_and_identity_conflicts_are_critical(self):
        for onprem in (False, True):
            s = copy.deepcopy(PUBLIC[4] if onprem else PUBLIC[1])
            if onprem:
                s['infrastructure'].update(cloud_preference='none', deployment_model='on_premise')
                code = 'EXTERNAL_IDENTITY_PROVIDER'
            else:
                s['infrastructure']['data_residency'] = 'eu'
                s['compliance'] = ['gdpr']
                code = 'PAYMENT_DATA_LOCATION'
            out = evaluate(s, counterfactuals=False)
            self.assertEqual(next(w['severity'] for w in out['warnings'] if w['code'] == code), 'critical')
            self.assertTrue(any(a.startswith('Relaxed:') for a in out['assumptions']))

    def test_known_supported_public_case_has_no_new_critical_warning(self):
        out = evaluate(copy.deepcopy(PUBLIC[5]), counterfactuals=False)
        self.assertFalse(any(w['severity'] == 'critical' for w in out['warnings']))


class RestrictedServices(unittest.TestCase):
    def test_air_gap_social_login_really_uses_the_reported_local_fallback(self):
        s = copy.deepcopy(PUBLIC[4])
        s['infrastructure'].update(cloud_preference='none', deployment_model='air_gapped')
        s['requirements']['auth'] = 'social'
        out = evaluate(s, counterfactuals=False)
        auth = next(x for x in out['stack']['supporting'] if x['layer'] == 'auth')
        self.assertIn('Keycloak', auth['choice'])
        self.assertIn('local accounts', auth['justification'])
        self.assertNotIn('Google/GitHub', auth['choice'])
        self.assertEqual(auth['deployment'], 'self_hosted')
        self.assertTrue(any(w['code'] == 'SOCIAL_LOGIN_NEEDS_NETWORK' for w in out['warnings']))

    def test_restricted_web3_never_silently_adds_a_managed_rpc(self):
        for dep in ('on_premise', 'air_gapped'):
            s = copy.deepcopy(PUBLIC[4])
            s['infrastructure'].update(cloud_preference='none', deployment_model=dep, existing_systems=[])
            s['project']['description'] = 'NFT ownership checks on a public blockchain.'
            out = evaluate(s, counterfactuals=False)
            self.assertFalse(any('managed blockchain RPC' in x['choice'] for x in out['stack']['supporting']))
            self.assertTrue(any(w['code'] == 'BLOCKCHAIN_NEEDS_NETWORK' and w['severity'] == 'critical' for w in out['warnings']))

    def test_connected_social_login_still_lists_oauth(self):
        s = copy.deepcopy(PUBLIC[4])
        s['requirements']['auth'] = 'social'
        out = evaluate(s, counterfactuals=False)
        self.assertTrue(any('OAuth' in x['choice'] for x in out['stack']['supporting'] if x['layer'] == 'auth'))


class OnPremCost(unittest.TestCase):
    def test_local_storage_and_rag_do_not_acquire_managed_cloud_fees(self):
        s = copy.deepcopy(PUBLIC[5])
        s['infrastructure'].update(cloud_preference='none', deployment_model='air_gapped')
        s['requirements'].update(auth='email_password', ml_features='llm_rag')
        s['budget']['monthly_infra_usd'] = 1500
        out = evaluate(s, counterfactuals=False)
        cost = out['estimated_monthly_cost_usd']
        self.assertEqual((cost['min'], cost['max']), (0, 0))
        self.assertTrue(any('hardware' in x for x in cost['assumptions']))
        self.assertNotIn('BUDGET_FAR_ABOVE_NEED', [w['code'] for w in out['warnings']])
        ml = next(x for x in out['stack']['supporting'] if x['layer'] == 'ml')
        self.assertNotIn('managed model', ml['justification'])
        self.assertNotIn('Per-token cost', ml['tradeoffs'])

    def test_cloud_storage_keeps_its_cost(self):
        out = evaluate(copy.deepcopy(PUBLIC[5]), counterfactuals=False)
        self.assertGreater(out['estimated_monthly_cost_usd']['min'], 0)
        self.assertTrue(any('Stored data' in x for x in out['estimated_monthly_cost_usd']['assumptions']))


class ExplanationAccuracy(unittest.TestCase):
    def test_skill_override_is_not_described_as_a_score_tie(self):
        s = copy.deepcopy(PUBLIC[2])
        s['team']['languages'] = ['php']
        out = evaluate(s, counterfactuals=False)
        backend = out['stack']['backend']
        self.assertLess(backend['score_margin'], 0)
        reason = backend['alternatives'][0]['why_not']
        self.assertNotIn('Tied on score', reason)
        self.assertIn('team-language preference', reason)
        self.assertIn('higher', reason)

    def test_tiny_positive_budget_does_not_crash(self):
        for value in (1e-308, 5e-324):
            s = copy.deepcopy(PUBLIC[1])
            s['budget']['monthly_infra_usd'] = value
            out = evaluate(s)
            self.assertEqual(out['status'], 'ok_with_warnings')
            self.assertIn('BUDGET_EXCEEDED', [w['code'] for w in out['warnings']])



class FrontDoorShare(unittest.TestCase):
    def test_public_p2_keeps_the_exact_budget_share(self):
        out = evaluate(copy.deepcopy(PUBLIC[1]), counterfactuals=False)
        cdn = next(x for x in out['stack']['supporting'] if x['layer'] == 'cdn')
        self.assertIn('23% of the $150 budget', cdn['justification'])


if __name__ == '__main__':
    unittest.main()
