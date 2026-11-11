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



def iot(deployment='managed_cloud'):
    s = copy.deepcopy(PUBLIC[5])  # P6 runs on GCP
    s['project'].update(type='iot', description='Sensors publish temperature telemetry via MQTT and trigger alerts.')
    if deployment != 'managed_cloud':
        s['infrastructure'].update(cloud_preference='none', deployment_model=deployment)
    return evaluate(s, counterfactuals=False)


class IotBroker(unittest.TestCase):
    def test_cloud_broker_has_its_own_priced_vm_next_to_the_http_host(self):
        out = iot()
        host = out['stack']['hosting']['choice']
        self.assertIn('Cloud Run', host)
        broker = next(x for x in out['stack']['supporting'] if 'Mosquitto' in x['choice'])
        self.assertIn('Compute Engine', broker['choice'])
        self.assertIn('asia-south1', broker['choice'])
        self.assertIn('TCP', broker['justification'])
        line = next(a for a in out['estimated_monthly_cost_usd']['assumptions'] if 'Mosquitto' in a)
        self.assertNotIn('$0-0', line)
        self.assertIn('e2-small at $0.017-0.018/hour', line)

    def test_on_premise_broker_runs_on_the_existing_servers_at_no_cloud_cost(self):
        out = iot('on_premise')
        broker = next(x for x in out['stack']['supporting'] if 'Mosquitto' in x['choice'])
        self.assertNotIn('Compute Engine', broker['choice'])
        self.assertEqual(broker['deployment'], 'self_hosted')
        self.assertIn('same servers', broker['justification'])
        self.assertFalse(any('Mosquitto' in a for a in out['estimated_monthly_cost_usd']['assumptions']))



class LambdaFramework(unittest.TestCase):
    def test_django_on_lambda_names_the_adapter_and_connection_limits(self):
        s = copy.deepcopy(PUBLIC[5])
        s['infrastructure']['cloud_preference'] = 'aws'
        out = evaluate(s, counterfactuals=False)
        host = out['stack']['hosting']
        self.assertIn('Lambda', host['choice'])
        self.assertIn('Django', out['stack']['backend']['choice'])
        text = host['justification'] + ' '.join(host['tradeoffs'])
        self.assertIn('Lambda Web Adapter', text)
        self.assertIn('CONN_MAX_AGE', text)
        self.assertIn('RDS Proxy', text)



class TrainingCostBasis(unittest.TestCase):
    def test_training_band_states_its_gpu_hour_basis(self):
        s = copy.deepcopy(PUBLIC[5])
        s['infrastructure']['cloud_preference'] = 'aws'
        s['requirements']['ml_features'] = 'training'
        out = evaluate(s, counterfactuals=False)
        ml = next(x for x in out['stack']['supporting'] if x['layer'] == 'ml')
        self.assertIn('SageMaker', ml['choice'])
        line = next(a for a in out['estimated_monthly_cost_usd']['assumptions'] if a.startswith('ml:'))
        self.assertIn('GPU-hours', line)
        self.assertIn('$0.736/hour', line)



class MarginScope(unittest.TestCase):
    def test_readme_scopes_margin_and_pareto_to_the_layers_that_have_them(self):
        for s in PUBLIC:
            stack = evaluate(copy.deepcopy(s), counterfactuals=False)['stack']
            self.assertNotIn('score_margin', stack['frontend'])
            self.assertNotIn('pareto', stack['frontend'])
        readme = (ROOT / 'README.md').read_text(encoding='utf-8')
        self.assertFalse('each core component has `kb_id`, `score_margin`' in readme)
        self.assertFalse('for each core layer, the score margin' in readme)
        self.assertIn('backend, database and hosting', readme)



def severity(out, code):
    return next(w['severity'] for w in out['warnings'] if w['code'] == code)


