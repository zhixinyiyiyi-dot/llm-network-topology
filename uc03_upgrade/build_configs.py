"""Generate local PT configuration files only. Never connects to devices."""
import argparse
import hashlib
import importlib.util
import ipaddress
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml


ALLOWED = [
    r'no router ospf [0-9]+', r'no router rip', r'router ospf [0-9]+',
    r'network (?:\d{1,3}\.){3}\d{1,3} (?:\d{1,3}\.){3}\d{1,3} area [0-9]+',
    r'enable', r'configure terminal', r'end', r'exit',
    r'hostname [A-Za-z][A-Za-z0-9_-]{0,31}',
    r'interface (?:GigabitEthernet|FastEthernet|Serial)\d+/\d+(?:/\d+)?',
    r'ip address (?:\d{1,3}\.){3}\d{1,3} (?:\d{1,3}\.){3}\d{1,3}',
    r'no shutdown', r'clock rate 2000000', r'router rip',
    r'version 2', r'no auto-summary', r'network (?:\d{1,3}\.){3}\d{1,3}',
]
BLOCKED = re.compile(r'\b(?:reload|erase|format|delete)\b', re.I)


def guard(lines):
    for line in lines:
        if BLOCKED.search(line) or not any(re.fullmatch(p, line) for p in ALLOWED):
            raise ValueError(f'命令被安全检查拒绝：{line!r}')


