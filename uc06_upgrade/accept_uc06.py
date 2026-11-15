"""Read-only UC-06 LAN acceptance through local PT MCP."""
import argparse
import asyncio
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import accept_uc01 as common


def ipconfig_check(text,expected):
    address=bool(re.search(r'(?:IPv4 Address|IP Address)[ .:\t]*'+re.escape(expected)+r'\b',text,re.I))
    mask=bool(re.search(r'Subnet Mask[ .:\t]*255\.255\.255\.0\b',text,re.I))
    gateway=re.search(r'Default Gateway[ .:\t]*([^\r\n]*)',text,re.I)
    empty=gateway is not None and gateway.group(1).strip() in {'','0.0.0.0'}
    return address and mask and empty and not common.command_failed(text),f'要求{expected}/24，默认网关为空或0.0.0.0。'


async def run(args):
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client
    out=args.run_dir/('acceptance_'+datetime.now().strftime('%Y%m%d_%H%M%S_%f'));out.mkdir(parents=True)
    report=dict(case_id='UC-06',started=datetime.now(timezone.utc).isoformat(),status='RUNNING',checks=[],calls=[],errors=[],mode='live_read_only',routing_assertion='N/A: same LAN, no router/default gateway required')
    def save():
        (out/'acceptance_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    def check(name,result,evidence):
        ok,detail=result
        report['checks'].append(dict(name=name,passed=bool(ok),detail=detail,evidence=evidence));save()
        print(('PASS ' if ok else 'FAIL ')+name+'：'+detail,flush=True)
    print('结果目录：',out.resolve(),flush=True);save()
    try:
        async with streamablehttp_client('http://127.0.0.1:39400/mcp') as streams:
            async with ClientSession(streams[0],streams[1]) as session:
                await session.initialize()
                async def call(name,arguments,label):
                    allowed=(name=='pt_query_topology' and arguments=={})
                    if name=='pt_host_command':
                        allowed=arguments.get('device') in {'PC0','PC1'} and arguments.get('command') in {'ipconfig','ping 192.168.1.1','ping 192.168.1.2','tracert 192.168.1.2'}
                    if name=='pt_cli':allowed=arguments.get('device')=='Switch0' and arguments.get('commands')==['enable','show running-config','show vlan brief']
                    if not allowed:raise ValueError('只读白名单拒绝调用。')
                    n=len(report['calls'])+1;record=dict(index=n,tool=name,arguments=arguments,label=label,status='RUNNING');report['calls'].append(record);save()
                    print(f'[{n}] {label} ...',flush=True)
                    result=await session.call_tool(name,arguments,read_timeout_seconds=timedelta(seconds=100))
                    file=f'{n:02}_{label}.json';text=common.result_text(result)
                    (out/file).write_text(json.dumps(result.model_dump(mode='json'),ensure_ascii=False,indent=2),encoding='utf-8')
                    (out/f'{n:02}_{label}.txt').write_text(text,encoding='utf-8')
                    record.update(status='ERROR' if result.isError else 'RETURNED',evidence=file);save()
                    if result.isError or common.command_failed(text):raise ValueError('工具/命令错误：'+file)
                    return text,file
                async def host(device,command,label):
                    return await call('pt_host_command',dict(device=device,command=command,timeout=45.0,show=False,capture=False),label)
                top,e=await call('pt_query_topology',{},'topology')
                present=all(re.search(r'(?<![\w-])'+name+r'(?![\w-])',top) for name in ['PC0','PC1','Switch0'])
                check('设备名称',(present,'要求PC0、PC1、Switch0存在；名称检查不等于完整拓扑证明。'),e)
                if not present:raise ValueError('设备显示名称不匹配。')
                sw,e=await call('pt_cli',dict(device='Switch0',commands=['enable','show running-config','show vlan brief'],timeout=30.0,auto_confirm=False,show=False,capture=False),'Switch0_vlan')
                vlan1=bool(re.search(r'^\s*1\s+\S+\s+active\b[^\n]*Fa0/1\b[^\n]*Fa0/2\b',sw,re.M))
                check('默认VLAN1',(vlan1,'两接入端口应在默认VLAN1的active成员中。'),e)
                for pc,ip in [('PC0','192.168.1.1'),('PC1','192.168.1.2')]:
                    text,e=await host(pc,'ipconfig',pc+'_ipconfig')
                    check(pc+'地址与空网关',ipconfig_check(text,ip),e)
                for source,target,label in [('PC0','192.168.1.2','PC0_to_PC1'),('PC1','192.168.1.1','PC1_to_PC0')]:
                    await host(source,'ping '+target,label+'_warmup')
                    text,e=await host(source,'ping '+target,label+'_ping')
                    check(label,common.ping_assert(text,target),e)
                text,e=await host('PC0','tracert 192.168.1.2','PC0_trace')
                check('同网段直接路径',common.trace_assert(text,['192.168.1.2']),e)
                report['status']='PASS' if all(c['passed'] for c in report['checks']) else 'FAIL'
    except Exception as exc:
        report['status']='ERROR';report['errors'].append(f'{type(exc).__name__}: {exc}')
        print('连接/采集错误：',type(exc).__name__,str(exc),flush=True)
    finally:
        report['finished']=datetime.now(timezone.utc).isoformat();save()
        lines=['# UC-06 自动验收','','状态：'+report['status'],'','|检查|结果|说明|','|---|---|---|']
        lines.extend(f"|{c['name']}|{'PASS' if c['passed'] else 'FAIL'}|{c['detail']}|" for c in report['checks'])
        lines+=['','同LAN用例无路由表断言，记为不适用，不虚构路由验证成功。','本程序只读；错误：'+str(report['errors'])]
        (out/'summary.md').write_text('\n'.join(lines),encoding='utf-8')
    print('总结果：',report['status'],'；报告：',out/'acceptance_report.json')
    return 0 if report['status']=='PASS' else 1


def self_test():
    raw='IP Address......................: 192.168.1.1\nSubnet Mask.....................: 255.255.255.0\nDefault Gateway.................: 0.0.0.0\n'
    assert ipconfig_check(raw,'192.168.1.1')[0]
    assert ipconfig_check(raw.replace('0.0.0.0',''),'192.168.1.1')[0]
    assert not ipconfig_check(raw,'192.168.1.2')[0]
    assert not ipconfig_check(raw.replace('0.0.0.0','192.168.1.254'),'192.168.1.1')[0]
    assert not ipconfig_check(raw.replace('255.255.255.0','255.255.255.128'),'192.168.1.1')[0]
    print('5项离线ipconfig解析检查通过；不是PT实际验收。')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--run-dir',type=Path,default=Path('runs/UC06_acceptance'));p.add_argument('--self-test',action='store_true')
    a=p.parse_args()
    if a.self_test:self_test()
    else:sys.exit(asyncio.run(run(a)))