class Section6Contradictions(unittest.TestCase):
    """Statement 6 names these as contradictions: critical warning plus a clearly labelled relaxed recommendation,
    at the extreme only (as SCALE_VS_BUDGET); milder forms stay warnings."""
    def solo(self, i, avail):
        s = copy.deepcopy(PUBLIC[i])
        s['team'].update(size=1, experience='beginner', has_devops=False)
        s['requirements']['availability'] = avail
        return evaluate(s, counterfactuals=False)

    def test_solo_beginner_with_99_99_on_a_dynamic_app_is_critical_and_relaxed(self):
        out = self.solo(2, '99.99')
        self.assertEqual(severity(out, 'AVAILABILITY_VS_TEAM'), 'critical')
        self.assertIn('AVAILABILITY_VS_TEAM', out['summary'].split(').')[0])
        self.assertTrue(any(a.startswith('Relaxed: requirements.availability') for a in out['assumptions']))

    def test_milder_availability_conflicts_stay_warnings(self):
        self.assertEqual(severity(self.solo(2, '99.95'), 'AVAILABILITY_VS_TEAM'), 'warning')
        self.assertEqual(severity(self.solo(0, '99.99'), 'AVAILABILITY_VS_TEAM'), 'warning')  # static site, no servers to run

    def scope(self, weeks, size):
        s = copy.deepcopy(PUBLIC[1])
        s['project']['platforms'] = ['web', 'android', 'ios']
        s['timeline']['mvp_weeks'] = weeks
        s['team']['size'] = size
        return evaluate(s, counterfactuals=False)

    def test_many_platforms_in_very_few_person_weeks_is_critical_and_relaxed(self):
        out = self.scope(2, 3)
        self.assertEqual(severity(out, 'TIMELINE_VS_SCOPE'), 'critical')
        self.assertTrue(out['summary'].startswith('Relaxed recommendation'))
        self.assertIn('web first', next(w['message'] for w in out['warnings'] if w['code'] == 'TIMELINE_VS_SCOPE'))

    def test_aggressive_but_staffed_timeline_stays_a_warning(self):
        self.assertEqual(severity(self.scope(4, 5), 'TIMELINE_VS_SCOPE'), 'warning')



class WebContentLength(unittest.TestCase):
    def test_malformed_content_length_is_http_400(self):
        import http.client
        import threading
        from engine.web import make_server
        srv = make_server(0)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            for bad in ('abc', '1.5', ''):
                with self.subTest(content_length=bad):
                    conn = http.client.HTTPConnection('127.0.0.1', srv.server_address[1], timeout=10)
                    conn.putrequest('POST', '/api/evaluate')
                    conn.putheader('Content-Length', bad)
                    conn.endheaders()
                    resp = conn.getresponse()
                    self.assertEqual(resp.status, 400)
                    self.assertIn('error', json.loads(resp.read()))
                    conn.close()
        finally:
            srv.shutdown()
            srv.server_close()



class SmallDatabasePlanBasis(unittest.TestCase):
    def db_line(self, i):
        out = evaluate(copy.deepcopy(PUBLIC[i]), counterfactuals=False)
        return next(a for a in out['estimated_monthly_cost_usd']['assumptions'] if a.startswith('Database '))

    def test_p5_azure_sql_serverless_band_states_its_auto_pause_basis(self):
        line = self.db_line(4)
        self.assertIn('$15-80', line)
        self.assertIn('auto-pause', line)
        self.assertIn('vCore-hours', line)
        self.assertIn('S0', line)

    def test_p6_cloud_sql_band_flags_shared_core_sla_and_unverified_price(self):
        line = self.db_line(5)
        self.assertIn('$10-30', line)
        self.assertIn('shared-core', line)
        self.assertIn('SLA', line)
        self.assertIn('db-g1-small', line)



class OnPremTraining(unittest.TestCase):
    def test_self_hosted_training_has_no_cloud_fee(self):
        for dep in ('on_premise', 'air_gapped'):
            with self.subTest(dep=dep):
                s = copy.deepcopy(PUBLIC[5])
                s['infrastructure'].update(cloud_preference='none', deployment_model=dep)
                s['requirements'].update(auth='email_password', ml_features='training')
                out = evaluate(s, counterfactuals=False)
                ml = next(x for x in out['stack']['supporting'] if x['layer'] == 'ml')
                self.assertEqual(ml['deployment'], 'self_hosted')
                self.assertFalse(any(a.startswith('ml:') for a in out['estimated_monthly_cost_usd']['assumptions']))
                self.assertIn('GPU', ' '.join(ml['tradeoffs']))

    def test_managed_training_keeps_its_band(self):
        s = copy.deepcopy(PUBLIC[5])
        s['requirements']['ml_features'] = 'training'
        out = evaluate(s, counterfactuals=False)
        self.assertTrue(any(a.startswith('ml:') for a in out['estimated_monthly_cost_usd']['assumptions']))



