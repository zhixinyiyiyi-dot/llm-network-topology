"""Read-only COURSE-6-6 HTTP acceptance through PC0's actual PT browser."""
import argparse
import asyncio
import ipaddress
import json
import re
import sys
import traceback
from datetime import datetime, timezone, timedelta
from pathlib import Path

URL = 'http://192.168.0.2/course_index.html'
MARKER = 'COURSE_HTTP_OK'

class CollectionError(ValueError):
    pass

def result_text(result):
    structured = getattr(result, 'structuredContent', None)
    if isinstance(structured, dict) and isinstance(structured.get('result'), str):
        return structured['result']
    texts = []
    for block in getattr(result, 'content', []):
        if getattr(block, 'type', None) != 'text':
            continue
        text = block.text
        try:
            value = json.loads(text)
            if isinstance(value, dict) and isinstance(value.get('result'), str):
                text = value['result']
        except (ValueError, TypeError):
            pass
        texts.append(text)
    return '\n'.join(texts)

def browser_assert(text):
    try:
        value = json.loads(text)
    except (ValueError, TypeError) as exc:
        raise CollectionError('Browser response is not structured JSON; inspect raw evidence') from exc
    if not isinstance(value, dict):
        raise CollectionError('Browser response must be an object')
    if 'ok' in value:
        if not isinstance(value['ok'], bool):
            raise CollectionError('Browser ok field has an unexpected type')
        if value['ok'] is not True:
            return False, 'Browser returned ok=false; failed/cached result rejected'
    if value.get('device') != 'PC0' or value.get('url') != URL:
        raise CollectionError('Response device or URL does not match this request')
    if value.get('error') or value.get('errors'):
        return False, 'Browser response reports an error'
    page = value.get('text')
    size = value.get('html_bytes')
    if not isinstance(page, str) or not isinstance(size, int) or isinstance(size, bool) or size <= 0:
        raise CollectionError('Browser response lacks nonempty page text/HTML byte count')
    notes = value.get('notes', [])
    if not isinstance(notes, list) or not all(isinstance(note, str) for note in notes):
        raise CollectionError('Unexpected browser notes format')
    for note in notes:
        # GUI display failure does not invalidate a response obtained through PT API.
        if note.startswith('GUI:') and 'The work was still done through the API.' in note:
            continue
        # Tool contract permits reopening the same URL and returning the same page.
        if note == 'The page is identical to the last one loaded in this browser.':
            continue
        if re.search(r'fail|error|timeout|timed out|previous page|old page|stale|slow|not load|could not|couldn.t', note, re.I):
            raise CollectionError('Browser load warning: ' + note)
    found = MARKER in page
    return found, ('PC0 and URL match; received nonempty page containing ' + MARKER +
                   '; repeated content is allowed, not a proof of fresh server bytes') if found else 'Received page lacks expected marker'

def endpoints(text):
    return {frozenset(((a, ai), (b, bi))) for a, ai, b, bi in re.findall(
        r'^\s*(\S+):(\S+)\s+<--\[[^\]]+\]-->\s+(\S+):(\S+)\s*$', text, re.M)}

