"""Offline IPv4/RIP DSL validator. Never deploys commands or calls an API."""
import argparse
import hashlib
import ipaddress as ip
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator


class UniqueLoader(yaml.SafeLoader):
    pass


def mapping(loader, node):
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node)
        if key in result:
            raise ValueError(f"YAML 重复字段：{key}")
        result[key] = loader.construct_object(value_node)
    return result


UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, mapping)


def classful(address):
    first = int(str(address).split('.')[0])
    prefix = 8 if first < 128 else 16 if first < 192 else 24
    return str(ip.IPv4Network(f"{address}/{prefix}", strict=False).network_address)


def validate(data, schema):
    errors = []
    def fail(code, path, message):
        errors.append(dict(code=code, path=path, message=message))

    for error in Draft202012Validator(schema).iter_errors(data):
        fail('SCHEMA', '/'.join(map(str, error.absolute_path)) or '/', error.message)
    if errors:
        return errors
    if data['status'] != 'ready' or data['questions']:
        fail('NOT_READY', 'status', '需求尚未澄清，不允许进入配置生成。')

    devices, interfaces, addresses, networks = {}, {}, {}, {}
    for d in data['devices']:
        name = d['name']
        if name in devices:
            fail('DUP_DEVICE', name, '设备名称重复。')
        devices[name] = d
        for i in d['interfaces']:
            endpoint = (name, i['name'])
            path = '/'.join(endpoint)
            if endpoint in interfaces:
                fail('DUP_INTERFACE', path, '同一设备接口名称重复。')
            interfaces[endpoint] = None
            if i['ipv4'] is None:
                continue
            try:
                if '/' not in i['ipv4']:
                    raise ValueError('必须显式提供前缀长度')
                addr = ip.IPv4Interface(i['ipv4'])
                if addr.ip.is_multicast or addr.ip.is_loopback or addr.ip.is_unspecified or addr.ip.is_reserved or int(addr.ip) >> 24 == 0:
                    raise ValueError('不是本 DSL 支持的单播接口地址')
                if addr.network.prefixlen < 31 and addr.ip in (addr.network.network_address, addr.network.broadcast_address):
                    raise ValueError('接口不能使用网络地址或广播地址')
                interfaces[endpoint] = addr
                if addr.ip in addresses:
                    fail('DUP_IP', path, f"IP 地址重复，另一接口为 {addresses[addr.ip]}。")
                addresses[addr.ip] = path
                networks[addr.network] = path
            except ValueError as exc:
                fail('IP_INVALID', path, str(exc))
    nets = list(networks)
    for index, a in enumerate(nets):
        for b in nets[index + 1:]:
            if a.overlaps(b):
                fail('SUBNET_OVERLAP', networks[b], f'不同子网存在重叠：{a} 和 {b}。')

    graph = {ep: set() for ep in interfaces}
    used = set()
    for index, link in enumerate(data['links']):
        path = f'links/{index}'
        ends = [(link[k]['device'], link[k]['interface']) for k in ('a', 'b')]
        valid = True
        for ep in ends:
            if ep not in interfaces:
                fail('LINK_REFERENCE', path, f'引用了不存在的接口 {ep}。')
                valid = False
            if ep in used:
                fail('PORT_REUSED', path, f'物理端口被重复连接：{ep}。')
            used.add(ep)
        a, b = ends
        if a[0] == b[0]:
            fail('SELF_LINK', path, '不允许设备连接自身。')
        serial = [ep[1].lower().startswith('serial') for ep in ends]
        if any(serial):
            if not all(serial):
                fail('LINK_MEDIA', path, '串行接口必须连接串行接口。')
            if link['dce'] is None:
                fail('DCE_MISSING', path, '串行链路必须指定 DCE 端。')
            elif (link['dce']['device'], link['dce']['interface']) not in ends:
                fail('DCE_REFERENCE', path, 'DCE 端必须属于本链路。')
        elif link['dce'] is not None:
            fail('DCE_MEDIA', path, '非串行链路不能设置 DCE。')
        if not valid:
            continue
        graph[a].add(b)
        graph[b].add(a)
        aa, bb = interfaces[a], interfaces[b]
        if aa is not None and bb is not None and aa.network != bb.network:
            fail('LINK_SUBNET', path, f'链路两端子网不一致：{aa} / {bb}。')

    # Equal subnets are valid on one LAN; disconnected duplicate LANs are not.
    for ep, addr in interfaces.items():
        if addr is not None and ep not in used:
            fail('UNLINKED_IP', '/'.join(ep), '已编址接口未连接链路。')
    by_net = {}
    for ep, addr in interfaces.items():
        if addr is not None:
            by_net.setdefault(addr.network, []).append(ep)
    def lan_reachable(start):
        seen, pending = set(), [start]
        while pending:
            ep = pending.pop()
            if ep in seen:
                continue
            seen.add(ep)
            pending.extend(graph[ep] - seen)
            if devices[ep[0]]['type'] == 'switch':
                pending.extend(x for x in interfaces if x[0] == ep[0] and x not in seen)
        return seen
    for net, eps in by_net.items():
        reachable = lan_reachable(eps[0])
        if any(ep not in reachable for ep in eps):
            fail('DISCONNECTED_SUBNET', str(net), '相同子网被用于不连通的二层网段。')

    for name, d in devices.items():
        own = [(ep, addr) for ep, addr in interfaces.items() if ep[0] == name and addr is not None]
        gateway = d['default_gateway']
        if d['type'] == 'pc':
            if gateway is None:
                fail('GATEWAY_MISSING', name, '当前 DSL 中 PC 必须配置网关。')
            else:
                try:
                    gw = ip.IPv4Address(gateway)
                    local = [(ep, addr) for ep, addr in own if gw in addr.network and gw != addr.ip]
                    targets = [ep for ep, addr in interfaces.items() if addr is not None and addr.ip == gw and devices[ep[0]]['type'] == 'router']
                    if not local or not any(t in lan_reachable(ep) for ep, _ in local for t in targets):
                        fail('GATEWAY_INVALID', name, '网关必须是同一二层网段内路由器接口的实际 IP。')
                except ValueError:
                    fail('GATEWAY_INVALID', name, '网关不是合法 IPv4 地址。')
        elif gateway is not None:
            fail('GATEWAY_ROLE', name, '当前版本只有 PC 支持 default_gateway 字段。')
        if d['type'] != 'router' and d['routing']:
            fail('ROUTING_ROLE', name, '非路由器不能配置路由协议。')
        if d['type'] == 'router' and not d['routing']:
            fail('RIP_MISSING', name, '路由器缺少路由声明。')
        expected = {classful(addr.ip) for _, addr in own}
        for route in d['routing']:
            if route['protocol'] == 'ospf':
                ranges = []
                for entry in route['networks']:
                    try:
                        address = ip.IPv4Address(entry['network'])
                        wildcard = int(ip.IPv4Address(entry['wildcard']))
                        if wildcard & (wildcard + 1):
                            raise ValueError('反掩码必须是连续低位1')
                        prefix = 32 - wildcard.bit_count()
                        net = ip.IPv4Network(f'{address}/{prefix}', strict=True)
                        ranges.append((net, entry['area']))
                        if not any(addr.ip in net for _, addr in own):
                            fail('OSPF_NETWORK_UNUSED', name, f'OSPF声明 {net} 没有匹配本机接口。')
                    except ValueError as exc:
                        fail('OSPF_NETWORK_INVALID', name, str(exc))
                for ep, addr in own:
                    matches = [area for net,area in ranges if addr.ip in net]
                    if len(matches) != 1:
                        fail('OSPF_INTERFACE_COVERAGE', '/'.join(ep), '每个已编址接口必须且只能匹配一条OSPF网络声明。')
                if data['case_id'] == 'UC-02' and (route['process_id'] != 100 or any(e['area'] != 0 for e in route['networks'])):
                    fail('UC02_OSPF_SETTINGS', name, 'UC-02必须使用OSPF进程100、全部area 0。')
                continue
            if data['case_id'] == 'UC-02':
                fail('UC02_PROTOCOL', name, 'UC-02应迁移到OSPF，不能保留RIP。')
            declared = set()
            for n in route['networks']:
                try:
                    addr = ip.IPv4Address(n)
                    canonical = classful(addr)
                    if addr.is_multicast or int(addr) >> 24 >= 224:
                        raise ValueError('不是有效的 RIP 主网络')
                    if n != canonical:
                        fail('RIP_NETWORK_CANONICAL', name, f'RIP network {n} 应规范化为 {canonical}。')
                    declared.add(canonical)
                except ValueError:
                    fail('RIP_NETWORK_INVALID', name, f'非法 RIP 主网络：{n}。')
            for n in sorted(expected - declared):
                fail('RIP_NETWORK_MISSING', name, f'缺少直连接口对应的 RIP network {n}。')
            for n in sorted(declared - expected):
                fail('RIP_NETWORK_UNUSED', name, f'RIP network {n} 没有对应的直连接口。')
    if data['case_id']=='UC-03':
        expected_ips = {
            'R0': {'GigabitEthernet0/0':'192.168.0.254/24','Serial0/0/0':'10.0.0.1/30','Serial0/0/1':'172.19.0.1/30'},
            'R1': {'Serial0/0/0':'10.0.0.2/30','Serial0/0/1':'172.16.0.1/30'},
            'R2': {'GigabitEthernet0/0':'192.168.1.254/24','Serial0/0/0':'172.16.0.2/30','Serial0/0/1':'172.19.0.2/30'},
            'PC0': {'FastEthernet0':'192.168.0.10/24'},
            'PC1': {'FastEthernet0':'192.168.1.10/24'},
        }
        expected_areas = {'192.168.0.0':0,'10.0.0.0':0,'172.16.0.0':100,'172.19.0.0':100,'192.168.1.0':100}
        if set(devices)!=set(expected_ips):
            fail('UC03_DEVICES','devices','UC-03设备必须为R0/R1/R2/PC0/PC1。')
        for name, d in devices.items():
            actual_ips={i['name']:i['ipv4'] for i in d['interfaces']}
            if actual_ips!=expected_ips.get(name):
                fail('UC03_ADDRESS',name,'UC-03地址或接口与需求不符。')
            if d['type']=='router':
                for route in d['routing']:
                    if route['protocol']!='ospf' or route.get('process_id')!=1:
                        fail('UC03_PROTOCOL',name,'UC-03必须为OSPF进程1。')
                        continue
                    for entry in route['networks']:
                        if expected_areas.get(entry['network'])!=entry['area']:
                            fail('UC03_AREA',name,'总部及10.0.0.0链路为area0，分部及172.16/172.19链路为area100。')
            if d['type']=='pc' and d['default_gateway']!={'PC0':'192.168.0.254','PC1':'192.168.1.254'}.get(name):
                fail('UC03_GATEWAY',name,'UC-03默认网关不符合需求。')
        actual_checks={(c['source'],c['destination']) for c in data['checks']}
        if actual_checks!={('PC0','192.168.1.10'),('PC1','192.168.0.10')}:
            fail('UC03_CHECK_TARGET','checks','必须为新地址的双向ping目标。')
    # OSPF neighbors on one link must agree on area (process IDs need not match).
    for index, link in enumerate(data['links']):
        areas = []
        for side in ('a','b'):
            ep = (link[side]['device'], link[side]['interface'])
            addr = interfaces.get(ep)
            if addr is None or ep[0] not in devices:
                continue
            for route in devices[ep[0]]['routing']:
                if route['protocol'] != 'ospf':
                    continue
                for entry in route['networks']:
                    try:
                        wc = int(ip.IPv4Address(entry['wildcard']))
                        if wc & (wc + 1):
                            continue
                        net = ip.IPv4Network(f"{entry['network']}/{32-wc.bit_count()}", strict=True)
                        if addr.ip in net:
                            areas.append(entry['area'])
                    except ValueError:
                        pass
        if len(areas) == 2 and areas[0] != areas[1]:
            fail('OSPF_LINK_AREA', f'links/{index}', 'OSPF链路两端area不一致。')
    for index, check in enumerate(data['checks']):
        if check['source'] not in devices:
            fail('CHECK_SOURCE', f'checks/{index}', '测试源设备不存在。')
        try:
            destination = ip.IPv4Address(check['destination'])
            if destination not in addresses:
                fail('CHECK_DESTINATION', f'checks/{index}', '本地测试目标不是拓扑中已编址的接口。')
        except ValueError:
            fail('CHECK_DESTINATION', f'checks/{index}', '测试目标不是合法 IPv4。')
    return errors