class StoredDataRate(unittest.TestCase):
    def stored(self, out):
        return next(a for a in out['estimated_monthly_cost_usd']['assumptions'] if a.startswith('Stored data'))

    def test_data_without_object_storage_is_priced_at_database_ssd_rates(self):
        s = copy.deepcopy(PUBLIC[5])
        s['requirements']['file_media_storage'] = False
        s['project']['description'] = 'NGO field agents fill crop surveys; data syncs when signal is available.'
        out = evaluate(s, counterfactuals=False)
        self.assertFalse(any(x['layer'] == 'storage' for x in out['stack']['supporting']))
        line = self.stored(out)
        self.assertIn('database', line)
        self.assertIn('$0.10-0.25/GB-month', line)

    def test_object_storage_case_states_the_split(self):
        line = self.stored(evaluate(copy.deepcopy(PUBLIC[5]), counterfactuals=False))
        self.assertIn('$0.02-0.035/GB-month', line)
        self.assertIn('object storage', line)



class RenderedSourceWording(unittest.TestCase):
    """Wording checked against pages rendered on 11 Nov 2026 (RBI FAQ 130, PCI FAQ 1588, redis.io licences,
    aws.amazon.com/apprunner, spring.io support table, Oracle Java SE roadmap)."""
    def warn(self, out, code):
        return next(w['message'] for w in out['warnings'] if w['code'] == code)

    def test_rbi_window_and_pci_saq_a_conditions(self):
        s = copy.deepcopy(PUBLIC[3])  # P4: RBI + PCI fintech
        s['compliance'] = sorted(set(s['compliance']) | {'rbi_localisation', 'pci_dss'})
        out = evaluate(s, counterfactuals=False)
        rbi = self.warn(out, 'RBI_LOCALISATION')
        self.assertIn('one business day or 24 hours', rbi)
        self.assertNotIn('backups and logs', rbi)
        pci = self.warn(out, 'PCI_SCOPE')
        self.assertIn('acquirer', pci)
        self.assertIn('script', pci)

    def test_dpdp_breach_note_is_not_an_unqualified_72_hour_rule(self):
        s = copy.deepcopy(PUBLIC[1])
        s['compliance'] = sorted(set(s['compliance']) | {'dpdp'})
        dpdp = self.warn(evaluate(s, counterfactuals=False), 'DPDP_OBLIGATIONS')
        self.assertNotIn('(72 h to the Board under the 2025 Rules)', dpdp)
        self.assertIn('phases', dpdp)

    def test_redis_licence_and_app_runner_date(self):
        src = (ROOT / 'engine' / 'services.py').read_text(encoding='utf-8')
        self.assertTrue('Redis 8+ adds an AGPLv3 option' in src)
        rows = json.loads((ROOT / 'kb' / 'technologies.json').read_text(encoding='utf-8'))
        text = json.dumps(rows)
        self.assertTrue('"pattern": "app runner", "name": "AWS App Runner (closed to new customers)", "eol": "2026-04-30"' in text)
        sources = json.loads((ROOT / 'kb' / 'sources.json').read_text(encoding='utf-8'))
        self.assertIn('spring.io', sources['eol-spring-boot']['url'])
        self.assertIn('oracle.com', sources['eol-oracle-jdk']['url'])



class SummaryLength(unittest.TestCase):
    def test_every_summary_is_at_most_two_sentences(self):
        import re
        docs = [evaluate(copy.deepcopy(s), counterfactuals=False) for s in PUBLIC]
        for f in sorted((ROOT / 'scenarios' / 'edge_cases').glob('*.json')):
            docs += parse_text(f.read_text(encoding='utf-8'))
        for d in docs:
            if d['status'] == 'invalid_input':
                continue
            with self.subTest(sid=d.get('scenario_id'), status=d['status']):
                self.assertLessEqual(len(re.findall(r'[.!?](?:\s|$)', d['summary'])), 2, d['summary'])



class NoGenericJustification(unittest.TestCase):
    def test_balanced_priorities_still_get_a_specific_reason(self):
        for f in sorted((ROOT / 'scenarios' / 'hidden_like').glob('H*.json')) + sorted((ROOT / 'scenarios' / 'edge_cases').glob('*.json')):
            for out in parse_text(f.read_text(encoding='utf-8')):
                for layer in ('frontend', 'backend', 'database', 'hosting'):
                    if out.get('stack'):
                        with self.subTest(sid=out['scenario_id'], layer=layer):
                            self.assertNotIn('Best overall fit', out['stack'][layer]['justification'])



