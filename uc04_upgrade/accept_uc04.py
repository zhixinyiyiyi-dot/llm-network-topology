"""UC-04 two-stage read-only acceptance against local Packet Tracer."""
import argparse
import asyncio
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import accept_uc01 as common


def ping_lost_all(text,target):
    if common.command_failed(text) or not re.search(r'Pinging\s+'+re.escape(target)+r'\b',text,re.I):
        return False,'无法识别原始目标和命令状态。'
    found=re.findall(r'Packets\s*:\s*Sent\s*=\s*(\d+)\s*,\s*Received\s*=\s*(\d+)\s*,\s*Lost\s*=\s*(\d+)',text,re.I)
    if len(found)!=1:return False,'没有唯一可识别的ping统计。'
    counts=tuple(map(int,found[0]))
    return counts==(4,0,4),f'未启用NAT的预期为4发0收4丢；实际{counts}。'


def translation(text,local):
    pattern=r'^\s*icmp\s+218\.75\.230\.253:\d+\s+'+re.escape(local)+r':\d+\s+218\.75\.230\.1:\d+\s+218\.75\.230\.1:\d+'
    return bool(re.search(pattern,text,re.M)),f'要求原始ICMP转换条目：{local}→218.75.230.253，目标218.75.230.1。'


async def run(args):
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client
    out=args.run_dir/('acceptance_'+args.stage+'_'+datetime.now().strftime('%Y%m%d_%H%M%S_%f'));out.mkdir(parents=True)
    report=dict(case_id='UC-04',stage=args.stage,started=datetime.now(timezone.utc).isoformat(),status='RUNNING',checks=[],calls=[],errors=[],mode='live_read_only')
    def save():
        (out/'acceptance_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    def check(name,result,evidence):
        ok,detail=result
        report['checks'].append(dict(name=name,passed=bool(ok),detail=detail,evidence=evidence));save()
        print(('PASS ' if ok else 'FAIL ')+name+'：'+detail,flush=True)
    save();print('结果目录：',out.resolve(),flush=True)
    try:
        async with streamablehttp_client('http://127.0.0.1:39400/mcp') as streams:
            async with ClientSession(streams[0],streams[1]) as session:
                await session.initialize()
                async def call(name,arguments,label):
                    allowed=False
                    if name=='pt_query_topology':allowed=arguments=={}
                    elif name=='pt_host_command':
                        allowed=arguments.get('device') in {'PC0','PC1'} and arguments.get('command') in {'ping 218.75.230.1','tracert 218.75.230.1'}
                    elif name=='pt_cli':
                        readonly={'enable','show ip route','show running-config','show ip nat translations','show ip nat statistics','ping 218.75.230.1'}
                        allowed=arguments.get('device') in {'Router0','Router1'} and all(c in readonly for c in arguments.get('commands',[]))
                    if not allowed:raise ValueError('只读白名单拒绝调用。')
                    index=len(report['calls'])+1
                    item=dict(index=index,tool=name,arguments=arguments,label=label,status='RUNNING')
                    report['calls'].append(item);save();print(f'[{index}] {label} ...',flush=True)
                    result=await session.call_tool(name,arguments,read_timeout_seconds=timedelta(seconds=100))
                    file=f'{index:02}_{label}.json';text=common.result_text(result)
                    (out/file).write_text(json.dumps(result.model_dump(mode='json'),ensure_ascii=False,indent=2),encoding='utf-8')
                    (out/f'{index:02}_{label}.txt').write_text(text,encoding='utf-8')
                    item.update(status='ERROR' if result.isError else 'RETURNED',evidence=file);save()
                    if result.isError or common.command_failed(text):raise ValueError('工具/命令错误，见'+file)
                    return text,file
                async def cli(device,commands,label):
                    return await call('pt_cli',dict(device=device,commands=commands,timeout=45.0,auto_confirm=False,show=False,capture=False),label)
                topology,e=await call('pt_query_topology',{},'topology')
                names=['Router0','Router1','Switch0','PC0','PC1','Server0']
                missing=[n for n in names if not re.search(r'(?<![\w-])'+re.escape(n)+r'(?![\w-])',topology)]
                check('设备存在',(not missing,'缺少'+str(missing) if missing else '找到6个预期设备名称。'),e)
                if missing:raise ValueError('设备显示名称不匹配，停止。')
                r0,e=await cli('Router0',['enable','show running-config','show ip route'],'R0_config_route')
                default=bool(re.search(r'^\s*S\*\s+0\.0\.0\.0/0[^\n]*via\s+218\.75\.230\.254\b',r0,re.M))
                check('R0默认路由',(default,'要求默认静态路由指向218.75.230.254。'),e)
                nat_enabled=bool(re.search(r'^\s*ip nat inside source list 1 pool UC04 overload\s*$',r0,re.M))
                check('NAPT阶段',(nat_enabled if args.stage=='after' else not re.search(r'^\s*ip nat inside source',r0,re.M),'after应启用指定NAPT规则；before不得启用源地址转换。'),e)
                if args.stage=='after':
                    rules=[r'access-list 1 permit 192\.168\.0\.0 0\.0\.0\.255',r'ip nat pool UC04 218\.75\.230\.253 218\.75\.230\.253 netmask 255\.255\.255\.252']
                    ok=all(re.search(r'^\s*'+p+r'\s*$',r0,re.M) for p in rules)
                    check('NAPT地址池和源范围',(ok,'要求单地址.253池，仅permit 192.168.0.0/24。'),e)
                r1,e=await cli('Router1',['enable','show ip route'],'R1_routes')
                direct=all(re.search(r'^\s*C\s+'+re.escape(p)+r'\s',r1,re.M) for p in ['218.75.230.0/25','218.75.230.252/30'])
                private=bool(re.search(r'^\s*(?:S\*?|R|O(?:\s+IA)?)\s+\d',r1,re.M))
                check('ISP仅有预期直连路由',(direct and not private,'不靠ISP额外私网/默认路由绕过NAT需求。'),e)
                # Prove outside network works independently of inside-PC failure.
                await cli('Router0',['enable','ping 218.75.230.1'],'R0_server_warmup')
                probe,e=await cli('Router0',['enable','ping 218.75.230.1'],'R0_server_ping')
                rates=re.findall(r'Success rate is\s+(\d+)\s+percent',probe,re.I)
                check('外网基础连通',(rates==['100'],'R0自身到Server0的正式ping应为100%。'),e)
                for pc,local in [('PC0','192.168.0.1'),('PC1','192.168.0.2')]:
                    arg=dict(device=pc,command='ping 218.75.230.1',timeout=45.0,show=False,capture=False)
                    await call('pt_host_command',arg,pc+'_warmup')
                    result,e=await call('pt_host_command',arg,pc+'_ping')
                    check(pc+'到Server0',common.ping_assert(result,'218.75.230.1') if args.stage=='after' else ping_lost_all(result,'218.75.230.1'),e)
                    if args.stage=='after':
                        table,e=await cli('Router0',['enable','show ip nat translations'],'R0_NAT_'+pc)
                        check(pc+'地址转换',translation(table,local),e)
                        trace,e=await call('pt_host_command',dict(device=pc,command='tracert 218.75.230.1',timeout=45.0,show=False,capture=False),pc+'_trace')
                        check(pc+'路径',common.trace_assert(trace,['192.168.0.254','218.75.230.254','218.75.230.1']),e)
                report['status']='PASS' if all(c['passed'] for c in report['checks']) else 'FAIL'
    except Exception as exc:
        report['status']='ERROR';report['errors'].append(f'{type(exc).__name__}: {exc}')
        print('采集/连接错误：',type(exc).__name__,str(exc),flush=True)
    finally:
        report['finished']=datetime.now(timezone.utc).isoformat();save()
        lines=['# UC-04 '+args.stage+' 阶段验收','','状态：'+report['status'],'','| 检查 | 结果 | 说明 |','|---|---|---|']
        lines.extend(f"|{c['name']}|{'PASS' if c['passed'] else 'FAIL'}|{c['detail']}|" for c in report['checks'])
        lines+=['','本程序只读；before阶段PC不通是预期，须同时证明外网本身可达。','错误：'+str(report['errors'])]
        (out/'summary.md').write_text('\n'.join(lines),encoding='utf-8')
    print('总结果：',report['status'],'；报告：',out/'acceptance_report.json')
    return 0 if report['status']=='PASS' else 1


def self_test():
    raw='Pinging 218.75.230.1 with 32 bytes of data:\nPackets: Sent = 4, Received = 0, Lost = 4 (100% loss),'
    assert ping_lost_all(raw,'218.75.230.1')[0]
    assert not ping_lost_all(raw.replace('Received = 0','Received = 1'),'218.75.230.1')[0]
    assert not ping_lost_all('TIMEOUT','218.75.230.1')[0]
    row='icmp 218.75.230.253:10 192.168.0.1:10 218.75.230.1:10 218.75.230.1:10'
    assert translation(row,'192.168.0.1')[0]
    assert not translation(row,'192.168.0.2')[0]
    assert not translation(row.replace('218.75.230.253','218.75.230.254'),'192.168.0.1')[0]
    print('6项离线解析检查通过；不是PT实际验收。')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--run-dir',type=Path,default=Path('runs/UC04_acceptance'))
    p.add_argument('--stage',choices=['before','after']);p.add_argument('--self-test',action='store_true')
    a=p.parse_args()
    if a.self_test:self_test()
    elif not a.stage:p.error('必须指定 --stage before 或 after')
    else:sys.exit(asyncio.run(run(a)))
