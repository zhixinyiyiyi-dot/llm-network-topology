"""Read-only UC-09 eBGP session, BGP-table, RIB and connectivity acceptance."""
import argparse
import asyncio
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import accept_uc01 as common


def local_identity(text, local_as, rid):
    text=text.replace('\r\n','\n')
    configured=re.findall(r'^\s*router bgp (\d+)\s*$',text,re.M)
    active=re.findall(r'^BGP router identifier ([0-9.]+), local AS number (\d+)\s*$',text,re.M)
    table_ids=re.findall(r'^BGP table version[^\n]*local router ID is ([0-9.]+)\s*$',text,re.M)
    explicit=re.findall(r'^\s*bgp router-id ([0-9.]+)\s*$',text,re.M)
    ok=(configured==[str(local_as)] and active==[(rid,str(local_as))]
        and table_ids==[rid] and all(value==rid for value in explicit))
    return ok, f'要求配置AS{local_as}，实际BGP摘要AS/router-id及BGP表router-id一致；摘要={active}，表ID={table_ids}，显式ID={explicit}。'


def session_established(text,peer,remote_as):
    for line in text.splitlines():
        if re.match(r'^\s*'+re.escape(peer)+r'\s+4\s+'+str(remote_as)+r'\s+',line):
            last=line.split()[-1]
            return last.isdigit() and int(last)>=1
    return False


def bgp_path(text,prefix,hop,asn):
    pattern=r'^.*?'+re.escape(prefix)+r'\s+'+re.escape(hop)+r'\s+[^\n]*\b'+str(asn)+r'\s+i\s*$'
    return re.search(pattern,text,re.M) is not None


def installed(text,prefix,hop):
    return re.search(r'^\s*B\s+'+re.escape(prefix)+r'\s+\[20/\d+\]\s+via\s+'+re.escape(hop)+r'(?:,|\s*$)',text,re.M) is not None


def ios_ping(text):
    found=re.findall(r'Success rate is\s+(\d+)\s+percent\s*\((\d+)/(\d+)\)',text,re.I)
    ok=not common.command_failed(text) and found==[('100','5','5')]
    return ok,'要求IOS正式ping为100%、5/5；识别到'+str(found)+'。'


def ios_trace(text,target,peer):
    if common.command_failed(text) or '*' in text or not re.search(r'Tracing the route to\s+'+re.escape(target),text,re.I):
        return False,'未识别到完整无超时的本次IOS路径。'
    hops=[]
    for line in text.splitlines():
        if re.match(r'^\s*\d+\s+',line):
            addresses=re.findall(r'\b(?:\d{1,3}\.){3}\d{1,3}\b',line)
            if not addresses:return False,'跳记录没有明确IPv4。'
            hops.append(addresses)
    ok=len(hops)==1 and all(ip in {target,peer} for ip in hops[0])
    return ok,f'实际跳记录{hops}；要求一跳到承载目标Loopback的对端路由器（{target}或其链路接口{peer}响应）。'


