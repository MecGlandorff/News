#!/usr/bin/env python3
"""Read-only verification of frozen source-only labels against local source packets."""
import argparse
import hashlib
import json
from pathlib import Path


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def read_rows(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def check_record(record, packet, references, strict):
    errors = []
    required = {'case_id', 'prefix_id', 'labeler_id', 'label_version',
                'inventory_version', 'contributions', 'relations',
                'delta_expectations', 'questions', 'no_delta_reason',
                'missing_evidence_reason', 'ambiguity_notes', 'adjudication_status'}
    if not required <= record.keys():
        errors.append('missing required top-level fields')
    if (record['case_id'], record['prefix_id']) != (packet['case_id'], packet['prefix_id']):
        errors.append('packet identity mismatch')
    observations = {o['observation_id']: o for o in packet['observations']}
    current_ids = {c['id'] for c in record['contributions']}
    if len(current_ids) != len(record['contributions']):
        errors.append('duplicate contribution IDs')
    references.update(current_ids)
    references.update(c[k] for c in record['contributions']
                      for k in ('occurrence_ref', 'story_ref') if c.get(k))
    references.update(q['id'] for q in record['questions'])
    def walk(value):
        if isinstance(value, dict):
            if {'observation_id', 'field', 'start', 'end'} <= value.keys():
                try:
                    assert value['field'] in ('text', 'title', 'description')
                    text = observations[value['observation_id']]['fields'][value['field']]
                    assert type(value['start']) is int and type(value['end']) is int
                    assert 0 <= value['start'] < value['end'] <= len(text)
                except (KeyError, AssertionError, TypeError):
                    errors.append('invalid span: ' + json.dumps(value, sort_keys=True))
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)
    walk(record)
    kinds = {'new_occurrence', 'same_occurrence_material_fact', 'source_correction',
             'question_opened', 'question_answered', 'question_closed', 'conflict', 'context_only'}
    for contribution in record['contributions']:
        if contribution['kind'] not in kinds:
            errors.append('invalid contribution kind: ' + contribution['id'])
        if not contribution['source_spans']:
            errors.append('contribution lacks evidence: ' + contribution['id'])
    for relation in record['relations']:
        if relation['from'] not in references or relation['to'] not in references:
            errors.append('unresolved relation reference: ' + json.dumps(relation, sort_keys=True))
        if relation['status'] not in ('required', 'allowed', 'prohibited', 'uncertain'):
            errors.append('invalid relation status')
    for delta in record['delta_expectations']:
        # Independent originals can reference an earlier incremental label.
        permitted = current_ids if strict else references
        if not set(delta['contribution_ids']) <= permitted:
            errors.append('unresolved delta reference')
        if delta['status'] not in ('required', 'allowed', 'prohibited', 'uncertain'):
            errors.append('invalid delta status')
    for question in record['questions']:
        if question['status'] not in ('open', 'answered', 'closed'):
            errors.append('non-protocol question status: ' + question['id'] + '=' + question['status'])
    if strict:
        if record['visible_observation_ids'] != list(observations):
            errors.append('visible observation accounting mismatch')
        if record['adjudication_status'] != 'adjudicated_development_reference':
            errors.append('unfrozen gold status')
        if not record.get('decisions'):
            errors.append('missing adjudication decisions')
        if record['chronology_mode'] != packet['chronology_mode']:
            errors.append('chronology mismatch')
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--packet-root', type=Path, required=True)
    parser.add_argument('--original-label-root', type=Path,
                        help='Optional original parent directory containing labels-a/b/c04; verify byte preservation.')
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
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
            packet_bytes = (args.packet_root / relative).read_bytes()
            packet = json.loads(packet_bytes)
            raw = (directory / (pid + '.json')).read_bytes()
            record = json.loads(raw)
            audit = audit_by_id[pid]
            label_hash_key = 'adjudication_sha256' if label_dir == 'adjudicated' else 'label_sha256'
            packet_hash_key = 'source_packet_sha256' if label_dir == 'adjudicated' else 'packet_sha256'
            if audit[label_hash_key] != sha(raw) or audit[packet_hash_key] != sha(packet_bytes):
                result['errors'].append(label_dir + '/' + pid + ': hash mismatch')
            if label_dir == 'adjudicated' and record['source_packet_sha256'] != sha(packet_bytes):
                result['errors'].append(pid + ': embedded packet hash mismatch')
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
    amendment = json.loads(amendment_bytes)
    amendment_audit = read_rows(root / 'adjudicated' / 'amendments.audit.jsonl')
    if not amendment_audit or amendment_audit[-1]['sha256'] != sha(amendment_bytes):
        result['errors'].append('span amendment audit mismatch')
    for index, audit_entry in enumerate(amendment_audit[1:], start=1):
        if audit_entry['previous_version'] != amendment_audit[index - 1]['sha256']:
            result['errors'].append('amendment audit chain mismatch')
        previous = root / 'adjudicated' / audit_entry['previous_artifact']
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
            record = effective.setdefault(pid, json.loads(raw))
            matches = [item for item in record[entry['record_collection']]
                       if item['id'] == entry['record_id']]
            if len(matches) != 1:
                result['errors'].append(pid + ': amendment target mismatch')
                continue
            for span in entry['append_source_spans']:
                if span not in matches[0]['source_spans']:
                    matches[0]['source_spans'].append(span)
    for pid, record in effective.items():
        packet = json.loads((args.packet_root / 'prefixes' / record['case_id'] / (pid + '.json')).read_text())
        result['errors'].extend(pid + ': amended ' + error
                                for error in check_record(record, packet, set(), True))
    if affected != set(amendment['original_record_sha256']):
        result['errors'].append('amendment base inventory mismatch')
    result['span_locator_amendments'] = len(amendment['amendments'])
    result['prefixes_with_locator_amendments'] = len(affected)
    print(json.dumps(result, indent=2, sort_keys=True))
    return int(bool(result['errors']))


if __name__ == '__main__':
    raise SystemExit(main())
