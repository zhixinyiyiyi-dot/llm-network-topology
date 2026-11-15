"""UC-02 live, read-only acceptance through the locally installed PT MCP server."""
import argparse
import asyncio
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path


def result_text(result):
    structured = getattr(result, 'structuredContent', None)
    if isinstance(structured, dict) and isinstance(structured.get('result'), str):
        return structured['result']
    parts = []
    for block in result.content:
        if getattr(block, 'type', None) != 'text':
            continue
        text = block.text
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict) and isinstance(parsed.get('result'), str):
                text = parsed['result']
        except (ValueError, TypeError):
            pass
        parts.append(text)
    return '\n'.join(parts)


def command_failed(text):
    return bool(re.search(r'%\s*(?:Invalid input|Incomplete command|Ambiguous command)|'
                          r'(?im:^\s*(?:\[?(?:ERROR|TIMEOUT|UNKNOWN COMMAND|WAITING FOR ANSWER)\]?)(?:\s|:|$))', text))


def ping_assert(text, destination):
    if command_failed(text):
        return False, '命令报错或超时。'
    if not re.search(r'Pinging\s+' + re.escape(destination) + r'\b', text, re.I):
        return False, '未识别到本次目标的原始 Pinging 标题，不能确认结果。'
    summaries = re.findall(r'Packets\s*:\s*Sent\s*=\s*(\d+)\s*,\s*Received\s*=\s*(\d+)\s*,\s*Lost\s*=\s*(\d+)', text, re.I)
    if len(summaries) != 1:
        return False, '应只有一组可识别的英文 PC ping 统计；多组或无法解析时拒绝判定通过。'
    sent, received, lost = map(int, summaries[0])
    passed = sent == 4 and received == 4 and lost == 0
    return passed, f'发送 {sent}，收到 {received}，丢失 {lost}；验收要求 4/4、0 丢包。'


def trace_assert(text, expected):
    if command_failed(text) or not re.search(r'Trace complete\.', text, re.I):
        return False, '路径测试未正常完成。'
    hops = []
    for line in text.splitlines():
        if re.match(r'^\s*\d+\s+', line):
            addresses = re.findall(r'\b(?:\d{1,3}\.){3}\d{1,3}\b', line)
            if not addresses or '*' in line:
                return False, '路径中存在未知或超时跳。'
            hops.append(addresses[-1])
    return hops == expected, f'实际路径 {hops}；预期 {expected}。'


def route_assert(text, prefix, next_hop, interface):
    if command_failed(text):
        return False, '读取路由表的命令报错或超时。'
    pattern = (r'^\s*O\s+' + re.escape(prefix) +
               r'\s+\[110/[0-9]+\]\s+via\s+' + re.escape(next_hop) +
               r',[^\n]*\b' + re.escape(interface) + r'\s*$')
    found = re.search(pattern, text, re.M) is not None
    return found, f'要求 OSPF {prefix} [110/cost] via {next_hop}，接口 {interface}。'


def self_test():
    sample = ('Pinging 192.168.16.130 with 32 bytes of data:\n'
              'Packets: Sent = 4, Received = 4, Lost = 0 (0% loss),')
    assert ping_assert(sample, '192.168.16.130')[0]
    assert not ping_assert(sample.replace('Received = 4', 'Received = 3'), '192.168.16.130')[0]
    assert not ping_assert(sample, '192.168.16.10')[0]
    assert not ping_assert(sample + '\n' + sample, '192.168.16.130')[0]
    assert not ping_assert('PASS: connectivity OK', '192.168.16.130')[0]
    route = 'O    192.168.16.128/26 [110/65] via 30.0.0.2, 00:00:25, Serial0/0/1'
    assert route_assert(route, '192.168.16.128/26', '30.0.0.2', 'Serial0/0/1')[0]
    assert not route_assert(route.replace('O ', 'C ', 1), '192.168.16.128/26', '30.0.0.2', 'Serial0/0/1')[0]
    assert not route_assert(route, '192.168.16.128/26', '20.0.0.2', 'Serial0/0/1')[0]
    trace = '1 0 ms 0 ms 0 ms 192.168.16.126\n2 1 ms 1 ms 1 ms 30.0.0.2\n3 1 ms 1 ms 1 ms 192.168.16.130\nTrace complete.'
    expected = ['192.168.16.126', '30.0.0.2', '192.168.16.130']
    assert trace_assert(trace, expected)[0]
    assert not trace_assert(trace.replace('30.0.0.2', '10.0.0.2'), expected)[0]
    assert not trace_assert(trace.replace('Trace complete.', ''), expected)[0]
    print('11 项离线解析检查通过；这不是 PT 实际验收结果。')