def main():
    parser = argparse.ArgumentParser(description='从通过校验的 IPv4/RIPv2 YAML 生成 PT 配置；不下发。')
    parser.add_argument('topology', type=Path)
    parser.add_argument('--migrate-from-rip', action='store_true')
    parser.add_argument('--replace-ospf-process',type=int,choices=range(1,65536),metavar='OLD_PROCESS')
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    folder = root / 'uc01_validator'
    spec = importlib.util.spec_from_file_location('topology_validator', folder / 'validate.py')
    validator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(validator)
    raw = args.topology.read_bytes()
    data = yaml.load(raw.decode('utf-8-sig'), Loader=validator.UniqueLoader)
    schema = json.loads((folder / 'schema.json').read_text(encoding='utf-8'))
    errors = validator.validate(data, schema)
    if errors:
        for error in errors:
            print(f"[{error['code']}] {error['path']}: {error['message']}")
        print('拒绝生成：请先修正 YAML。')
        return 1

    if args.migrate_from_rip and any(d['type']=='router' and (len(d['routing'])!=1 or d['routing'][0]['protocol']!='ospf') for d in data['devices']):
        raise ValueError('RIP迁移模式只接受全OSPF目标拓扑。')
    generated = {}
    dce = {(l['dce']['device'], l['dce']['interface'])
           for l in data['links'] if l['dce'] is not None}
    guide = ['Packet Tracer 人工部署指南',
             '生成配置尚未执行；本程序不打开 PT、不连接任何设备。',
             '仅在本地仿真环境使用。先另存一个副本再部署。',
             '下列配置面向新建或已确认没有冲突配置的设备，默认不会清除旧配置；指定 --migrate-from-rip 时会移除 RIP 路由进程。',
             '若在已有同名同接口拓扑上使用，应先审查现有配置。',
             '', '一、设备、接口及接线']
    for link in data['links']:
        a, b = link['a'], link['b']
        line = f"{a['device']} {a['interface']} <-> {b['device']} {b['interface']}"
        if link['dce']:
            line += f"；DCE：{link['dce']['device']} {link['dce']['interface']}"
        guide.append(line)
    guide += ['', '路由器需具备 YAML 中列出的串行接口；按现有 UC-01 拓扑选型与接线。',
              '', '二、PC 的 Desktop > IP Configuration（Static）']
    for device in data['devices']:
        name = device['name']
        if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,31}', name):
            raise ValueError('不支持的设备名称。')
        if device['type'] == 'switch':
            raise ValueError('本配置生成器暂不支持交换机配置。')
        if device['type'] == 'pc':
            for interface in device['interfaces']:
                if interface['ipv4']:
                    addr = ipaddress.IPv4Interface(interface['ipv4'])
                    guide.append(f"{name} {interface['name']}：IP {addr.ip}；掩码 {addr.netmask}；网关 {device['default_gateway']}")
            continue
        lines = ['enable', 'configure terminal', f'hostname {name}']
        if args.migrate_from_rip:
            lines.append('no router rip')
        if args.replace_ospf_process is not None:
            if any(route['protocol']!='ospf' for route in device['routing']):
                raise ValueError('替换OSPF进程只接受OSPF目标配置。')
            lines.append(f'no router ospf {args.replace_ospf_process}')
        for interface in device['interfaces']:
            if interface['ipv4'] is None:
                raise ValueError('本路由器配置生成器要求每个接口明确提供 IPv4。')
            addr = ipaddress.IPv4Interface(interface['ipv4'])
            lines.extend([f"interface {interface['name']}", f'ip address {addr.ip} {addr.netmask}'])
            if (name, interface['name']) in dce:
                lines.append('clock rate 2000000')
            lines.extend(['no shutdown', 'exit'])
        for route in device['routing']:
            if route['protocol'] == 'rip':
                lines.extend(['router rip', 'version 2', 'no auto-summary'])
                lines.extend(f'network {network}' for network in route['networks'])
            else:
                lines.append(f"router ospf {route['process_id']}")
                lines.extend(f"network {e['network']} {e['wildcard']} area {e['area']}" for e in route['networks'])
            lines.append('exit')
        lines.append('end')
        guard(lines)
        generated[f'{name}.cfg'] = '\n'.join(lines) + '\n'
    guide += ['', '三、部署与验证',
              '人工审查所有 .cfg 后，再自行决定是否粘贴到对应 PT 路由器的 CLI。',
              '在设备 > 提示符下粘贴；若处于配置模式，先输入 end。',
              '出现密码提示应停下来检查，不要继续盲目粘贴。',
              '先配置路由器，再设置 PC 地址。等待接口与路由收敛后验证。',
              '在三台路由器的特权模式执行 show ip interface brief、show ip protocols、show ip route。',
              '在对应 PC 的 Command Prompt 执行以下测试：']
    for check in data['checks']:
        guide.append(f"{check['source']}：ping {check['destination']}")
    guide += ['PC0 可对checks中对应目标执行tracert，保存实际路径结果。',
              '以上是人工验证步骤，不是自动验收。',
              '确认结果后，在路由器 # 提示符下执行 copy running-config startup-config，按回车接受文件名。',
              '最后保存 .pkt 文件。', '',
              '范围：IPv4/RIPv2/OSPF 配置模板；不支持 VLAN、NAT、ACL。',
              '内置白名单和危险词检查仅审查本程序生成的命令，不是完整 Cisco CLI 语法/语义分析器。',
              '本程序没有自动部署功能，也未实现自动部署前 CONFIRM 门。']
    generated['PT_GUIDE.txt'] = '\n'.join(guide) + '\n'
    out = args.topology.resolve().parent / ('configs_' + datetime.now().strftime('%Y%m%d_%H%M%S_%f'))
    out.mkdir()
    for name, content in generated.items():
        (out / name).write_text(content, encoding='utf-8')
    audit = dict(timestamp=datetime.now(timezone.utc).isoformat(),
                 source=str(args.topology.resolve()), source_sha256=hashlib.sha256(raw).hexdigest(),
                 validation_passed=True, command_guard_passed=True, deployed=False, migrate_from_rip=args.migrate_from_rip, replace_ospf_process=args.replace_ospf_process,
                 files={name:hashlib.sha256(content.encode('utf-8')).hexdigest() for name,content in generated.items()})
    (out/'generation_audit.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2),encoding='utf-8')
    print('配置生成成功（尚未部署）：', out)
    print('文件：', ', '.join(generated))
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (OSError, ValueError, yaml.YAMLError) as exc:
        print('生成失败：', exc)
        sys.exit(1)
