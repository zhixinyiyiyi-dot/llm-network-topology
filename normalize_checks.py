"""Explicit, audited device-name to IPv4 normalization; never overwrites source."""
import argparse
import copy
import hashlib
import importlib.util
import ipaddress
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml


def normalize(data):
    candidate=copy.deepcopy(data)
    by_name={}
    for device in data['devices']:
        if device['name'] in by_name:
            raise ValueError('设备名称重复，不能可靠解析目标。')
        by_name[device['name']]=device
    changes=[]
    for index,check in enumerate(candidate['checks']):
        destination=check['destination']
        try:
            ipaddress.IPv4Address(destination)
            continue
        except (ValueError,TypeError):
            pass
        device=by_name.get(destination)
        if device is None or device['type'] not in ('pc','server'):
            raise ValueError(f'checks/{index}：未知目标或不是PC/服务器，拒绝猜测：{destination!r}')
        addresses=[str(ipaddress.IPv4Interface(i['ipv4']).ip) for i in device['interfaces'] if i['ipv4'] is not None]
        if len(addresses)!=1:
            raise ValueError(f'checks/{index}：目标必须恰有一个明确的IPv4接口。')
        check['destination']=addresses[0]
        changes.append(dict(path=f'checks/{index}/destination',before=destination,after=addresses[0],reason='exact device name with one IPv4 interface'))
    return candidate,changes


def main():
    parser=argparse.ArgumentParser(description='显式转换checks中设备名为其唯一IPv4；另存并审计，保留原始生成失败。')
    parser.add_argument('topology',type=Path,nargs='?')
    parser.add_argument('--self-test',action='store_true')
    args=parser.parse_args()
    if args.self_test:
        fixture=dict(devices=[dict(name='PC1',type='pc',interfaces=[dict(name='FastEthernet0',ipv4='192.168.1.2/24')])],checks=[dict(type='ping',source='PC0',destination='PC1')])
        fixed,changes=normalize(fixture)
        assert fixed['checks'][0]['destination']=='192.168.1.2' and fixture['checks'][0]['destination']=='PC1'
        assert len(changes)==1
        fixed['checks'][0]['destination']='192.168.1.2';assert normalize(fixed)[1]==[]
        for value in ['Unknown','192.168.1.999']:
            bad=copy.deepcopy(fixture);bad['checks'][0]['destination']=value
            try:normalize(bad)
            except ValueError:pass
            else:raise AssertionError('Unknown target guessed')
        bad=copy.deepcopy(fixture);bad['devices'][0]['interfaces'].append(dict(name='other',ipv4='10.0.0.1/24'))
        try:normalize(bad)
        except ValueError:pass
        else:raise AssertionError('Ambiguous IP accepted')
        print('6项离线转换检查通过；不计作模型生成成功。')
        return 0
    if args.topology is None:parser.error('请提供topology.yaml路径。')
    root=Path(__file__).resolve().parent
    spec=importlib.util.spec_from_file_location('topology_validator',root/'uc01_validator/validate.py')
    validator=importlib.util.module_from_spec(spec);spec.loader.exec_module(validator)
    schema=json.loads((root/'uc01_validator/schema.json').read_text(encoding='utf-8'))
    raw=args.topology.read_bytes()
    original=yaml.load(raw.decode('utf-8-sig'),Loader=validator.UniqueLoader)
    before=validator.validate(original,schema)
    if not before:
        print('输入已通过校验，不需要转换。')
        return 0
    if any(e['code'] not in {'CHECK_DESTINATION','UC05_MATRIX'} for e in before):
        raise ValueError('还存在测试目标之外的错误；本工具拒绝自动修改。')
    output=args.topology.with_name(args.topology.stem+'.fixed.yaml')
    if output.exists():raise ValueError('修正副本已存在，拒绝覆盖：'+str(output))
    audit_path=args.topology.with_name('normalization_'+datetime.now().strftime('%Y%m%d_%H%M%S_%f')+'.json')
    audit=dict(timestamp=datetime.now(timezone.utc).isoformat(),method='deterministic_name_to_single_ipv4',
               source=str(args.topology.resolve()),source_sha256=hashlib.sha256(raw).hexdigest(),
               first_model_output_passed=False,original_errors=before,status='RUNNING')
    try:
        fixed,changes=normalize(original)
        audit['changes']=changes
        after=validator.validate(fixed,schema)
        audit['validation_errors_after']=after
        if after:
            audit['status']='REJECTED'
            raise ValueError('转换后仍未通过完整校验，未保存修正副本：'+str(after))
        content=yaml.safe_dump(fixed,allow_unicode=True,sort_keys=False)
        with output.open('x',encoding='utf-8') as stream:stream.write(content)
        audit.update(status='PASS',output=str(output.resolve()),output_sha256=hashlib.sha256(content.encode('utf-8')).hexdigest())
        print(f'已转换 {len(changes)} 个目标，完整静态校验 PASS。')
        print('副本：',output)
        print('原始文件保持不变；本次属于确定性转换，不是模型重新生成或设备自动排障。')
    except Exception as exc:
        audit.update(status='REJECTED',error=f'{type(exc).__name__}: {exc}')
        raise
    finally:
        audit_path.write_text(json.dumps(audit,ensure_ascii=False,indent=2),encoding='utf-8')
        print('转换审计：',audit_path)
    return 0


if __name__=='__main__':
    try:sys.exit(main())
    except (ValueError,OSError,yaml.YAMLError) as exc:
        print('停止：',exc)
        sys.exit(1)
