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
    r'clear ip nat translation \*', r'no ip address', r'no ip nat inside',
    r'no ip nat inside source list 1 pool UC04 overload', r'no ip nat pool UC04', r'no access-list 1',
    r'ip access-list extended [A-Za-z][A-Za-z0-9_]{0,31}', r'ip access-group [A-Za-z][A-Za-z0-9_]{0,31} (?:in|out)',
    r'(?:permit|deny) (?:ip|icmp|tcp) (?:any|(?:\d{1,3}\.){3}\d{1,3} (?:\d{1,3}\.){3}\d{1,3}) (?:any|(?:\d{1,3}\.){3}\d{1,3} (?:\d{1,3}\.){3}\d{1,3})(?: echo-reply| established)?',
    r'passive-interface (?:GigabitEthernet|FastEthernet|Serial)\d+/\d+(?:/\d+)?',
    r'router bgp [0-9]+', r'bgp router-id (?:\d{1,3}\.){3}\d{1,3}',
    r'neighbor (?:\d{1,3}\.){3}\d{1,3} remote-as [0-9]+',
    r'network (?:\d{1,3}\.){3}\d{1,3} mask (?:\d{1,3}\.){3}\d{1,3}',
    r'interface Loopback[0-9]+',
    r'ip routing', r'vlan [0-9]+', r'name [A-Za-z][A-Za-z0-9_]{0,31}',
    r'interface Vlan[0-9]+', r'encapsulation dot1Q [0-9]+',
    r'switchport mode trunk', r'switchport access vlan [0-9]+', r'switchport trunk allowed vlan [0-9,]+',
    r'switchport mode access', r'ip nat inside', r'ip nat outside',
    r'ip route (?:\d{1,3}\.){3}\d{1,3} (?:\d{1,3}\.){3}\d{1,3} (?:\d{1,3}\.){3}\d{1,3}(?: [0-9]+)?',
    r'access-list [0-9]+ permit (?:\d{1,3}\.){3}\d{1,3} (?:\d{1,3}\.){3}\d{1,3}',
    r'ip nat pool [A-Za-z][A-Za-z0-9_]{0,20} (?:\d{1,3}\.){3}\d{1,3} (?:\d{1,3}\.){3}\d{1,3} netmask (?:\d{1,3}\.){3}\d{1,3}',
    r'ip nat inside source list [0-9]+ pool [A-Za-z][A-Za-z0-9_]{0,20} overload',
    r'enable', r'configure terminal', r'end', r'exit',
    r'hostname [A-Za-z][A-Za-z0-9_-]{0,31}',
    r'interface (?:GigabitEthernet|FastEthernet|Serial)\d+/\d+(?:/\d+)?(?:\.\d+)?',
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
    parser.add_argument('--omit-nat',action='store_true',help='生成未启用NAT的基线配置，同时另存NAPT启用文件。')
    parser.add_argument('--from-uc04',action='store_true',help='仅UC07：在UC04副本中清理旧单网段NAPT配置。')
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
    if args.from_uc04 and data['case_id']!='UC-07':raise ValueError('--from-uc04只允许UC-07迁移。')
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
        if device['type'] in ('switch','multilayer_switch'):
            lines=['enable','configure terminal',f'hostname {name}']
            for vlan in data['vlans']:
                lines.extend([f"vlan {vlan['id']}",f"name {vlan['name']}",'exit'])
            if device.get('ip_routing'):lines.append('ip routing')
            for i in device['interfaces']:
                lines.append(f"interface {i['name']}")
                if i['name'].startswith('Vlan'):
                    addr=ipaddress.IPv4Interface(i['ipv4'])
                    lines.append(f'ip address {addr.ip} {addr.netmask}')
                elif i.get('switchport_mode')=='trunk':
                    lines.extend(['switchport mode trunk','switchport trunk allowed vlan '+','.join(map(str,i['allowed_vlans']))])
                else:
                    lines.append('switchport mode access')
                    if 'access_vlan' in i:lines.append(f"switchport access vlan {i['access_vlan']}")
                lines.extend(['no shutdown','exit'])
            lines.append('end');guard(lines)
            generated[f'{name}.cfg']='\n'.join(lines)+'\n'
            continue
        if device['type'] in ('pc','server'):
            for interface in device['interfaces']:
                if interface['ipv4']:
                    addr = ipaddress.IPv4Interface(interface['ipv4'])
                    guide.append(f"{name} {interface['name']}：IP {addr.ip}；掩码 {addr.netmask}；网关 {device['default_gateway'] if device['default_gateway'] is not None else '留空（不设置网关）'}")
            continue
        lines = ['enable']
        if args.from_uc04 and name=='R0':lines.append('clear ip nat translation *')
        lines.extend(['configure terminal',f'hostname {name}'])
        if args.from_uc04 and name=='R0':
            lines.extend(['no ip nat inside source list 1 pool UC04 overload','no ip nat pool UC04','no access-list 1',
                          'interface GigabitEthernet0/0','no ip nat inside','no ip address','exit'])
        if args.migrate_from_rip:
            lines.append('no router rip')
        if args.replace_ospf_process is not None:
            if any(route['protocol']!='ospf' for route in device['routing']):
                raise ValueError('替换OSPF进程只接受OSPF目标配置。')
            lines.append(f'no router ospf {args.replace_ospf_process}')
        for interface in device['interfaces']:
            lines.append(f"interface {interface['name']}")
            if 'encapsulation_vlan' in interface:
                lines.append(f"encapsulation dot1Q {interface['encapsulation_vlan']}")
            if interface['ipv4'] is not None:
                addr = ipaddress.IPv4Interface(interface['ipv4'])
                lines.append(f'ip address {addr.ip} {addr.netmask}')
            elif not any(i.get('encapsulation_vlan') and i['name'].split('.')[0]==interface['name'] for i in device['interfaces']):
                raise ValueError('没有IPv4的路由器接口必须是已定义子接口的父接口。')
            if (name, interface['name']) in dce:
                lines.append('clock rate 2000000')
            lines.extend(['no shutdown', 'exit'])
        for route in device['routing']:
            if route['protocol'] == 'rip':
                lines.extend(['router rip', 'version 2', 'no auto-summary'])
                lines.extend(f'network {network}' for network in route['networks'])
            elif route['protocol']=='static':
                for entry in route['routes']:
                    net=ipaddress.IPv4Network(entry['prefix'])
                    command=f"ip route {net.network_address} {net.netmask} {entry['next_hop']}"
                    if 'distance' in entry:command+=' '+str(entry['distance'])
                    lines.append(command)
                continue
            elif route['protocol']=='bgp':
                lines.extend([f"router bgp {route['local_as']}",f"bgp router-id {route['router_id']}",'no auto-summary'])
                for prefix in route['networks']:
                    net=ipaddress.IPv4Network(prefix)
                    lines.append(f'network {net.network_address} mask {net.netmask}')
                lines.extend(f"neighbor {n['address']} remote-as {n['remote_as']}" for n in route['neighbors'])
            else:
                lines.append(f"router ospf {route['process_id']}")
                lines.extend(f"network {e['network']} {e['wildcard']} area {e['area']}" for e in route['networks'])
                lines.extend('passive-interface '+iface for iface in route.get('passive_interfaces',[]))
            lines.append('exit')
        nat=device.get('nat')
        if nat:
            nat_lines=[]
            for iface in nat.get('inside_interfaces',[nat.get('inside_interface')]):
                nat_lines.extend([f'interface {iface}','ip nat inside','exit'])
            nat_lines.extend([f"interface {nat['outside_interface']}",'ip nat outside','exit'])
            for prefix in nat.get('source_networks',[nat.get('source_network')]):
                source=ipaddress.IPv4Network(prefix)
                nat_lines.append(f"access-list {nat['acl_id']} permit {source.network_address} {source.hostmask}")
            nat_lines.extend([f"ip nat pool {nat['pool_name']} {nat['pool_start']} {nat['pool_end']} netmask {nat['netmask']}",
                              f"ip nat inside source list {nat['acl_id']} pool {nat['pool_name']} overload"])
            separate=['enable','configure terminal']+nat_lines+['end'];guard(separate)
            generated[f'{name}_NAPT.cfg']='\n'.join(separate)+'\n'
            if not args.omit_nat:lines.extend(nat_lines)
        def acl_address(value):
            if value=='any':return 'any'
            net=ipaddress.IPv4Network(value)
            return f'{net.network_address} {net.hostmask}'
        for acl in device.get('acls',[]):
            lines.append(f"ip access-list extended {acl['name']}")
            for rule in acl['rules']:
                command=f"{rule['action']} {rule['protocol']} {acl_address(rule['source'])} {acl_address(rule['destination'])}"
                if rule.get('icmp_type'):command+=' '+rule['icmp_type']
                if rule.get('established'):command+=' established'
                lines.append(command)
            lines.extend(['exit',f"interface {acl['interface']}",f"ip access-group {acl['name']} {acl['direction']}",'exit'])
        lines.append('end')
        guard(lines)
        generated[f'{name}.cfg'] = '\n'.join(lines) + '\n'
    guide += ['', '三、部署与验证',
              '人工审查所有 .cfg 后，再自行决定是否粘贴到对应 PT 路由器的 CLI。',
              '在设备 > 提示符下粘贴；若处于配置模式，先输入 end。',
              '出现密码提示应停下来检查，不要继续盲目粘贴。',
              '先配置路由器，再设置 PC 地址。等待接口与路由收敛后验证。',
              '在相应路由器的特权模式执行 show ip interface brief、show ip protocols、show ip route。',
              '在对应 PC 的 Command Prompt 执行以下测试：']
    for check in data['checks']:
        guide.append(f"{check['source']}：ping {check['destination']}")
    guide += ['PC0 可对checks中对应目标执行tracert，保存实际路径结果。',
              '以上是人工验证步骤，不是自动验收。',
              '确认结果后，在路由器 # 提示符下执行 copy running-config startup-config，按回车接受文件名。',
              '最后保存 .pkt 文件。', '',
              '范围：IPv4/RIPv2/OSPF/eBGP 配置模板；支持单地址NAPT、静态路由；支持VLAN access/trunk、单臂子接口与SVI；支持扩展IPv4 ACL及UC07指定策略；并非状态防火墙。',
              '内置白名单和危险词检查仅审查本程序生成的命令，不是完整 Cisco CLI 语法/语义分析器。',
              '本程序没有自动部署功能，也未实现自动部署前 CONFIRM 门。']
    if data.get('case_id')=='UC-09':
        guide += ['', 'UC-09：只有Router0和Router1；R0.cfg贴到Router0，R1.cfg贴到Router1。', 'Loopback0为软件接口，配置自动创建，不接网线、不需要PC。', '在路由器CLI执行ping，不是在PC命令行。show ip bgp summary核对邻居。', '10.0.0.0/24是两端共享直连网络；保留AS100原宣告，另加10.1.0.0/24验证远端BGP安装。']
    generated['PT_GUIDE.txt'] = '\n'.join(guide) + '\n'
    out = args.topology.resolve().parent / ('configs_' + datetime.now().strftime('%Y%m%d_%H%M%S_%f'))
    out.mkdir()
    for name, content in generated.items():
        (out / name).write_text(content, encoding='utf-8')
    audit = dict(timestamp=datetime.now(timezone.utc).isoformat(),
                 source=str(args.topology.resolve()), source_sha256=hashlib.sha256(raw).hexdigest(),
                 validation_passed=True, command_guard_passed=True, deployed=False, migrate_from_rip=args.migrate_from_rip, replace_ospf_process=args.replace_ospf_process, omit_nat=args.omit_nat, from_uc04=args.from_uc04,
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