class PublicCitedSources(unittest.TestCase):
    """Every source cited by P1-P6 except TRAI DLT was rendered or read from vendor price data on 11 Nov 2026."""
    def test_p2_free_cdn_and_app_service_band_follow_the_vendor_pages(self):
        out = evaluate(copy.deepcopy(PUBLIC[1]), counterfactuals=False)
        cdn = next(x for x in out['stack']['supporting'] if x['layer'] == 'cdn')
        self.assertIn('business-critical', ' '.join(cdn['tradeoffs']))
        host = next(a for a in out['estimated_monthly_cost_usd']['assumptions'] if a.startswith('Hosting'))
        self.assertIn('$25-150/month', host)

    def test_cited_sources_are_verified(self):
        src = json.loads((ROOT / 'kb' / 'sources.json').read_text(encoding='utf-8'))
        for key in ('azure-appservice-pricing', 'azure-sql-pricing', 'aws-sagemaker', 'cloudflare-plans', 'postgis'):
            with self.subTest(key=key):
                self.assertEqual(src[key]['status'], 'verified')



class BudgetAtRisk(unittest.TestCase):
    def test_upper_bound_far_above_budget_is_a_warning_that_names_its_drivers(self):
        out = evaluate(copy.deepcopy(PUBLIC[1]), counterfactuals=False)  # P2: $150 budget
        w = next(x for x in out['warnings'] if x['code'] == 'BUDGET_AT_RISK')
        self.assertEqual(w['severity'], 'warning')
        self.assertIn('Hosting', w['message'])
        self.assertIn('Phone OTP', w['message'])
        self.assertEqual(out['status'], 'ok_with_warnings')

    def test_mild_overshoot_stays_info(self):
        s = copy.deepcopy(PUBLIC[1])
        cap = evaluate(copy.deepcopy(s), counterfactuals=False)['estimated_monthly_cost_usd']['max']
        s['budget']['monthly_infra_usd'] = round(cap * 0.75)
        w = next(x for x in evaluate(s, counterfactuals=False)['warnings'] if x['code'] == 'BUDGET_AT_RISK')
        self.assertEqual(w['severity'], 'info')



class BudgetOvershootWording(unittest.TestCase):
    def test_small_overshoot_is_a_percentage_not_1_0x(self):
        out = evaluate(copy.deepcopy(PUBLIC[3]), counterfactuals=False)  # P4: $6,219 vs $6,000
        msg = next(w['message'] for w in out['warnings'] if w['code'] == 'BUDGET_AT_RISK')
        self.assertNotIn('1.0x', msg)
        self.assertIn('4% above the $6000 budget', msg)



class SnsIndiaSmsRate(unittest.TestCase):
    def test_p4_otp_line_uses_the_aws_india_local_rate(self):
        out = evaluate(copy.deepcopy(PUBLIC[3]), counterfactuals=False)
        line = next(a for a in out['estimated_monthly_cost_usd']['assumptions'] if a.startswith('Phone OTP'))
        self.assertIn('$0.004', line)



class OnPremStoreBilling(unittest.TestCase):
    def test_app_store_billing_under_on_premise_is_a_flagged_external_dependency(self):
        sys.path.insert(0, str(ROOT / 'tools'))
        import perturb
        for dep in ('on_premise', 'air_gapped'):
            with self.subTest(dep=dep):
                s = copy.deepcopy(PUBLIC[5])  # Android app
                s['project']['type'] = 'gaming'
                s['requirements']['payments'] = True
                s['infrastructure'].update(cloud_preference='none', deployment_model=dep)
                out = evaluate(s, counterfactuals=False)
                self.assertEqual(perturb.hard_violations(out, s), [])
                pay = [x for x in out['stack']['supporting'] if x['layer'] == 'payments']
                if dep == 'air_gapped':  # no payment network at all: excluded with a critical warning
                    self.assertEqual(pay, [])
                    self.assertTrue(any(w['code'] == 'PAYMENTS_NEED_NETWORK' for w in out['warnings']))
                    continue
                self.assertIn('Google Play Billing', pay[0]['choice'])
                self.assertTrue(any(w['code'] == 'EXTERNAL_PAYMENT_GATEWAY' and w['severity'] == 'critical' for w in out['warnings']))


