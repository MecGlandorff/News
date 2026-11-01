"""Executable negative checks using an entirely synthetic offline archive."""
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

VALIDATOR = Path(__file__).resolve().parents[1] / 'casebook/labels/validate.py'
LABELS = 'research/casebook/labels/'


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


class ReferenceValidationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name)
        self.packets = self.repo / 'packets'
        self.manifest_path = LABELS + 'effective-reference.json'
        self.make_fixture()

    def write(self, relative, value):
        target = self.repo / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(value, indent=2) + '\n')

    def rows(self, relative, rows):
        target = self.repo / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(''.join(json.dumps(row) + '\n' for row in rows))

    def read(self, relative):
        return json.loads((self.repo / relative).read_text())

    def pin(self, relative):
        return {'path': relative, 'sha256': sha((self.repo / relative).read_bytes())}

    def make_fixture(self):
        self.ids = ['C90-p01', 'C90-p02']
        self.packet_paths = {pid: 'prefixes/C90/' + pid + '.json' for pid in self.ids}
        checkpoints = ['2026-01-01T00:00:00+00:00', '2026-01-02T00:00:00+00:00']
        observations = []
        for i, pid in enumerate(self.ids):
            observations.append({'observation_id': f'O00{i+1}', 'source_version_id': f'S00{i+1}',
                                 'observed_at': checkpoints[i], 'fields': {'title': 'A title', 'text': 'abcdef'}})
            self.write('packets/' + self.packet_paths[pid], {'case_id': 'C90', 'prefix_id': pid,
                'chronology_mode': 'captured_observation', 'checkpoint_at': checkpoints[i],
                'source_version_ids': [o['source_version_id'] for o in observations], 'observations': copy.deepcopy(observations)})
        (self.packets / 'traversal.txt').write_text('\n'.join(self.packet_paths.values()) + '\n')
        self.write('research/casebook/freeze.json', {'packet_digest': 'fixture-inventory'})
        self.write('research/casebook/inventory.json', {'scope': 'synthetic offline test only'})
        self.write('research/casebook/cases.json', {'cases': [{'case_id': 'C90', 'chronology_mode': 'captured_observation',
            'checkpoints': [{'at': instant, 'add_observation_ids': [f'O00{i+1}']} for i, instant in enumerate(checkpoints)]}]})
        for directory in ('a', 'b', 'adjudicated', 'd-test', 'e-test'):
            rows = []
            wanted = self.ids[-1:] if directory in ('d-test', 'e-test') else self.ids
            for pid in wanted:
                i = self.ids.index(pid)
                packet_hash = self.pin('packets/' + self.packet_paths[pid])['sha256']
                record = {'case_id': 'C90', 'prefix_id': pid, 'labeler_id': directory,
                    'label_version': 'adjudicated-v1' if directory == 'adjudicated' else directory + '-v1',
                    'inventory_version': 'fixture-inventory', 'contributions': [{'id': 'c1', 'kind': 'context_only',
                    'claim': 'A synthetic claim', 'source_spans': [{'observation_id': 'O001', 'field': 'text', 'start': 0, 'end': 1}],
                    'attribution': None, 'occurrence_ref': None, 'story_ref': None, 'materiality': 'context', 'uncertainty': None}],
                    'relations': [], 'delta_expectations': [{'contribution_ids': ['c1'], 'status': 'prohibited', 'reason': 'synthetic context'}],
                    'questions': [], 'no_delta_reason': None, 'missing_evidence_reason': None, 'ambiguity_notes': [],
                    'adjudication_status': 'unadjudicated'}
                if directory == 'adjudicated':
                    record.update(adjudication_status='adjudicated_development_reference', decisions=[{'reason': 'fixture'}],
                        visible_observation_ids=[f'O00{j+1}' for j in range(i+1)], chronology_mode='captured_observation',
                        checkpoint_at=checkpoints[i], source_packet_sha256=packet_hash, label_inputs={
                            d: {'sha256': self.pin(LABELS + d + '/' + pid + '.json')['sha256']} for d in ('a', 'b')},
                        saved_at_utc=f'2026-02-0{i+1}T00:00:00+00:00')
                self.write(LABELS + directory + '/' + pid + '.json', record)
                row = {'prefix_id': pid, 'source_packet_sha256' if directory == 'adjudicated' else 'packet_sha256': packet_hash,
                    'adjudication_sha256' if directory == 'adjudicated' else 'label_sha256': self.pin(LABELS + directory + '/' + pid + '.json')['sha256']}
                if directory == 'adjudicated':
                    row.update(saved_at_utc=record['saved_at_utc'], label_inputs=record['label_inputs'])
                rows.append(row)
            self.rows(LABELS + directory + '/audit.jsonl', rows)
        self.rows(LABELS + 'c04/audit.jsonl', [])
        self.write(LABELS + 'adjudicated/eligibility.json', {'exclusions': [{'label_set': 'adjudicated-v1', 'prefix_ids': ['C90-p02']}]})
        self.rows(LABELS + 'adjudicated/eligibility.audit.jsonl', [{'sha256': self.pin(LABELS + 'adjudicated/eligibility.json')['sha256']}])
        amendment = {'amendment_version': 'locator-v2', 'original_record_sha256': {'C90-p01': self.pin(LABELS + 'adjudicated/C90-p01.json')['sha256']},
            'amendments': [{'amendment_id': 'span-1', 'affected_prefixes': ['C90-p01'], 'record_collection': 'contributions',
                'record_id': 'c1', 'append_source_spans': [{'observation_id': 'O001', 'field': 'text', 'start': 1, 'end': 2}]}]}
        rejected = copy.deepcopy(amendment)
        rejected['amendment_version'] = 'locator-rejected'
        rejected['amendments'][0]['append_source_spans'][0]['observation_id'] = 'O002'
        self.write(LABELS + 'adjudicated/span-amendments.rejected-v1.json', rejected)
        self.write(LABELS + 'adjudicated/span-amendments.json', amendment)
        previous = self.pin(LABELS + 'adjudicated/span-amendments.rejected-v1.json')['sha256']
        self.rows(LABELS + 'adjudicated/amendments.audit.jsonl', [{'sha256': previous}, {'sha256': self.pin(LABELS + 'adjudicated/span-amendments.json')['sha256'],
            'previous_version': previous, 'previous_artifact': 'span-amendments.rejected-v1.json'}])
        pid = self.ids[-1]
        gold = self.read(LABELS + 'adjudicated/' + pid + '.json')
        for key in ('visible_observation_ids', 'chronology_mode', 'checkpoint_at', 'source_packet_sha256', 'label_inputs'):
            gold.pop(key)
        inputs = {d: self.pin(LABELS + directory + '/' + pid + '.json')['sha256'] for d, directory in [('D', 'd-test'), ('E', 'e-test')]}
        gold.update(label_version='replacement-v2', adjudication_status='adjudicated', source_packet_raw_sha256=self.pin('packets/' + self.packet_paths[pid])['sha256'],
            label_input_raw_sha256=inputs, decisions=[{'d_refs': ['d-test/' + pid + '.json#/contributions/0'],
            'e_refs': ['e-test/' + pid + '.json#/contributions/0'], 'gold_refs': ['#/contributions/0']}])
        self.write(LABELS + 'replacement/' + pid + '.json', gold)
        self.rows(LABELS + 'replacement/audit.jsonl', [{'prefix_id': pid, 'freeze_order': 1, 'saved_at_utc': gold['saved_at_utc'],
            'packet_sha256': gold['source_packet_raw_sha256'], 'gold_sha256': self.pin(LABELS + 'replacement/' + pid + '.json')['sha256'], 'label_input_raw_sha256': inputs}])
        override = {'inventory_version': 'fixture-inventory', 'effective_prefixes': {pid: {'gold_file': LABELS + 'replacement/' + pid + '.json',
            'gold_sha256': self.pin(LABELS + 'replacement/' + pid + '.json')['sha256'], 'source_packet_raw_sha256': gold['source_packet_raw_sha256'],
            'label_input_raw_sha256': inputs, 'saved_at_utc': gold['saved_at_utc']}}, 'audit_file': LABELS + 'replacement/audit.jsonl',
            'audit_sha256': self.pin(LABELS + 'replacement/audit.jsonl')['sha256'], 'preserved_inputs': {
                d: {name: self.pin(LABELS + directory + '/' + name)['sha256'] for name in [pid + '.json', 'audit.jsonl']}
                for d, directory in [('D', 'd-test'), ('E', 'e-test')]}}
        self.write(LABELS + 'replacement/manifest.json', override)
        artifacts = {key: self.pin(path) for key, path in {
            'inventory': 'research/casebook/inventory.json', 'freeze': 'research/casebook/freeze.json', 'cases': 'research/casebook/cases.json',
            'eligibility': LABELS + 'adjudicated/eligibility.json', 'eligibility_audit': LABELS + 'adjudicated/eligibility.audit.jsonl',
            'amendment': LABELS + 'adjudicated/span-amendments.json', 'amendment_audit': LABELS + 'adjudicated/amendments.audit.jsonl',
            'rejected_amendment': LABELS + 'adjudicated/span-amendments.rejected-v1.json', 'override': LABELS + 'replacement/manifest.json'}.items()}
        manifest = {'inventory_version': 'fixture-inventory', 'active_amendment_version': 'locator-v2', 'artifacts': artifacts,
            'profiles': {'v1': {'label_version': 'adjudicated-v1', 'eligibility_set': 'adjudicated-v1'},
                         'v2': {'label_version': 'replacement-v2', 'eligibility_set': 'replacement-v2'}},
            'override_input_dirs': {'D': LABELS + 'd-test', 'E': LABELS + 'e-test'}, 'override_decision_keys': {'D': 'd_refs', 'E': 'e_refs'}, 'prefixes': []}
        for i, pid in enumerate(self.ids):
            manifest['prefixes'].append({'prefix_id': pid, 'profile': 'v1' if i == 0 else 'v2',
                'record': self.pin(LABELS + ('adjudicated' if i == 0 else 'replacement') + '/' + pid + '.json'),
                'packet': {'path': self.packet_paths[pid], 'sha256': self.pin('packets/' + self.packet_paths[pid])['sha256']},
                'active_amendment_ids': ['span-1'] if i == 0 else [],
                'active_amendment': {'version': 'locator-v2', 'sha256': artifacts['amendment']['sha256']} if i == 0 else None})
        self.write(self.manifest_path, manifest)

    def repin(self):
        """Refresh integrity pins so negative schema tests cannot pass on hashes alone."""
        manifest = self.read(self.manifest_path)
        override_path = manifest['artifacts']['override']['path']
        override = self.read(override_path)
        audit_path = override['audit_file']
        rows = [json.loads(line) for line in (self.repo / audit_path).read_text().splitlines()]
        for row in rows:
            selected = override['effective_prefixes'][row['prefix_id']]
            selected['gold_sha256'] = self.pin(selected['gold_file'])['sha256']
            row['gold_sha256'] = selected['gold_sha256']
        self.rows(audit_path, rows)
        override['audit_sha256'] = self.pin(audit_path)['sha256']
        self.write(override_path, override)
        for pin in manifest['artifacts'].values():
            pin['sha256'] = self.pin(pin['path'])['sha256']
        for entry in manifest['prefixes']:
            entry['record']['sha256'] = self.pin(entry['record']['path'])['sha256']
            if entry['active_amendment']:
                entry['active_amendment']['sha256'] = manifest['artifacts']['amendment']['sha256']
        self.write(self.manifest_path, manifest)

    def run_validator(self, optimized=False):
        command = [sys.executable] + (['-O'] if optimized else []) + [str(VALIDATOR), '--repository-root', str(self.repo), '--packet-root', str(self.packets)]
        result = subprocess.run(command, capture_output=True, text=True)
        return result, json.loads(result.stdout)

    def mutate_gold(self, change):
        path = LABELS + 'replacement/C90-p02.json'
        gold = self.read(path)
        change(gold)
        self.write(path, gold)
        self.repin()

    def test_effective_selection_and_archived_counts(self):
        result, output = self.run_validator()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(output['archived_v1']['gold_prefixes'], 2)
        self.assertEqual(output['effective_reference']['profiles'], {'v1': 1, 'v2': 1})

    def test_tampered_replacement_inputs_and_gold_are_rejected(self):
        for relative in ['d-test/C90-p02.json', 'e-test/audit.jsonl', 'replacement/C90-p02.json']:
            with self.subTest(relative=relative):
                path = self.repo / (LABELS + relative)
                original = path.read_bytes()
                path.write_bytes(original + b' ')
                self.assertNotEqual(self.run_validator()[0].returncode, 0)
                path.write_bytes(original)

    def test_exposed_old_selection_rejected_even_with_current_hash(self):
        manifest = self.read(self.manifest_path)
        manifest['prefixes'][1].update(profile='v1', record=self.pin(LABELS + 'adjudicated/C90-p02.json'))
        self.write(self.manifest_path, manifest)
        result, output = self.run_validator()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('excluded by eligibility', str(output))

    def test_inactive_or_rejected_amendment_rejected(self):
        manifest = self.read(self.manifest_path)
        manifest['prefixes'][0]['active_amendment_ids'] = []
        self.write(self.manifest_path, manifest)
        self.assertNotEqual(self.run_validator()[0].returncode, 0)
        manifest['prefixes'][0]['active_amendment_ids'] = ['span-1']
        manifest['artifacts']['amendment'] = manifest['artifacts']['rejected_amendment']
        self.write(self.manifest_path, manifest)
        self.assertNotEqual(self.run_validator()[0].returncode, 0)

    def test_missing_duplicate_unexpected_prefixes_rejected(self):
        original = self.read(self.manifest_path)
        for entries in [original['prefixes'][:1], original['prefixes'] + original['prefixes'][:1],
                        [dict(original['prefixes'][0], prefix_id='C90-p99'), original['prefixes'][1]]]:
            manifest = copy.deepcopy(original)
            manifest['prefixes'] = entries
            self.write(self.manifest_path, manifest)
            self.assertNotEqual(self.run_validator()[0].returncode, 0)

    def test_schema_errors_fail_after_refreshing_gold_hashes(self):
        original = self.read(LABELS + 'replacement/C90-p02.json')
        mutations = [lambda g: g['contributions'][0].pop('claim'),
            lambda g: g['contributions'][0].update(source_spans=[{'observation_id': 'O999', 'field': 'text', 'start': 0}]),
            lambda g: g['contributions'][0]['source_spans'][0].update(observation_id='O999'),
            lambda g: g['decisions'][0]['d_refs'].append('d-test/C90-p03.json#/contributions/0'),
            lambda g: g['label_input_raw_sha256'].update(D='0' * 64)]
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                self.write(LABELS + 'replacement/C90-p02.json', original)
                self.mutate_gold(mutation)
                self.assertNotEqual(self.run_validator()[0].returncode, 0)

    def test_out_of_bounds_rejected_under_python_optimized(self):
        self.mutate_gold(lambda g: g['contributions'][0]['source_spans'][0].update(end=999))
        result, output = self.run_validator(optimized=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('invalid span', str(output))

    def mutate_v1(self, mutation):
        path = LABELS + 'adjudicated/C90-p01.json'
        record = self.read(path)
        mutation(record)
        self.write(path, record)
        audit_path = LABELS + 'adjudicated/audit.jsonl'
        rows = [json.loads(line) for line in (self.repo / audit_path).read_text().splitlines()]
        rows[0].update(adjudication_sha256=self.pin(path)['sha256'], label_inputs=record['label_inputs'])
        self.rows(audit_path, rows)
        amendment_path = LABELS + 'adjudicated/span-amendments.json'
        amendment = self.read(amendment_path)
        amendment['original_record_sha256']['C90-p01'] = self.pin(path)['sha256']
        self.write(amendment_path, amendment)
        audit_path = LABELS + 'adjudicated/amendments.audit.jsonl'
        rows = [json.loads(line) for line in (self.repo / audit_path).read_text().splitlines()]
        rows[-1]['sha256'] = self.pin(amendment_path)['sha256']
        self.rows(audit_path, rows)
        self.repin()

    def test_future_observation_span_rejected_after_all_v1_pins_refreshed(self):
        self.mutate_v1(lambda g: g['contributions'][0]['source_spans'][0].update(observation_id='O002'))
        result, output = self.run_validator()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('invalid span', str(output))

    def test_v1_checkpoint_and_input_hash_rejected_after_audit_refresh(self):
        self.mutate_v1(lambda g: g.update(checkpoint_at='2026-01-03T00:00:00+00:00'))
        result, output = self.run_validator()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('chronology/checkpoint mismatch', str(output))
        self.mutate_v1(lambda g: g['label_inputs']['a'].update(sha256='0' * 64))
        self.assertNotEqual(self.run_validator()[0].returncode, 0)

    def test_replacement_input_schema_checked_after_all_hashes_refreshed(self):
        path = LABELS + 'd-test/C90-p02.json'
        record = self.read(path)
        record['contributions'][0].pop('claim')
        self.write(path, record)
        new_hash = self.pin(path)['sha256']
        self.rows(LABELS + 'd-test/audit.jsonl', [{'prefix_id': 'C90-p02', 'label_sha256': new_hash,
            'packet_sha256': self.pin('packets/' + self.packet_paths['C90-p02'])['sha256']}])
        override_path = LABELS + 'replacement/manifest.json'
        override = self.read(override_path)
        override['preserved_inputs']['D'].update({'C90-p02.json': new_hash,
            'audit.jsonl': self.pin(LABELS + 'd-test/audit.jsonl')['sha256']})
        override['effective_prefixes']['C90-p02']['label_input_raw_sha256']['D'] = new_hash
        self.write(override_path, override)
        gold_path = LABELS + 'replacement/C90-p02.json'
        gold = self.read(gold_path)
        gold['label_input_raw_sha256']['D'] = new_hash
        self.write(gold_path, gold)
        audit_path = LABELS + 'replacement/audit.jsonl'
        rows = [json.loads(line) for line in (self.repo / audit_path).read_text().splitlines()]
        rows[0]['label_input_raw_sha256']['D'] = new_hash
        self.rows(audit_path, rows)
        self.repin()
        result, output = self.run_validator()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('replacement input invalid/missing nested fields', str(output))

    def test_missing_replacement_original_is_not_ignored(self):
        (self.repo / (LABELS + 'e-test/C90-p02.json')).unlink()
        self.assertNotEqual(self.run_validator()[0].returncode, 0)

    def test_unsafe_paths_rejected(self):
        manifest = self.read(self.manifest_path)
        manifest['prefixes'][1]['record']['path'] = '../outside.json'
        self.write(self.manifest_path, manifest)
        result, output = self.run_validator()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('unsafe path', str(output))


if __name__ == '__main__':
    unittest.main()
