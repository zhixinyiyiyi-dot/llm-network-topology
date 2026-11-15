"""Live read-only UC10: underlay gate before IPv6 verification."""
import argparse,asyncio,json,re,sys
from datetime import datetime,timedelta,timezone
from pathlib import Path
import accept_uc01 as common

def ios_ping(text):
    stats=re.findall(r'Success rate is\s+(\d+)\s+percent\s*\((\d+)/(\d+)\)',text,re.I)
    return not common.command_failed(text) and stats==[('100','5','5')],f'IOS正式ping要求100%、5/5；实际{stats}'
def config_line(text,line):return re.search(r'^\s*'+re.escape(line)+r'\s*$',text,re.M|re.I) is not None

async def run(args):
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client
    out=args.run_dir/('acceptance_'+datetime.now().strftime('%Y%m%d_%H%M%S_%f'));out.mkdir(parents=True)
    report=dict(case_id='UC-10',status='RUNNING',started=datetime.now(timezone.utc).isoformat(),checks=[],calls=[],errors=[],mode='live_read_only',ipv4_gate_passed=False)
    def save():(out/'acceptance_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    def check(name,result,evidence):
        ok,detail=result;report['checks'].append(dict(name=name,passed=bool(ok),detail=detail,evidence=evidence));save();print(('PASS ' if ok else 'FAIL ')+name+'：'+detail,flush=True);return ok
    print('结果目录：',out.resolve(),flush=True);save()
    try:
        async with streamablehttp_client('http://127.0.0.1:39400/mcp') as streams:
            async with ClientSession(streams[0],streams[1]) as session:
                await session.initialize()
                async def call(tool,params,label):
                    valid=tool=='pt_query_topology' and params=={}
                    if tool=='pt_cli':
                        valid=params.get('device') in ['Router0','Router1','Router2'] and all(c in ['enable','show running-config','show ip interface brief','show ip route','show ipv6 interface brief','show ipv6 route','ping 10.0.0.6','ping 10.0.0.1'] for c in params.get('commands',[]))
                    if tool=='pt_host_command':valid=(params.get('device'),params.get('command')) in [('PC0','ping 2002::10'),('PC1','ping 2001::10'),('PC0','ipconfig /all'),('PC1','ipconfig /all'),('PC0','tracert 2002::10'),('PC1','tracert 2001::10')]
                    if not valid:raise ValueError('只读白名单拒绝调用')
                    n=len(report['calls'])+1;print(f'[{n}] {label} ...',flush=True)
                    rec=dict(tool=tool,arguments=params,label=label);report['calls'].append(rec);save()
                    r=await session.call_tool(tool,params,read_timeout_seconds=timedelta(seconds=120));text=common.result_text(r).replace('\r\n','\n');file=f'{n:02}_{label}.txt'
                    (out/file).write_text(text,encoding='utf-8');(out/file.replace('.txt','.json')).write_text(json.dumps(r.model_dump(mode='json'),ensure_ascii=False,indent=2),encoding='utf-8');rec['evidence']=file;save()
                    if r.isError or common.command_failed(text):raise ValueError('工具/命令错误：'+file)
                    return text,file
                async def cli(dev,cmds,label):return await call('pt_cli',dict(device=dev,commands=cmds,timeout=45.0,auto_confirm=False,show=False,capture=False),label)
                async def host(dev,cmd,label):return await call('pt_host_command',dict(device=dev,command=cmd,timeout=45.0,show=False,capture=False),label)
                t,e=await call('pt_query_topology',{},'topology');check('设备名称',(all(re.search(r'(?<![\w-])'+n+r'(?![\w-])',t) for n in ['Router0','Router1','Router2','PC0','PC1']),'要求五个预期设备名；非完整接线证明'),e)
                gate=[]
                for dev,target in [('Router0','10.0.0.6'),('Router2','10.0.0.1')]:
                    await cli(dev,['enable','ping '+target],dev+'_IPv4_warmup')
                    t,e=await cli(dev,['enable','ping '+target],dev+'_IPv4_ping');gate.append(check(dev+'隧道端点IPv4',ios_ping(t),e))
                report['ipv4_gate_passed']=all(gate);save()
                if not all(gate):raise ValueError('IPv4底层未通过，停止IPv6验收；未执行的IPv6测试不算成功')
                for dev,local,remote,route in [('Router0','10.0.0.1','10.0.0.6','ipv6 route 2002::/64 2003::2'),('Router2','10.0.0.6','10.0.0.1','ipv6 route 2001::/64 2003::1')]:
                    t,e=await cli(dev,['enable','show running-config','show ipv6 interface brief','show ipv6 route'],dev+'_tunnel_state')
                    required=['ipv6 unicast-routing','interface Tunnel0','tunnel source '+local,'tunnel destination '+remote,'tunnel mode ipv6ip',route]
                    ok=all(config_line(t,line) for line in required)
                    check(dev+'隧道配置',(ok,'要求IPv6转发、Tunnel0、准确IPv4端点、手动ipv6ip及远端IPv6静态路由'),e)
                    up=bool(re.search(r'Tunnel0\s+\[up/up\]',t,re.I))
                    check(dev+'隧道状态',(up,'要求show ipv6 interface brief明确显示Tunnel0 [up/up]'),e)
                t,e=await cli('Router1',['enable','show running-config','show ip interface brief','show ip route'],'IPv4_only_core')
                check('骨干保持纯IPv4',(not re.search(r'^\s*(?:ipv6 address|ipv6 unicast-routing|interface Tunnel)',t,re.M|re.I),'中间路由器不得配置IPv6转发、IPv6地址或隧道'),e)
                for dev,target in [('PC0','2002::10'),('PC1','2001::10')]:
                    await host(dev,'ping '+target,dev+'_IPv6_warmup')
                    t,e=await host(dev,'ping '+target,dev+'_IPv6_ping');check(dev+'端到端IPv6',common.ping_assert(t,target),e)
                    # Preserve path evidence without assuming simulator-specific IPv6 trace rendering.
                    t,e=await host(dev,'tracert '+target,dev+'_IPv6_trace');report.setdefault('path_evidence',[]).append(e);save()
                report['status']='PASS' if all(c['passed'] for c in report['checks']) else 'FAIL'
    except Exception as exc:
        report['errors'].append(type(exc).__name__+': '+str(exc));report['status']='ERROR';print('已停止：',str(exc),flush=True)
    finally:
        report['finished']=datetime.now(timezone.utc).isoformat();save()
        lines=['# UC-10 验收','', '状态：'+report['status'],'','IPv4门槛通过：'+str(report['ipv4_gate_passed']),'','|检查|结果|说明|','|---|---|---|']
        lines += [f"|{c['name']}|{'PASS' if c['passed'] else 'FAIL'}|{c['detail']}|" for c in report['checks']]
        lines+=['','路径输出只保留原始证据，未声明精确路径自动断言通过。','本次为只读验收，不计Agent修复轮数。','错误：'+str(report['errors'])]
        (out/'summary.md').write_text('\n'.join(lines),encoding='utf-8')
    print('总结果：',report['status'],'；报告：',out/'acceptance_report.json');return 0 if report['status']=='PASS' else 1
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--run-dir',type=Path,required=True);sys.exit(asyncio.run(run(p.parse_args())))