async def run(args):
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client
    from jsonschema import validate

    out = args.run_dir / ('acceptance_' + datetime.now().strftime('%Y%m%d_%H%M%S_%f'))
    out.mkdir(parents=True)
    report = dict(case_id='UC-02', started=datetime.now(timezone.utc).isoformat(),
                  endpoint='http://127.0.0.1:39400/mcp', mode='live_read_only',
                  mapping=dict(R0=args.r0, R1=args.r1, R2=args.r2, PC0=args.pc0, PC1=args.pc1),
                  status='RUNNING', checks=[], calls=[], errors=[],
                  policy='双向 ping 预热后测量，必须4/4；双向精确路径；四条关键 OSPF 路由、进程100、无RIP及邻居FULL。无自动修复。')

    def save():
        (out/'acceptance_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')

    def check(name, result, evidence):
        passed, detail = result
        report['checks'].append(dict(name=name,passed=passed,detail=detail,evidence=evidence))
        print(('PASS ' if passed else 'FAIL ') + name + '：' + detail, flush=True)
        save()

    async def invoke(session, catalog, name, arguments, label):
        # Only these exact calls can be sent. No config, reload, shell, or arbitrary CLI.
        if name == 'pt_query_topology':
            allowed = arguments == {}
        elif name == 'pt_host_command':
            allowed = (arguments.get('device') in {args.pc0,args.pc1} and
                       arguments.get('command') in {'ping 192.168.16.130','ping 192.168.16.10',
                                                    'tracert 192.168.16.130','tracert 192.168.16.10'} and
                       set(arguments) == {'device','command','timeout','show','capture'})
        elif name == 'pt_cli':
            allowed = (arguments.get('device') in {args.r0,args.r1,args.r2} and
                       arguments.get('commands') == ['enable','show ip route','show ip protocols','show running-config','show ip ospf neighbor'] and
                       set(arguments) == {'device','commands','timeout','auto_confirm','show','capture'})
        else:
            allowed = False
        if not allowed:
            raise ValueError('本地只读白名单拒绝该调用。')
        validate(arguments, catalog[name].inputSchema)
        index = len(report['calls']) + 1
        print(f'[{index}] {label} ...', flush=True)
        record = dict(index=index, tool=name, arguments=arguments, label=label,
                      started=datetime.now(timezone.utc).isoformat(), status='RUNNING')
        report['calls'].append(record)
        save()
        result = await session.call_tool(name, arguments, read_timeout_seconds=__import__('datetime').timedelta(seconds=100))
        filename = f'{index:02}_{label}.json'
        (out/filename).write_text(json.dumps(result.model_dump(mode='json'),ensure_ascii=False,indent=2),encoding='utf-8')
        text = result_text(result)
        (out/f'{index:02}_{label}.txt').write_text(text,encoding='utf-8')
        record.update(status='ERROR' if result.isError else 'RETURNED', evidence=filename,
                      finished=datetime.now(timezone.utc).isoformat())
        save()
        if result.isError:
            raise RuntimeError(f'{name} 返回工具错误；详见 {filename}')
        return text, filename

    save()
    print('结果目录：', out.resolve(), flush=True)
    try:
        async with streamablehttp_client('http://127.0.0.1:39400/mcp') as streams:
            async with ClientSession(streams[0], streams[1]) as session:
                await session.initialize()
                listed = await session.list_tools()
                tools = list(listed.tools)
                while listed.nextCursor:
                    listed = await session.list_tools(cursor=listed.nextCursor)
                    tools.extend(listed.tools)
                catalog = {t.name:t for t in tools}
                for required in ['pt_query_topology','pt_host_command','pt_cli']:
                    if required not in catalog:
                        raise ValueError(f'服务缺少接口 {required}')
                (out/'tool_schemas.json').write_text(json.dumps([t.model_dump(mode='json') for t in tools if t.name in {'pt_query_topology','pt_host_command','pt_cli'}],ensure_ascii=False,indent=2),encoding='utf-8')
                topology, evidence = await invoke(session,catalog,'pt_query_topology',{},'topology')
                names = [args.r0,args.r1,args.r2,args.pc0,args.pc1]
                missing = [n for n in names if not re.search(r'(?<![\w-])'+re.escape(n)+r'(?![\w-])',topology)]
                check('预期设备名称存在', (not missing, '缺少：'+str(missing) if missing else '已找到5个预期名称；不代表全部拓扑已验证。'), evidence)
                if missing:
                    raise ValueError('设备显示名称不匹配；请发 topology 输出，不能猜测后继续测试。')
                for source,target,label in [(args.pc0,'192.168.16.130','PC0_to_PC1'),(args.pc1,'192.168.16.10','PC1_to_PC0')]:
                    arguments=dict(device=source,command=f'ping {target}',timeout=45.0,show=False,capture=False)
                    await invoke(session,catalog,'pt_host_command',arguments,label+'_warmup')
                    text,evidence=await invoke(session,catalog,'pt_host_command',arguments,label+'_ping')
                    check(label+' ping',ping_assert(text,target),evidence)
                for source,target,label,expected in [
                    (args.pc0,'192.168.16.130','PC0_to_PC1',['192.168.16.126','30.0.0.2','192.168.16.130']),
                    (args.pc1,'192.168.16.10','PC1_to_PC0',['192.168.16.190','30.0.0.1','192.168.16.10'])]:
                    text,evidence=await invoke(session,catalog,'pt_host_command',dict(device=source,command=f'tracert {target}',timeout=45.0,show=False,capture=False),label+'_trace')
                    check(label+' 路径',trace_assert(text,expected),evidence)
                route_specs=[(args.r0,'R0',[('192.168.16.128/26','30.0.0.2','Serial0/0/1')]),
                             (args.r1,'R1',[('192.168.16.0/25','10.0.0.1','Serial0/0/0'),('192.168.16.128/26','20.0.0.2','Serial0/0/1')]),
                             (args.r2,'R2',[('192.168.16.0/25','30.0.0.1','Serial0/0/1')])]
                for device,label,specs in route_specs:
                    text,evidence=await invoke(session,catalog,'pt_cli',dict(device=device,commands=['enable','show ip route','show ip protocols','show running-config','show ip ospf neighbor'],timeout=30.0,auto_confirm=False,show=False,capture=False),label+'_routes')
                    process_ok = bool(re.search(r'Routing Protocol is\s+"ospf 100"',text,re.I)) and bool(re.search(r'^\s*router ospf 100\s*$',text,re.M))
                    check(label+' OSPF进程100', (process_ok, '要求实际协议输出与配置均显示OSPF进程100。'), evidence)
                    no_rip = not re.search(r'^\s*router rip\s*$',text,re.M) and not re.search(r'Routing Protocol is\s+"rip"',text,re.I)
                    check(label+' 旧RIP已清除', (no_rip and process_ok, '配置与实际协议输出不应含RIP，且OSPF输出可识别。'), evidence)
                    full_count=len(re.findall(r'\bFULL/',text))
                    check(label+' OSPF邻居', (full_count==2, f'三角形拓扑预期2个FULL邻居，实际识别{full_count}个。'), evidence)
                    for prefix,next_hop,interface in specs:
                        check(label+' '+prefix,route_assert(text,prefix,next_hop,interface),evidence)
                report['status']='PASS' if all(c['passed'] for c in report['checks']) else 'FAIL'
    except Exception as exc:
        report['status']='ERROR'
        report['errors'].append(f'{type(exc).__name__}: {exc}')
        print('连接或采集出错：',type(exc).__name__,str(exc),flush=True)
    finally:
        report['finished']=datetime.now(timezone.utc).isoformat()
        save()
        summary=['# UC-02 自动验收', '', '状态：'+report['status'], '',
                 '这是本机 PT 实际调用的记录。预热结果单独保留，不替代正式 ping；无法解析时不判为通过。', '',
                 '| 检查 | 结果 | 说明 |','|---|---|---|']
        summary += [f"| {c['name']} | {'PASS' if c['passed'] else 'FAIL'} | {c['detail']} |" for c in report['checks']]
        summary += ['', '错误：'+str(report['errors']), '', '本程序不修改配置，不执行修复。']
        (out/'summary.md').write_text('\n'.join(summary),encoding='utf-8')
    print('总结果：',report['status'],'；报告：',out/'acceptance_report.json')
    return 0 if report['status']=='PASS' else 1


def main():
    parser=argparse.ArgumentParser(description='UC-02 本地 PT 只读自动验收。保持 PT 与 MCP 服务打开。')
    parser.add_argument('--run-dir',type=Path,required=False,default=Path('runs/UC02_acceptance'))
    parser.add_argument('--r0',default='Router0')
    parser.add_argument('--r1',default='Router1')
    parser.add_argument('--r2',default='Router2')
    parser.add_argument('--pc0',default='PC0')
    parser.add_argument('--pc1',default='PC1')
    parser.add_argument('--self-test',action='store_true')
    args=parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    return asyncio.run(run(args))


if __name__=='__main__':
    sys.exit(main())