async def run(args):
    import yaml
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client
    data = yaml.safe_load((args.case_dir / 'topology.yaml').read_text(encoding='utf-8-sig'))
    if data.get('case_id') != 'COURSE-6-6':
        raise ValueError('Only COURSE-6-6 is accepted')
    devices = {dev['name']: dev for dev in data['devices']}
    if 'PC0' not in devices or 'Server0' not in devices:
        raise ValueError('Target requires PC0 and Server0')
    if str(ipaddress.ip_interface(devices['Server0']['interfaces'][0]['ipv4']).ip) != '192.168.0.2':
        raise ValueError('Target server IP differs from the fixed acceptance URL')
    # The marker is fixed by this experiment, never injected by this checker.
    out = args.case_dir / ('runtime_http_' + datetime.now().strftime('%Y%m%d_%H%M%S_%f'))
    out.mkdir()
    report = dict(case_id='COURSE-6-6', version='http-browser-v2', status='RUNNING',
                  started=datetime.now(timezone.utc).isoformat(), source='PC0', url=URL,
                  expected_marker=MARKER, checks=[], calls=[], errors=[],
                  device_configuration_writes=0, model_requests=0,
                  scope='Exact physical links and topology IPv4 fields; actual PC0 browser load and received page marker. No server edits, no claim of full page byte equality or deployment history.')
    def save():
        (out / 'runtime_report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    def check(name, passed, detail, evidence):
        report['checks'].append(dict(name=name, passed=bool(passed), detail=detail, evidence=evidence))
        save()
        print(('PASS ' if passed else 'FAIL ') + name + ': ' + detail, flush=True)
    async def call(session, name, params, label):
        # Exact read/navigation-only whitelist. No arbitrary raw JS or server mutations.
        if not ((name == 'pt_query_topology' and params == {}) or
                (name == 'pt_web_browser' and params == dict(device='PC0', url=URL, timeout=30.0, show=True, capture=False))):
            raise ValueError('Read-only whitelist rejected call')
        index = len(report['calls']) + 1
        record = dict(tool=name, arguments=params, label=label)
        report['calls'].append(record)
        save()
        print(f'[{index}] {label}', flush=True)
        result = await session.call_tool(name, params, read_timeout_seconds=timedelta(seconds=100))
        raw_name = f'{index:02}_{label}.json'
        (out / raw_name).write_text(json.dumps(result.model_dump(mode='json'), ensure_ascii=False, indent=2), encoding='utf-8')
        text = result_text(result)
        evidence = f'{index:02}_{label}.txt'
        (out / evidence).write_text(text, encoding='utf-8')
        record['evidence'] = evidence
        save()
        if getattr(result, 'isError', False):
            raise CollectionError('MCP tool error: ' + evidence)
        return text, evidence
    print('Version: HTTP browser v2; actual PC0 request; no configuration writes', flush=True)
    print('Report directory:', out.resolve(), flush=True)
    save()
    try:
        async with streamablehttp_client('http://127.0.0.1:39400/mcp') as streams:
            async with ClientSession(streams[0], streams[1]) as session:
                await session.initialize()
                top, evidence = await call(session, 'pt_query_topology', {}, 'topology')
                expected = {frozenset((link[key]['device'], link[key]['interface']) for key in ['a', 'b']) for link in data['links']}
                check('Physical links', endpoints(top) == expected and bool(expected), 'Expected links must match exactly', evidence)
                missing = []
                for dev in data['devices']:
                    row = re.search(r'^\s*' + re.escape(dev['name']) + r'\s+\[[^\n]+', top, re.M)
                    for interface in dev['interfaces']:
                        if not interface.get('ipv4'):
                            continue
                        addr = ipaddress.ip_interface(interface['ipv4'])
                        token = interface['name'] + '=' + str(addr.ip) + '/' + str(addr.netmask)
                        if not row or token not in row.group(0):
                            missing.append(dev['name'] + ':' + token)
                check('Actual IPv4 and masks', not missing, 'Missing/mismatched: ' + str(missing), evidence)
                if not all(item['passed'] for item in report['checks']):
                    raise CollectionError('Topology differs from COURSE-6-6; browser navigation stopped')
                text, evidence = await call(session, 'pt_web_browser', dict(device='PC0', url=URL, timeout=30.0, show=True, capture=False), 'PC0_http')
                passed, detail = browser_assert(text)
                check('PC0 HTTP page', passed, detail, evidence)
                report['status'] = 'PASS_HTTP_CHECKS' if all(item['passed'] for item in report['checks']) else 'FAIL_HTTP_CHECKS'
    except Exception as exc:
        def leaves(err):
            children = getattr(err, 'exceptions', None)
            return [message for child in children for message in leaves(child)] if children else [type(err).__name__ + ': ' + str(err)]
        report['status'] = 'ERROR_COLLECTION'
        report['errors'] = leaves(exc)
        (out / 'error_details.txt').write_text(traceback.format_exc(), encoding='utf-8')
        for message in report['errors']:
            print('ERROR:', message, flush=True)
    finally:
        report['finished'] = datetime.now(timezone.utc).isoformat()
        save()
    print('Result:', report['status'], '; report:', out / 'runtime_report.json', flush=True)
    return 0 if report['status'] == 'PASS_HTTP_CHECKS' else 1

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--case-dir', type=Path, required=True)
    try:
        sys.exit(asyncio.run(run(parser.parse_args())))
    except Exception as exc:
        print(type(exc).__name__ + ': ' + str(exc), file=sys.stderr)
        sys.exit(1)
