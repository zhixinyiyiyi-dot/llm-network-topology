"""Read-only UC-05 acceptance for router-on-a-stick and SVI variants."""
import argparse
import asyncio
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import accept_uc01 as common


def interface_block(text,name):
    text=text.replace('\r\n','\n')
    match=re.search(r'^[ \t]*interface[ \t]+'+re.escape(name)+r'[ \t]*\r?\n(.*?)(?=^[ \t]*(?:interface[ \t]|!|end\b)|\Z)',text,re.M|re.S)
    return match.group(1) if match else ''


def has_line(text,line):
    text=text.replace('\r\n','\n')
    return re.search(r'^[ \t]*'+re.escape(line)+r'[ \t]*$',text,re.M|re.I) is not None


async def run(args):
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client
    out=args.run_dir/('acceptance_'+args.variant+'_'+datetime.now().strftime('%Y%m%d_%H%M%S_%f'));out.mkdir(parents=True)
    report=dict(case_id='UC-05',variant=args.variant,started=datetime.now(timezone.utc).isoformat(),status='RUNNING',checks=[],calls=[],errors=[],mode='live_read_only')
    def save():
        (out/'acceptance_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    def check(name,ok,detail,evidence):
        report['checks'].append(dict(name=name,passed=bool(ok),detail=detail,evidence=evidence));save()
        print(('PASS ' if ok else 'FAIL ')+name+'：'+detail,flush=True)
    print('结果目录：',out.resolve(),flush=True);save()
    pcs={f'PC{i}':f'192.168.{1 if i<3 else 2}.{i%3+1}' for i in range(6)}
    try:
        async with streamablehttp_client('http://127.0.0.1:39400/mcp') as streams:
            async with ClientSession(streams[0],streams[1]) as session:
                await session.initialize()
                async def call(name,arguments,label):
                    allowed=False
                    if name=='pt_query_topology':allowed=arguments=={}
                    elif name=='pt_cli':
                        commands={'enable','show running-config','show ip route','show ip interface brief','show vlan brief','show interfaces trunk'}
                        allowed=arguments.get('device') in {'Router0','Switch0'} and all(c in commands for c in arguments.get('commands',[]))
                    elif name=='pt_host_command':
                        targets=set(pcs.values())|{'192.168.1.254','192.168.2.254'}
                        allowed=arguments.get('device') in pcs and arguments.get('command') in {f'{verb} {ip}' for verb in ['ping','tracert'] for ip in targets}
                    if not allowed:raise ValueError('只读白名单拒绝调用。')
                    n=len(report['calls'])+1;record=dict(index=n,tool=name,arguments=arguments,label=label,status='RUNNING')
                    report['calls'].append(record);save();print(f'[{n}] {label} ...',flush=True)
                    result=await session.call_tool(name,arguments,read_timeout_seconds=timedelta(seconds=100))
                    file=f'{n:02}_{label}.json';text=common.result_text(result)
                    (out/file).write_text(json.dumps(result.model_dump(mode='json'),ensure_ascii=False,indent=2),encoding='utf-8')
                    (out/f'{n:02}_{label}.txt').write_text(text,encoding='utf-8')
                    record.update(status='ERROR' if result.isError else 'RETURNED',evidence=file);save()
                    if result.isError or common.command_failed(text):raise ValueError('工具/命令错误：'+file)
                    return text,file
                async def cli(device,commands,label):
                    return await call('pt_cli',dict(device=device,commands=commands,timeout=30.0,auto_confirm=False,show=False,capture=False),label)
                async def host(device,command,label):
                    return await call('pt_host_command',dict(device=device,command=command,timeout=45.0,show=False,capture=False),label)
                top,e=await call('pt_query_topology',{},'topology')
                required=set(pcs)|{'Switch0'}|({'Router0'} if args.variant=='router_on_a_stick' else set())
                missing=[name for name in required if not re.search(r'(?<![\w-])'+re.escape(name)+r'(?![\w-])',top)]
                check('设备存在',not missing,'缺少'+str(missing) if missing else '已找到所有预期设备名称。',e)
                if missing:raise ValueError('设备显示名称不符。')
                sw,e=await cli('Switch0',['enable','show running-config','show vlan brief','show interfaces trunk'],'Switch0_vlan_config')
                for vlan in [10,20]:
                    active=bool(re.search(r'^\s*'+str(vlan)+r'\s+\S+\s+active\b',sw,re.M))
                    check(f'VLAN{vlan}存在',active,'show vlan brief应显示该VLAN active。',e)
                for i in range(6):
                    vlan=10 if i<3 else 20;name=f'FastEthernet0/{i+1}';block=interface_block(sw,name)
                    good=has_line(block,'switchport mode access') and has_line(block,f'switchport access vlan {vlan}')
                    check(name+'接入VLAN',good,f'要求access VLAN {vlan}。',e)
                if args.variant=='router_on_a_stick':
                    trunk=interface_block(sw,'GigabitEthernet0/1')
                    good=has_line(trunk,'switchport mode trunk') and has_line(trunk,'switchport trunk allowed vlan 10,20')
                    active=bool(re.search(r'^\s*(?:Gi|Gig)0/1\s+.+\s+trunking\s+',sw,re.M))
                    check('上联Trunk',good and active,'Gi0/1配置允许10,20，实际状态trunking。',e)
                    router,e=await cli('Router0',['enable','show running-config','show ip interface brief','show ip route'],'Router0_subinterfaces_routes')
                    for vlan,subnet in [(10,1),(20,2)]:
                        name=f'GigabitEthernet0/0.{vlan}';block=interface_block(router,name)
                        good=has_line(block,f'encapsulation dot1Q {vlan}') and has_line(block,f'ip address 192.168.{subnet}.254 255.255.255.0')
                        up=bool(re.search(r'^\s*'+re.escape(name)+r'\s+192\.168\.'+str(subnet)+r'\.254\s+YES\s+\S+\s+up\s+up\s*$',router,re.M))
                        check(name,good and up,'要求dot1Q、网关正确且up/up。',e)
                    route_text=router
                else:
                    route_text,e=await cli('Switch0',['enable','show ip route','show ip interface brief'],'Switch0_svi_routes')
                    check('三层转发',has_line(sw,'ip routing'),'实际配置中必须启用ip routing。',e)
                    for vlan,subnet in [(10,1),(20,2)]:
                        block=interface_block(sw,f'Vlan{vlan}')
                        good=has_line(block,f'ip address 192.168.{subnet}.254 255.255.255.0')
                        up=bool(re.search(r'^\s*Vlan'+str(vlan)+r'\s+192\.168\.'+str(subnet)+r'\.254\s+YES\s+\S+\s+up\s+up\s*$',route_text,re.M))
                        check(f'Vlan{vlan} SVI',good and up,'要求网关地址正确且SVI up/up。',e)
                for vlan,subnet in [(10,1),(20,2)]:
                    iface=f'GigabitEthernet0/0.{vlan}' if args.variant=='router_on_a_stick' else f'Vlan{vlan}'
                    good=bool(re.search(r'^\s*C\s+192\.168\.'+str(subnet)+r'\.0/24[^\n]*'+re.escape(iface)+r'\s*$',route_text,re.M))
                    check(f'192.168.{subnet}.0/24直连路由',good,'要求通过对应子接口/SVI直连。',e)
                # One gateway warm-up per host, retained separately from formal measurements.
                for i in range(6):
                    gateway=f'192.168.{1 if i<3 else 2}.254'
                    await host(f'PC{i}','ping '+gateway,f'PC{i}_gateway_warmup')
                for source in pcs:
                    for destination,ip in pcs.items():
                        if source==destination:continue
                        text,e=await host(source,'ping '+ip,source+'_to_'+destination)
                        ok,detail=common.ping_assert(text,ip)
                        check(source+'→'+destination,ok,detail,e)
                for source,target,gateway in [('PC0','192.168.2.1','192.168.1.254'),('PC3','192.168.1.1','192.168.2.254')]:
                    text,e=await host(source,'tracert '+target,source+'_cross_vlan_trace')
                    ok,detail=common.trace_assert(text,[gateway,target])
                    check(source+'跨VLAN路径',ok,detail,e)
                report['status']='PASS' if all(c['passed'] for c in report['checks']) else 'FAIL'
    except Exception as exc:
        report['status']='ERROR';report['errors'].append(f'{type(exc).__name__}: {exc}')
        print('连接/采集错误：',type(exc).__name__,str(exc),flush=True)
    finally:
        report['finished']=datetime.now(timezone.utc).isoformat();save()
        lines=['# UC-05 '+args.variant+' 自动验收','','状态：'+report['status'],'','|检查|结果|说明|','|---|---|---|']
        lines.extend(f"|{c['name']}|{'PASS' if c['passed'] else 'FAIL'}|{c['detail']}|" for c in report['checks'])
        lines+=['','6台PC的30个有向ping，网关预热单独留档；本程序不修改配置。','错误：'+str(report['errors'])]
        (out/'summary.md').write_text('\n'.join(lines),encoding='utf-8')
    print('总结果：',report['status'],'；报告：',out/'acceptance_report.json')
    return 0 if report['status']=='PASS' else 1


def self_test():
    sample='interface GigabitEthernet0/0.10\n encapsulation dot1Q 10\n ip address 192.168.1.254 255.255.255.0\n!\ninterface GigabitEthernet0/0.20\n encapsulation dot1Q 20\n!'
    block=interface_block(sample,'GigabitEthernet0/0.10')
    assert has_line(block,'encapsulation dot1Q 10')
    assert not has_line(block,'encapsulation dot1Q 20')
    assert interface_block(sample,'Vlan10')==''
    assert has_line(interface_block('interface Vlan10\r\n ip address 192.168.1.254 255.255.255.0\r\n!','Vlan10'),'ip address 192.168.1.254 255.255.255.0')
    print('4项离线接口解析检查通过；不是实际PT验收。')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--run-dir',type=Path,default=Path('runs/UC05_acceptance'))
    p.add_argument('--variant',choices=['router_on_a_stick','svi'],default='router_on_a_stick');p.add_argument('--self-test',action='store_true')
    a=p.parse_args()
    if a.self_test:self_test()
    else:sys.exit(asyncio.run(run(a)))