def main():
    parser = argparse.ArgumentParser(description='本地 IPv4/RIPv2 YAML 校验，不调用模型，不连接网络设备。')
    parser.add_argument('topology', type=Path)
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    raw = args.topology.read_bytes()
    schema = json.loads(Path(__file__).with_name('schema.json').read_text(encoding='utf-8'))
    try:
        data = yaml.load(raw.decode('utf-8-sig'), Loader=UniqueLoader)
        errors = validate(data, schema)
    except (ValueError, yaml.YAMLError) as exc:
        errors = [dict(code='YAML_PARSE', path='/', message=str(exc))]
    report = dict(timestamp=datetime.now(timezone.utc).isoformat(),
                  input=str(args.topology.resolve()), sha256=hashlib.sha256(raw).hexdigest(),
                  scope='IPv4/RIPv2/OSPF; no VLAN/CLI/runtime validation',
                  passed=not errors, errors=errors)
    output = args.report or args.topology.with_name('validation_report.json')
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.resolve() == args.topology.resolve() or output.resolve() == Path(__file__).with_name('schema.json').resolve():
        raise ValueError('报告不能覆盖输入文件或 schema.json。')
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print('PASS：静态校验通过。' if not errors else f'FAIL：发现 {len(errors)} 个问题。')
    for error in errors:
        print(f"[{error['code']}] {error['path']}: {error['message']}")
    print('报告：', output.resolve())
    return 0 if not errors else 1


if __name__ == '__main__':
    sys.exit(main())
