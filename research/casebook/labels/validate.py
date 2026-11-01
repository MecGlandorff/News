#!/usr/bin/env python3
"""Read-only verification of frozen source-only labels against local source packets."""
import argparse
import hashlib
import json
from pathlib import Path


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def load_json(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('duplicate JSON key: ' + key)
            result[key] = value
        return result
    return json.loads(raw, object_pairs_hook=unique)


def read_rows(path):
    return [load_json(line) for line in path.read_text().splitlines() if line.strip()]


def check_record(record, packet, references, strict, profile="v1"):
    """Check executable label contracts; hashes alone do not establish validity."""
    errors = []
    required = {'case_id', 'prefix_id', 'labeler_id', 'label_version',
                'inventory_version', 'contributions', 'relations',
                'delta_expectations', 'questions', 'no_delta_reason',
                'missing_evidence_reason', 'ambiguity_notes', 'adjudication_status'}
    if not isinstance(record, dict) or not required <= record.keys():
        return ['missing required top-level fields']
    for key in ('case_id', 'prefix_id', 'labeler_id', 'label_version', 'inventory_version', 'adjudication_status'):
        if not isinstance(record[key], str) or not record[key]:
            errors.append('invalid string field: ' + key)
    for key in ('no_delta_reason', 'missing_evidence_reason'):
        if record[key] is not None and not isinstance(record[key], str):
            errors.append('invalid nullable field: ' + key)
    collections = {'contributions': {'id', 'kind', 'claim', 'source_spans', 'attribution', 'occurrence_ref', 'story_ref', 'materiality', 'uncertainty'},
                   'relations': {'from', 'to', 'type', 'status', 'reason', 'source_spans'},
                   'delta_expectations': {'contribution_ids', 'status', 'reason'},
                   'questions': {'id', 'status', 'claim', 'source_spans', 'closure_reason'}}
    for name, keys in collections.items():
        if not isinstance(record[name], list) or any(not isinstance(x, dict) or not keys <= x.keys() for x in record[name]):
            return errors + ['invalid/missing nested fields: ' + name]
    if not isinstance(record['ambiguity_notes'], list) or any(not isinstance(x, str) for x in record['ambiguity_notes']):
        errors.append('invalid ambiguity notes')
    if (record['case_id'], record['prefix_id']) != (packet['case_id'], packet['prefix_id']):
        errors.append('packet identity mismatch')
    observations = {o['observation_id']: o for o in packet['observations']}
    current_ids = {c['id'] for c in record['contributions'] if isinstance(c['id'], str)}
    if len(current_ids) != len(record['contributions']):
        errors.append('invalid/duplicate contribution IDs')
    references.update(current_ids)
    for contribution in record['contributions']:
        for key in ('id', 'kind', 'claim', 'materiality'):
            if not isinstance(contribution[key], str) or not contribution[key]:
                errors.append('invalid contribution field: ' + key)
        for key in ('attribution', 'uncertainty', 'occurrence_ref', 'story_ref'):
            value = contribution[key]
            if value is not None and not isinstance(value, str):
                errors.append('invalid nullable contribution field: ' + key)
        references.update(contribution[k] for k in ('occurrence_ref', 'story_ref') if isinstance(contribution[k], str))
    question_ids = [q['id'] for q in record['questions']]
    if any(not isinstance(x, str) or not x for x in question_ids) or len(set(question_ids)) != len(question_ids):
        errors.append('invalid/duplicate question IDs')
    references.update(x for x in question_ids if isinstance(x, str))
    for name in ('contributions', 'relations', 'questions'):
        for item in record[name]:
            spans = item['source_spans']
            if not isinstance(spans, list):
                errors.append('invalid source_spans array')
                continue
            if name == 'contributions' and not spans:
                errors.append('contribution lacks evidence: ' + str(item['id']))
            for span in spans:
                valid = isinstance(span, dict) and set(span) == {'observation_id', 'field', 'start', 'end'}
                if valid:
                    valid = (isinstance(span['observation_id'], str) and span['field'] in ('text', 'title', 'description')
                             and type(span['start']) is int and type(span['end']) is int)
                if valid:
                    text = observations.get(span['observation_id'], {}).get('fields', {}).get(span['field'])
                    valid = isinstance(text, str) and 0 <= span['start'] < span['end'] <= len(text)
                if not valid:
                    errors.append('invalid span: ' + json.dumps(span, sort_keys=True))
    kinds = {'new_occurrence', 'same_occurrence_material_fact', 'source_correction',
             'question_opened', 'question_answered', 'question_closed', 'conflict', 'context_only'}
    for contribution in record['contributions']:
        if contribution['kind'] not in kinds:
            errors.append('invalid contribution kind: ' + str(contribution['id']))
    for relation in record['relations']:
        if any(not isinstance(relation[k], str) or not relation[k] for k in ('from', 'to', 'type', 'reason')):
            errors.append('invalid relation field')
        if relation['from'] not in references or relation['to'] not in references:
            errors.append('unresolved relation reference: ' + json.dumps(relation, sort_keys=True))
        if relation['status'] not in ('required', 'allowed', 'prohibited', 'uncertain'):
            errors.append('invalid relation status')
    for delta in record['delta_expectations']:
        permitted = current_ids if strict else references
        ids = delta['contribution_ids']
        if not isinstance(ids, list) or any(not isinstance(x, str) or x not in permitted for x in ids):
            errors.append('unresolved delta reference')
        if delta['status'] not in ('required', 'allowed', 'prohibited', 'uncertain'):
            errors.append('invalid delta status')
        if not isinstance(delta['reason'], str) or not delta['reason']:
            errors.append('invalid delta reason')
    for question in record['questions']:
        if question['status'] not in ('open', 'answered', 'closed'):
            errors.append('non-protocol question status: ' + str(question['id']) + '=' + str(question['status']))
        if not isinstance(question['claim'], str) or not question['claim']:
            errors.append('invalid question claim')
        if question['closure_reason'] is not None and not isinstance(question['closure_reason'], str):
            errors.append('invalid question closure_reason')
    if strict:
        if profile == 'v1':
            if record.get('visible_observation_ids') != list(observations):
                errors.append('visible observation accounting mismatch')
            if 'chronology_mode' not in record or 'checkpoint_at' not in record:
                errors.append('missing chronology/checkpoint metadata')
        if any(key in record and record[key] != packet[key] for key in ('chronology_mode', 'checkpoint_at')):
            errors.append('chronology/checkpoint mismatch')
        expected_status = {'v1': 'adjudicated_development_reference', 'v2': 'adjudicated'}[profile]
        if record['adjudication_status'] != expected_status:
            errors.append('unfrozen gold status')
        if not isinstance(record.get('decisions'), list) or not record['decisions']:
            errors.append('missing adjudication decisions')
    return errors


def safe_path(root, relative):
    path = Path(relative)
    if path.is_absolute() or '..' in path.parts or not path.parts:
        raise ValueError('unsafe path: ' + str(relative))
    resolved = (root / path).resolve()
    if not resolved.is_relative_to(root.resolve()):
        raise ValueError('unsafe path: ' + str(relative))
    return resolved


def checked_file(root, pin):
    raw = safe_path(root, pin['path']).read_bytes()
    if sha(raw) != pin['sha256']:
        raise ValueError('stale hash: ' + pin['path'])
    return raw


def json_pointer(document, pointer):
    if not pointer.startswith('/'):
        raise ValueError('invalid JSON Pointer')
    for token in pointer[1:].split('/'):
        token = token.replace('~1', '/').replace('~0', '~')
        document = document[int(token)] if isinstance(document, list) else document[token]
    return document


def validate_effective(repo, packet_root, manifest_path):
    manifest = load_json(manifest_path.read_text())
    artifacts = {key: checked_file(repo, pin) for key, pin in manifest['artifacts'].items()}
    freeze = load_json(artifacts['freeze'])
    inventory = freeze['packet_digest']
    if manifest['inventory_version'] != inventory:
        raise ValueError('effective inventory mismatch')
    cases = load_json(artifacts['cases'])['cases']
    expected_packets = {f"{case['case_id']}-p{i:02d}": (case, checkpoint)
                        for case in cases for i, checkpoint in enumerate(case['checkpoints'], 1)}
    expected = list(expected_packets)
    entries = manifest['prefixes']
    if [entry['prefix_id'] for entry in entries] != expected:
        raise ValueError('effective prefix coverage/order mismatch')
    eligibility = load_json(artifacts['eligibility'])
    eligibility_rows = [load_json(line) for line in artifacts['eligibility_audit'].decode().splitlines() if line.strip()]
    if eligibility_rows[-1]['sha256'] != sha(artifacts['eligibility']):
        raise ValueError('eligibility audit mismatch')
    amendment = load_json(artifacts['amendment'])
    amendment_rows = [load_json(line) for line in artifacts['amendment_audit'].decode().splitlines() if line.strip()]
    if amendment_rows[-1]['sha256'] != sha(artifacts['amendment']) or amendment['amendment_version'] != manifest['active_amendment_version']:
        raise ValueError('inactive amendment selected')
    override = load_json(artifacts['override'])
    if override['inventory_version'] != inventory:
        raise ValueError('override inventory mismatch')
    override_ids = list(override['effective_prefixes'])
    gold_dirs = {}
    for pid, selected in override['effective_prefixes'].items():
        gold_dirs.setdefault(str(Path(selected['gold_file']).parent), []).append(pid)
    for directory, desired in gold_dirs.items():
        if sorted(p.stem for p in safe_path(repo, directory).glob('C*-p*.json')) != sorted(desired):
            raise ValueError('override gold file coverage mismatch')
    audit_raw = checked_file(repo, {'path': override['audit_file'], 'sha256': override['audit_sha256']})
    override_rows = [load_json(line) for line in audit_raw.decode().splitlines() if line.strip()]
    if [row['prefix_id'] for row in override_rows] != override_ids or [row['freeze_order'] for row in override_rows] != list(range(1, len(override_ids) + 1)):
        raise ValueError('override audit coverage/order mismatch')
    times = [row['saved_at_utc'] for row in override_rows]
    if times != sorted(times) or len(set(times)) != len(times):
        raise ValueError('override save times not increasing')
    input_records = {}
    input_audits = {}
    for labeler, files in override['preserved_inputs'].items():
        directory = manifest['override_input_dirs'][labeler]
        for name, expected_hash in files.items():
            raw = checked_file(repo, {'path': str(Path(directory) / name), 'sha256': expected_hash})
            if name.endswith('.json'):
                input_records[(labeler, Path(name).stem)] = load_json(raw)
            elif name == 'audit.jsonl':
                rows = [load_json(line) for line in raw.decode().splitlines() if line.strip()]
                if [row['prefix_id'] for row in rows] != override_ids:
                    raise ValueError('replacement input audit coverage/order mismatch')
                input_audits[labeler] = {row['prefix_id']: row for row in rows}
        if sorted(p.stem for p in safe_path(repo, directory).glob('C*-p*.json')) != sorted(override_ids):
            raise ValueError('replacement input file coverage mismatch')
    errors, counts, active_ids = [], {}, set()
    for entry in entries:
        pid = entry['prefix_id']
        profile = entry['profile']
        if profile not in ('v1', 'v2'):
            raise ValueError('unknown record profile')
        eligibility_set = manifest['profiles'][profile]['eligibility_set']
        if any(pid in exclusion['prefix_ids'] and eligibility_set in exclusion['label_set'].split(',') for exclusion in eligibility['exclusions']):
            raise ValueError(pid + ': selected record is excluded by eligibility')
        packet_raw = checked_file(packet_root, entry['packet'])
        packet = load_json(packet_raw)
        case, checkpoint = expected_packets[pid]
        if (packet['prefix_id'], packet['case_id'], packet['chronology_mode'], packet['checkpoint_at']) != (pid, case['case_id'], case['chronology_mode'], checkpoint['at']):
            raise ValueError('effective packet identity/clock mismatch')
        observations = packet['observations']
        if len({o['observation_id'] for o in observations}) != len(observations):
            raise ValueError('duplicate packet observation')
        if packet['chronology_mode'] not in ('captured_observation', 'publication_order_simulation'):
            raise ValueError('unknown packet chronology')
        clock = 'observed_at' if packet['chronology_mode'] == 'captured_observation' else 'published_at_utc'
        if any(not o.get(clock) or o[clock] > packet['checkpoint_at'] for o in observations):
            raise ValueError('future observation in packet')
        raw = checked_file(repo, entry['record'])
        record = load_json(raw)
        if record['inventory_version'] != inventory or record['label_version'] != manifest['profiles'][profile]['label_version']:
            raise ValueError(pid + ': record version mismatch')
        expected_amendments = [a['amendment_id'] for a in amendment['amendments'] if pid in a['affected_prefixes']]
        if entry['active_amendment_ids'] != expected_amendments:
            raise ValueError(pid + ': active amendment selection mismatch')
        if bool(expected_amendments) != bool(entry['active_amendment']):
            raise ValueError('amendment pin missing/unexpected')
        if expected_amendments and entry['active_amendment'] != {'version': amendment['amendment_version'], 'sha256': sha(artifacts['amendment'])}:
            raise ValueError('inactive amendment selected')
        if profile == 'v1':
            if pid in override_ids:
                raise ValueError(pid + ': superseded reference selected')
            if record.get('source_packet_sha256') != sha(packet_raw):
                raise ValueError('embedded packet hash mismatch')
            for labeler, label_input in record['label_inputs'].items():
                checked_file(repo, {'path': 'research/casebook/labels/' + labeler + '/' + pid + '.json', 'sha256': label_input['sha256']})
        else:
            selected = override['effective_prefixes'].get(pid)
            audit = next((row for row in override_rows if row['prefix_id'] == pid), None)
            if not selected or not audit or entry['record'] != {'path': selected['gold_file'], 'sha256': selected['gold_sha256']}:
                raise ValueError('override selection mismatch')
            if any(value != sha(packet_raw) for value in (selected['source_packet_raw_sha256'], audit['packet_sha256'], record.get('source_packet_raw_sha256'))):
                raise ValueError('override packet hash mismatch')
            if audit['gold_sha256'] != sha(raw) or record['saved_at_utc'] != audit['saved_at_utc'] or selected['saved_at_utc'] != audit['saved_at_utc']:
                raise ValueError('override gold audit mismatch')
            inputs = selected['label_input_raw_sha256']
            if inputs != audit['label_input_raw_sha256'] or inputs != record.get('label_input_raw_sha256') or set(inputs) != set(manifest['override_input_dirs']):
                raise ValueError('override embedded input hashes mismatch')
            for labeler, expected_hash in inputs.items():
                source = input_records[(labeler, pid)]
                source_hash = override['preserved_inputs'][labeler][pid + '.json']
                audit_input = input_audits[labeler][pid]
                if expected_hash != source_hash or audit_input['label_sha256'] != source_hash or audit_input['packet_sha256'] != sha(packet_raw):
                    raise ValueError('replacement input audit/hash mismatch')
                if source['inventory_version'] != inventory or source['adjudication_status'] != 'unadjudicated':
                    raise ValueError('replacement input metadata mismatch')
                errors.extend(pid + ': replacement input ' + e for e in check_record(source, packet, set(), False))
            allowed_documents = {'': record}
            for labeler, directory in manifest['override_input_dirs'].items():
                allowed_documents[str(Path(directory).relative_to('research/casebook/labels') / (pid + '.json'))] = input_records[(labeler, pid)]
            for decision in record['decisions']:
                for key in [*manifest['override_decision_keys'].values(), 'gold_refs']:
                    if not isinstance(decision.get(key), list) or not decision[key]:
                        raise ValueError('missing decision references')
                    for reference in decision[key]:
                        path, pointer = reference.split('#', 1)
                        json_pointer(allowed_documents[path], pointer)
        for change in amendment['amendments']:
            if change['amendment_id'] not in expected_amendments:
                continue
            active_ids.add(change['amendment_id'])
            if amendment['original_record_sha256'].get(pid) != sha(raw):
                raise ValueError('amendment base hash mismatch')
            matches = [item for item in record[change['record_collection']] if item['id'] == change['record_id']]
            if len(matches) != 1:
                raise ValueError('amendment target mismatch')
            for span in change['append_source_spans']:
                if span not in matches[0]['source_spans']:
                    matches[0]['source_spans'].append(span)
        errors.extend(pid + ': ' + error for error in check_record(record, packet, set(), True, profile))
        counts[profile] = counts.get(profile, 0) + 1
    return {'prefixes': len(entries), 'profiles': counts, 'active_locator_amendments': len(active_ids), 'errors': errors}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--packet-root', type=Path, required=True)
    parser.add_argument('--repository-root', type=Path, default=Path(__file__).resolve().parents[3],
                        help='Repository containing the frozen tracked references (also supports offline fixtures).')
    parser.add_argument('--original-label-root', type=Path,
                        help='Optional original parent directory containing labels-a/b/c04; verify byte preservation.')
    args = parser.parse_args()
    root = args.repository_root / 'research/casebook/labels'
    paths = (args.packet_root / 'traversal.txt').read_text().splitlines()
    expected = [Path(p).stem for p in paths]
    result = {'gold_prefixes': 0, 'preserved_original_prefixes': {},
              'original_schema_observations': [], 'errors': []}
    for label_dir in ('a', 'b', 'c04', 'adjudicated'):
        directory = root / label_dir
        rows = read_rows(directory / 'audit.jsonl')
        desired = [p for p in expected if p.startswith('C04-')] if label_dir == 'c04' else expected
        if [row['prefix_id'] for row in rows] != desired:
            result['errors'].append(label_dir + ': audit coverage/order mismatch')
        if sorted(p.stem for p in directory.glob('C*-p*.json')) != sorted(desired):
            result['errors'].append(label_dir + ': file coverage mismatch')
        audit_by_id = {row['prefix_id']: row for row in rows}
        refs_by_case = {}
        for relative in paths:
            pid = Path(relative).stem
            if pid not in desired:
                continue
            packet_bytes = safe_path(args.packet_root, relative).read_bytes()
            packet = load_json(packet_bytes)
            raw = (directory / (pid + '.json')).read_bytes()
            record = load_json(raw)
            audit = audit_by_id[pid]
            label_hash_key = 'adjudication_sha256' if label_dir == 'adjudicated' else 'label_sha256'
            packet_hash_key = 'source_packet_sha256' if label_dir == 'adjudicated' else 'packet_sha256'
            if audit[label_hash_key] != sha(raw) or audit[packet_hash_key] != sha(packet_bytes):
                result['errors'].append(label_dir + '/' + pid + ': hash mismatch')
            if label_dir == 'adjudicated':
                if record.get('source_packet_sha256') != sha(packet_bytes):
                    result['errors'].append(pid + ': embedded packet hash mismatch')
                if record.get('label_inputs') != audit.get('label_inputs') or record.get('saved_at_utc') != audit.get('saved_at_utc'):
                    result['errors'].append(pid + ': embedded audit metadata mismatch')
                for labeler, label_input in record.get('label_inputs', {}).items():
                    checked_file(args.repository_root, {'path': 'research/casebook/labels/' + labeler + '/' + pid + '.json', 'sha256': label_input['sha256']})
            refs = refs_by_case.setdefault(record['case_id'], set())
            found = check_record(record, packet, refs, label_dir == 'adjudicated')
            target = 'errors' if label_dir == 'adjudicated' else 'original_schema_observations'
            result[target].extend(label_dir + '/' + pid + ': ' + error for error in found)
            if args.original_label_root and label_dir != 'adjudicated':
                source_dir = args.original_label_root / ('labels-' + label_dir)
                if raw != (source_dir / (pid + '.json')).read_bytes():
                    result['errors'].append(label_dir + '/' + pid + ': original byte mismatch')
        if label_dir == 'adjudicated':
            result['gold_prefixes'] = len(desired)
            times = [row['saved_at_utc'] for row in rows]
            if times != sorted(times) or len(set(times)) != len(times):
                result['errors'].append('adjudication save times not strictly increasing')
        else:
            result['preserved_original_prefixes'][label_dir] = len(desired)
            if args.original_label_root:
                original_audit = args.original_label_root / ('labels-' + label_dir) / 'audit.jsonl'
                if (directory / 'audit.jsonl').read_bytes() != original_audit.read_bytes():
                    result['errors'].append(label_dir + ': original audit bytes differ')
    amendment_path = root / 'adjudicated' / 'span-amendments.json'
    amendment_bytes = amendment_path.read_bytes()
    amendment = load_json(amendment_bytes)
    amendment_audit = read_rows(root / 'adjudicated' / 'amendments.audit.jsonl')
    if not amendment_audit or amendment_audit[-1]['sha256'] != sha(amendment_bytes):
        result['errors'].append('span amendment audit mismatch')
    for index, audit_entry in enumerate(amendment_audit[1:], start=1):
        if audit_entry['previous_version'] != amendment_audit[index - 1]['sha256']:
            result['errors'].append('amendment audit chain mismatch')
        previous = safe_path(root / 'adjudicated', audit_entry['previous_artifact'])
        if sha(previous.read_bytes()) != audit_entry['previous_version']:
            result['errors'].append('rejected amendment history hash mismatch')
    effective = {}
    affected = set()
    for entry in amendment['amendments']:
        for pid in entry['affected_prefixes']:
            affected.add(pid)
            raw = (root / 'adjudicated' / (pid + '.json')).read_bytes()
            if amendment['original_record_sha256'].get(pid) != sha(raw):
                result['errors'].append(pid + ': amendment base hash mismatch')
            record = effective.setdefault(pid, load_json(raw))
            matches = [item for item in record[entry['record_collection']]
                       if item['id'] == entry['record_id']]
            if len(matches) != 1:
                result['errors'].append(pid + ': amendment target mismatch')
                continue
            for span in entry['append_source_spans']:
                if span not in matches[0]['source_spans']:
                    matches[0]['source_spans'].append(span)
    for pid, record in effective.items():
        packet = load_json((args.packet_root / 'prefixes' / record['case_id'] / (pid + '.json')).read_text())
        result['errors'].extend(pid + ': amended ' + error
                                for error in check_record(record, packet, set(), True))
    if affected != set(amendment['original_record_sha256']):
        result['errors'].append('amendment base inventory mismatch')
    result['span_locator_amendments'] = len(amendment['amendments'])
    result['prefixes_with_locator_amendments'] = len(affected)
    effective = validate_effective(args.repository_root, args.packet_root, root / 'effective-reference.json')
    output = {'archived_v1': result, 'effective_reference': effective}
    print(json.dumps(output, indent=2, sort_keys=True))
    return int(bool(result['errors'] or effective['errors']))


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (ValueError, KeyError, TypeError, IndexError, OSError) as error:
        print(json.dumps({'errors': [str(error)]}, sort_keys=True))
        raise SystemExit(1)