async def run(args):
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client
    out=args.run_dir/('acceptance_'+datetime.now().strftime('%Y%m%d_%H%M%S_%f'));out.mkdir(parents=True)
    report=dict(case_id='UC-09',started=datetime.now(timezone.utc).isoformat(),status='RUNNING',checks=[],calls=[],errors=[],mode='live_read_only',adaptation='original 10.0.0.0/24 advertisement retained; additional AS100 Loopback10.1/24 makes remote BGP RIB installation distinguishable from connected link')
    def save():
        (out/'acceptance_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    def check(name,result,evidence):
        ok,detail=result;report['checks'].append(dict(name=name,passed=bool(ok),detail=detail,evidence=evidence));save()
        print(('PASS ' if ok else 'FAIL ')+name+'：'+detail,flush=True)
    save();print('结果目录：',out.resolve(),flush=True)
    try:
        async with streamablehttp_client('http://127.0.0.1:39400/mcp') as streams:
            async with ClientSession(streams[0],streams[1]) as session:
                await session.initialize()
                async def call(name,arguments,label):
                    allowed=name=='pt_query_topology' and arguments=={}
                    if name=='pt_cli':
                        whitelist={'enable','show running-config','show ip interface brief','show ip bgp summary','show ip bgp','show ip route','ping 20.0.0.1','ping 10.1.0.1','traceroute 20.0.0.1','traceroute 10.1.0.1'}
                        allowed=arguments.get('device') in {'Router0','Router1'} and all(command in whitelist for command in arguments.get('commands',[]))
                    if not allowed:raise ValueError('只读白名单拒绝调用。')
                    n=len(report['calls'])+1;record=dict(index=n,tool=name,arguments=arguments,label=label,status='RUNNING');report['calls'].append(record);save();print(f'[{n}] {label} ...',flush=True)
                    result=await session.call_tool(name,arguments,read_timeout_seconds=timedelta(seconds=120))
                    file=f'{n:02}_{label}.json';text=common.result_text(result).replace('\r\n','\n')
                    (out/file).write_text(json.dumps(result.model_dump(mode='json'),ensure_ascii=False,indent=2),encoding='utf-8')
                    (out/f'{n:02}_{label}.txt').write_text(text,encoding='utf-8')
                    record.update(status='ERROR' if result.isError else 'RETURNED',evidence=file);save()
                    if result.isError or common.command_failed(text):raise ValueError('工具/命令错误：'+file)
                    return text,file
                async def cli(device,commands,label):
                    return await call('pt_cli',dict(device=device,commands=commands,timeout=45.0,auto_confirm=False,show=False,capture=False),label)
                top,e=await call('pt_query_topology',{},'topology')
                present=all(re.search(r'(?<![\w-])'+name+r'(?![\w-])',top) for name in ['Router0','Router1'])
                check('设备名称',(present,'要求Router0和Router1存在。'),e)
                if not present:raise ValueError('设备名称不匹配。')
                states={};files={}
                for i in [0,1]:
                    states[i],files[i]=await cli(f'Router{i}',['enable','show running-config','show ip interface brief','show ip bgp summary','show ip bgp','show ip route'],f'R{i}_BGP_state')
                for i,peer,local_as,remote_as,prefix,rid in [(0,'10.0.0.2',100,200,'20.0.0.0/24','10.1.0.1'),(1,'10.0.0.1',200,100,'10.1.0.0/24','20.0.0.1')]:
                    text=states[i];e=files[i]
                    check(f'R{i}本地AS与router-id',local_identity(text,local_as,rid),e)
                    check(f'R{i}eBGP邻居',(session_established(text,peer,remote_as),f'邻居{peer}为AS{remote_as}，State/PfxRcd应为已收前缀的数值。'),e)
                    check(f'R{i}BGP学习前缀',(bgp_path(text,prefix,peer,remote_as),f'BGP表应有{prefix}，下一跳{peer}，AS_PATH含对端AS{remote_as}。'),e)
                    check(f'R{i}实际BGP路由',(installed(text,prefix,peer),f'IP路由表应以B、AD20安装{prefix}，而不是依靠直连或静态路由。'),e)
                original=bool(re.search(r'^\s*network 10\.0\.0\.0 mask 255\.255\.255\.0\s*$',states[0],re.M))
                connected=bool(re.search(r'^\s*C\s+10\.0\.0\.0/24\s',states[1],re.M))
                check('原宣告与直连优先',(original and connected,'R0保留宣告10.0.0.0/24，R1对同一互联前缀保留C路由，不误判为BGP失败。'),files[0]+', '+files[1])
                report['original_link_prefix_seen_in_peer_bgp_table']=bgp_path(states[1],'10.0.0.0/24','10.0.0.1',100)
                for i,target,peer in [(0,'20.0.0.1','10.0.0.2'),(1,'10.1.0.1','10.0.0.1')]:
                    device=f'Router{i}'
                    await cli(device,['enable','ping '+target],f'R{i}_ping_warmup')
                    text,e=await cli(device,['enable','ping '+target],f'R{i}_ping')
                    check(f'R{i}到对端Loopback',ios_ping(text),e)
                    text,e=await cli(device,['enable','traceroute '+target],f'R{i}_trace')
                    check(f'R{i}对端路径',ios_trace(text,target,peer),e)
                report['status']='PASS' if all(c['passed'] for c in report['checks']) else 'FAIL'
    except Exception as exc:
        report['status']='ERROR';report['errors'].append(f'{type(exc).__name__}: {exc}')
        print('连接/采集错误：',type(exc).__name__,str(exc),flush=True)
    finally:
        report['finished']=datetime.now(timezone.utc).isoformat();save()
        lines=['# UC-09 自动验收','','状态：'+report['status'],'','|检查|结果|说明|','|---|---|---|']
        lines.extend(f"|{c['name']}|{'PASS' if c['passed'] else 'FAIL'}|{c['detail']}|" for c in report['checks'])
        lines+=['','保留原始互联前缀宣告，并增加AS100的10.1/24 Loopback，用于验证双端实际BGP路由安装。','同一10.0/24直连C优先，不伪称它在对端RIB一定显示B。','只读执行；错误：'+str(report['errors'])]
        (out/'summary.md').write_text('\n'.join(lines),encoding='utf-8')
    print('总结果：',report['status'],'；报告：',out/'acceptance_report.json')
    return 0 if report['status']=='PASS' else 1


def self_test():
    summary='10.0.0.2 4 200 10 10 3 0 0 00:00:25 1'
    assert session_established(summary,'10.0.0.2',200)
    assert not session_established(summary.replace('00:00:25 1','00:00:25 Idle'),'10.0.0.2',200)
    assert not session_established(summary,'10.0.0.2',100)
    assert bgp_path('*> 20.0.0.0/24 10.0.0.2 0 0 200 i','20.0.0.0/24','10.0.0.2',200)
    assert installed('B 20.0.0.0/24 [20/0] via 10.0.0.2, 00:00:10','20.0.0.0/24','10.0.0.2')
    assert not installed('C 20.0.0.0/24 is directly connected','20.0.0.0/24','10.0.0.2')
    assert ios_ping('Success rate is 100 percent (5/5)')[0]
    assert not ios_ping('Success rate is 80 percent (4/5)')[0]
    trace='Tracing the route to 20.0.0.1\n1 20.0.0.1 0 msec 0 msec 0 msec'
    assert ios_trace(trace,'20.0.0.1','10.0.0.2')[0]
    assert not ios_trace(trace.replace('1 20.0.0.1','1 *'),'20.0.0.1','10.0.0.2')[0]
    identity='router bgp 100\nBGP router identifier 10.1.0.1, local AS number 100\nBGP table version is 4, local router ID is 10.1.0.1'
    assert local_identity(identity,100,'10.1.0.1')[0]
    assert not local_identity(identity,200,'10.1.0.1')[0]
    assert not local_identity(identity.replace('identifier 10.1.0.1','identifier 10.9.0.1'),100,'10.1.0.1')[0]
    assert not local_identity(identity+'\n bgp router-id 10.9.0.1',100,'10.1.0.1')[0]
    assert not local_identity('router bgp 100',100,'10.1.0.1')[0]
    print('15项离线BGP/IOS解析检查通过；不是实际PT验收。')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--run-dir',type=Path,default=Path('runs/UC09_acceptance'));p.add_argument('--self-test',action='store_true')
    a=p.parse_args()
    if a.self_test:self_test()
    else:sys.exit(asyncio.run(run(a)))