class RealtimeLocality(unittest.TestCase):
    """Section 8 locality: realtime=true on P6 (spiky field sync, not a collaborative app) may change the backend,
    but must not move hosting and the database to another cloud through a stacked WebSocket penalty."""
    def test_p6_realtime_keeps_provider(self):
        base = evaluate(copy.deepcopy(PUBLIC[5]), counterfactuals=False)['stack']
        s = copy.deepcopy(PUBLIC[5])
        s['requirements']['realtime'] = True
        st = evaluate(s, counterfactuals=False)['stack']
        for layer in ('hosting', 'database'):
            self.assertEqual(st[layer]['choice'], base[layer]['choice'], layer)

    def test_collaborative_p3_still_penalises_the_request_timeout(self):
        st = evaluate(copy.deepcopy(PUBLIC[2]), counterfactuals=False)['stack']
        self.assertIn('Azure App Service', st['hosting']['choice'])


class StaticOffline(unittest.TestCase):
    """Section 6 over-engineering: a static content site that must work offline needs a service-worker
    precache, not an application server and database."""
    def test_p1_offline_stays_static(self):
        sys.path.insert(0, str(ROOT / 'tools'))
        import check_contract
        base = evaluate(copy.deepcopy(PUBLIC[0]), counterfactuals=False)['stack']
        s = copy.deepcopy(PUBLIC[0])
        s['requirements']['offline_support'] = True
        out = evaluate(s, counterfactuals=False)
        self.assertEqual(check_contract.check(out), [])
        for layer in ('frontend', 'backend', 'database', 'hosting'):
            self.assertEqual(out['stack'][layer]['choice'], base[layer]['choice'], layer)
        off = [x for x in out['stack']['supporting'] if 'requirements.offline_support' in x['driven_by']]
        self.assertTrue(off and 'service worker' in off[0]['choice'].lower())
        self.assertNotIn('outbox', json.dumps(off))


class CurrentProductNames(unittest.TestCase):
    """Section 5.2: Google renamed Looker Studio to Data Studio (docs page rendered 12 Nov 2026)."""
    def test_gcp_analytics_names_data_studio(self):
        s = copy.deepcopy(PUBLIC[2])
        s['project']['type'] = 'data_analytics'
        s['infrastructure']['cloud_preference'] = 'gcp'
        text = json.dumps(evaluate(s, counterfactuals=False))
        self.assertIn('Data Studio', text)
        self.assertNotIn('"Looker Studio"', text)


class MoreEndOfLife(unittest.TestCase):
    """Section 6 deprecated technology: common EOL systems in existing_systems are flagged (dates from vendor
    pages rendered 12 Nov 2026); supported versions stay quiet."""
    CASES = {'PHP 8.1 site': '2025-12-31', 'php7 api': '2022-11-28', 'CentOS 7 servers': '2024-06-30',
             'Xamarin.Forms app': '2024-05-01', 'MongoDB 5.0': '2024-10-31', 'mongo 4.4 cluster': '2024-02-29',
             'Spring Boot 2.7 service': '2023-06-30', 'Django 3.2 app': '2024-04-01', 'Laravel 10 app': '2025-02-04',
             'Node 16 backend': '2023-09-11', 'Python 3.8 jobs': '2024-10-07', '.NET Core 3.1 API': '2022-12-13',
             '.NET 7 service': '2024-05-14', 'Angular 15 frontend': 'no longer supported', 'Internet Explorer 11 users': '2022-06-15'}

    def eol(self, system):
        s = copy.deepcopy(PUBLIC[4])
        s['infrastructure']['existing_systems'] = [system]
        return [w['message'] for w in evaluate(s, counterfactuals=False)['warnings'] if w['code'] == 'END_OF_LIFE_SYSTEM']

    def test_flagged(self):
        for system, needle in self.CASES.items():
            with self.subTest(system=system):
                msgs = self.eol(system)
                self.assertTrue(msgs and needle in msgs[0], msgs)

    def test_supported_versions_stay_quiet(self):
        for system in ('PHP 8.4 site', 'MongoDB 8.0', 'Angular 21 app', 'Django 5.2 app', 'Laravel 12 app', 'Spring Boot 4.0'):
            with self.subTest(system=system):
                self.assertEqual([m for m in self.eol(system) if 'reached end' in m or 'no longer' in m], [])


if __name__ == '__main__':
    unittest.main()
