"""UC-07 read-only ACL/NAPT acceptance. Never modifies device configuration."""
import argparse
import asyncio
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import accept_uc01 as common
from accept_uc04 import ping_lost_all, translation
from accept_uc05 import interface_block, has_line


ACL_LINES=[
    'permit icmp 192.168.30.0 0.0.0.255 192.168.40.0 0.0.0.255 echo-reply',
    'permit tcp 192.168.30.0 0.0.0.255 192.168.40.0 0.0.0.255 established',
    'deny ip 192.168.30.0 0.0.0.255 192.168.40.0 0.0.0.255',
    'permit ip any any',
]


def acl_order(text):
    match=re.search(r'^\s*ip access-list extended GUEST_IN\s*\n(.*?)(?=^[ \t]*(?:!|interface\s|line\s|end\b)|\Z)',text,re.M|re.S)
    if not match:return False
    lines=[line.strip() for line in match.group(1).splitlines() if line.strip()]
    return lines==ACL_LINES


def hit_count(text,rule):
    match=re.search(re.escape(rule)+r'[^\r\n]*\((\d+)\s+match',text,re.I)
    return int(match.group(1)) if match else None


async def run(args):
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client
    out=args.run_dir/('acceptance_'+datetime.now().strftime('%Y%m%d_%H%M%S_%f'));out.mkdir(parents=True)
    report=dict(case_id='UC-07',started=datetime.now(timezone.utc).isoformat(),status='RUNNING',checks=[],calls=[],errors=[],mode='live_read_only',scope='ICMP ACL directions and shared NAPT; TCP established rule configured, not traffic-tested; no full UDP/session firewall claim')
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
                    allowed=name=='pt_query_topology' and arguments=={}
                    if name=='pt_cli':
                        whitelist={'enable','show running-config','show ip route','show ip interface brief','show vlan brief','show interfaces trunk','show ip nat translations','show access-lists','ping 218.75.230.1'}
                        allowed=arguments.get('device') in {'Router0','Router1','Switch0'} and all(c in whitelist for c in arguments.get('commands',[]))
                    if name=='pt_host_command':
                        whitelist={'ping '+ip for ip in ['192.168.30.254','192.168.40.254','192.168.30.10','192.168.40.10','218.75.230.1']}|{'tracert 218.75.230.1'}
                        allowed=arguments.get('device') in {'PC0','PC1'} and arguments.get('command') in whitelist
                    if not allowed:raise ValueError('只读白名单拒绝调用。')
                    n=len(report['calls'])+1;record=dict(index=n,tool=name,arguments=arguments,label=label,status='RUNNING')
                    report['calls'].append(record);save();print(f'[{n}] {label} ...',flush=True)
                    result=await session.call_tool(name,arguments,read_timeout_seconds=timedelta(seconds=100))
                    file=f'{n:02}_{label}.json';text=common.result_text(result).replace('\r\n','\n')
                    (out/file).write_text(json.dumps(result.model_dump(mode='json'),ensure_ascii=False,indent=2),encoding='utf-8')
                    (out/f'{n:02}_{label}.txt').write_text(text,encoding='utf-8')
                    record.update(status='ERROR' if result.isError else 'RETURNED',evidence=file);save()
                    if result.isError or common.command_failed(text):raise ValueError('工具/命令错误：'+file)
                    return text,file
                async def cli(device,commands,label):
                    return await call('pt_cli',dict(device=device,commands=commands,timeout=45.0,auto_confirm=False,show=False,capture=False),label)
                async def host(device,command,label):
                    return await call('pt_host_command',dict(device=device,command=command,timeout=45.0,show=False,capture=False),label)
                top,e=await call('pt_query_topology',{},'topology')
                missing=[n for n in ['Router0','Router1','Switch0','PC0','PC1','Server0'] if not re.search(r'(?<![\w-])'+n+r'(?![\w-])',top)]
                check('设备名称',(not missing,'缺少'+str(missing) if missing else '找到6个预期设备名称。'),e)
                if missing:raise ValueError('设备名称不符。')
                sw,e=await cli('Switch0',['enable','show running-config','show vlan brief','show interfaces trunk'],'Switch0_VLAN')
                for vlan,port in [(30,'FastEthernet0/1'),(40,'FastEthernet0/2')]:
                    block=interface_block(sw,port)
                    active=bool(re.search(r'^\s*'+str(vlan)+r'\s+\S+\s+active\b',sw,re.M))
                    check(f'VLAN{vlan}与接入口',(active and has_line(block,'switchport mode access') and has_line(block,f'switchport access vlan {vlan}'),f'{port}必须属于对应active VLAN。'),e)
                trunk=interface_block(sw,'FastEthernet0/24')
                active=bool(re.search(r'^\s*Fa0/24\s+.+\s+trunking\s+',sw,re.M))
                check('上联Trunk',(active and has_line(trunk,'switchport mode trunk') and has_line(trunk,'switchport trunk allowed vlan 30,40'),'Fa0/24应Trunking，仅允许30、40。'),e)
                r0,e=await cli('Router0',['enable','show running-config','show ip interface brief','show ip route'],'R0_config_routes')
                for vlan in [30,40]:
                    name=f'GigabitEthernet0/0.{vlan}';block=interface_block(r0,name)
                    good=has_line(block,f'encapsulation dot1Q {vlan}') and has_line(block,f'ip address 192.168.{vlan}.254 255.255.255.0') and has_line(block,'ip nat inside')
                    route=bool(re.search(r'^\s*C\s+192\.168\.'+str(vlan)+r'\.0/24[^\n]*'+re.escape(name)+r'\s*$',r0,re.M))
                    check(f'VLAN{vlan}网关与内口',(good and route,'子接口dot1Q、IP、NAT inside及直连路由应一致。'),e)
                parent=interface_block(r0,'GigabitEthernet0/0')
                check('清理旧单网段地址',(not re.search(r'^\s*ip address\s',parent,re.M) and not has_line(parent,'ip nat inside'),'父接口不应残留旧IP或NAT inside。'),e)
                default=bool(re.search(r'^\s*S\*\s+0\.0\.0\.0/0[^\n]*via\s+218\.75\.230\.254\b',r0,re.M))
                check('默认路由',(default,'R0默认路由指向模拟ISP。'),e)
                check('ACL规则与绑定',(acl_order(r0) and has_line(interface_block(r0,'GigabitEthernet0/0.30'),'ip access-group GUEST_IN in'),'顺序为ICMP回包许可、TCP established许可、客人到收银deny、其余permit，入方向绑定客人子接口。'),e)
                nat_lines=['ip nat inside source list 1 pool UC07 overload','ip nat pool UC07 218.75.230.253 218.75.230.253 netmask 255.255.255.252','access-list 1 permit 192.168.30.0 0.0.0.255','access-list 1 permit 192.168.40.0 0.0.0.255']
                check('共享NAPT配置',(all(has_line(r0,line) for line in nat_lines) and has_line(interface_block(r0,'GigabitEthernet0/1'),'ip nat outside'),'仅两私网源共用.253池，外口标记正确。'),e)
                r1,e=await cli('Router1',['enable','show ip route'],'R1_routes')
                direct=all(re.search(r'^\s*C\s+'+re.escape(p)+r'\s',r1,re.M) for p in ['218.75.230.0/25','218.75.230.252/30'])
                extra=bool(re.search(r'^\s*(?:S\*?|R|O(?:\s+IA)?)\s+\d',r1,re.M))
                check('ISP直连路由',(direct and not extra,'ISP不靠额外私网返回路由绕过NAPT。'),e)
                for pc,gw in [('PC0','192.168.30.254'),('PC1','192.168.40.254')]:
                    await host(pc,'ping '+gw,pc+'_gateway_warmup')
                    text,e=await host(pc,'ping '+gw,pc+'_gateway_ping')
                    check(pc+'网关可达',common.ping_assert(text,gw),e)
                text,e=await host('PC0','ping 192.168.40.10','guest_to_cashier_denied')
                check('客人不能主动ping收银',ping_lost_all(text,'192.168.40.10'),e)
                await host('PC1','ping 192.168.30.10','cashier_to_guest_warmup')
                text,e=await host('PC1','ping 192.168.30.10','cashier_to_guest')
                check('收银主动ping客人',common.ping_assert(text,'192.168.30.10'),e)
                for pc,local,gw in [('PC0','192.168.30.10','192.168.30.254'),('PC1','192.168.40.10','192.168.40.254')]:
                    await host(pc,'ping 218.75.230.1',pc+'_WAN_warmup')
                    text,e=await host(pc,'ping 218.75.230.1',pc+'_WAN_ping')
                    check(pc+'访问模拟公网',common.ping_assert(text,'218.75.230.1'),e)
                    text,e=await cli('Router0',['enable','show ip nat translations'],'NAPT_'+pc)
                    check(pc+'实际转换表',translation(text,local),e)
                    text,e=await host(pc,'tracert 218.75.230.1',pc+'_WAN_trace')
                    check(pc+'公网路径',common.trace_assert(text,[gw,'218.75.230.254','218.75.230.1']),e)
                counters,e=await cli('Router0',['enable','show access-lists'],'ACL_counters')
                deny=hit_count(counters,ACL_LINES[2]);reply=hit_count(counters,ACL_LINES[0])
                check('ACL拒绝与回包命中',(deny is not None and deny>=4 and reply is not None and reply>=4,f'期望deny及echo-reply命中均≥4；实际deny={deny}、reply={reply}。'),e)
                report['status']='PASS' if all(c['passed'] for c in report['checks']) else 'FAIL'
    except Exception as exc:
        report['status']='ERROR';report['errors'].append(f'{type(exc).__name__}: {exc}')
        print('采集/连接错误：',type(exc).__name__,str(exc),flush=True)
    finally:
        report['finished']=datetime.now(timezone.utc).isoformat();save()
        lines=['# UC-07 自动验收','','状态：'+report['status'],'','|检查|结果|说明|','|---|---|---|']
        lines.extend(f"|{c['name']}|{'PASS' if c['passed'] else 'FAIL'}|{c['detail']}|" for c in report['checks'])
        lines+=['','仅验证ICMP方向控制与NAPT；TCP established配置已检查，未进行TCP业务测试；不是完整状态防火墙或任意UDP回流证明。','错误：'+str(report['errors'])]
        (out/'summary.md').write_text('\n'.join(lines),encoding='utf-8')
    print('总结果：',report['status'],'；报告：',out/'acceptance_report.json')
    return 0 if report['status']=='PASS' else 1


def self_test():
    text='ip access-list extended GUEST_IN\n '+'\n '.join(ACL_LINES)+'\n!\n'
    assert acl_order(text)
    assert not acl_order(text.replace(ACL_LINES[2],ACL_LINES[3]))
    assert hit_count('30 '+ACL_LINES[2]+' (4 match(es))',ACL_LINES[2])==4
    assert hit_count(ACL_LINES[2],ACL_LINES[2]) is None
    print('4项离线ACL解析检查通过；不是实际PT验收。')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--run-dir',type=Path,default=Path('runs/UC07_acceptance'));p.add_argument('--self-test',action='store_true')
    a=p.parse_args()
    if a.self_test:self_test()
    else:sys.exit(asyncio.run(run(a)))
