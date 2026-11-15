"""Read-only UC-08 three-stage failover acceptance. Fault switching is manual."""
import argparse
import asyncio
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import accept_uc01 as common


def route_present(text,code,prefix,next_hop,distance=None):
    metric=r'\[\d+/\d+\]' if distance is None else r'\['+str(distance)+r'/0\]'
    pattern=r'^\s*'+re.escape(code)+r'\s+'+re.escape(prefix)+r'\s+'+metric+r'\s+via\s+'+re.escape(next_hop)+r'(?:,|\s*$)'
    return re.search(pattern,text,re.M) is not None


def cfg_line(text,line):
    return re.search(r'^\s*'+re.escape(line)+r'\s*$',text,re.M) is not None


async def run(args):
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client
    out=args.run_dir/('acceptance_'+args.stage+'_'+datetime.now().strftime('%Y%m%d_%H%M%S_%f'));out.mkdir(parents=True)
    backup=args.stage=='backup'
    report=dict(case_id='UC-08',stage=args.stage,started=datetime.now(timezone.utc).isoformat(),status='RUNNING',checks=[],calls=[],errors=[],mode='live_read_only',fault='Router1 GigabitEthernet0/1 admin shutdown only in backup stage',scope='link-down floating defaults, not general remote-ISP outage/SLA monitoring')
    def save():
        (out/'acceptance_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    def check(name,ok,detail,evidence):
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
                        read={'enable','show running-config','show ip route','show ip interface brief','show ip ospf neighbor','show ip protocols'}
                        allowed=arguments.get('device') in {f'Router{i}' for i in range(5)} and all(c in read for c in arguments.get('commands',[]))
                    if name=='pt_host_command':
                        read={'ping 203.0.113.100','ping 10.1.0.10','tracert 203.0.113.100'}
                        allowed=arguments.get('device') in {'PC0','Server0'} and arguments.get('command') in read
                    if not allowed:raise ValueError('只读白名单拒绝调用。')
                    n=len(report['calls'])+1;record=dict(index=n,tool=name,arguments=arguments,label=label,status='RUNNING');report['calls'].append(record);save()
                    print(f'[{n}] {label} ...',flush=True)
                    result=await session.call_tool(name,arguments,read_timeout_seconds=timedelta(seconds=120))
                    file=f'{n:02}_{label}.json';text=common.result_text(result).replace('\r\n','\n')
                    (out/file).write_text(json.dumps(result.model_dump(mode='json'),ensure_ascii=False,indent=2),encoding='utf-8')
                    (out/f'{n:02}_{label}.txt').write_text(text,encoding='utf-8')
                    record.update(status='ERROR' if result.isError else 'RETURNED',evidence=file);save()
                    if result.isError or common.command_failed(text):raise ValueError('工具/命令错误：'+file)
                    return text,file
                async def cli(i):
                    commands=['enable','show running-config','show ip route','show ip interface brief']
                    if i<3:commands+=['show ip ospf neighbor','show ip protocols']
                    return await call('pt_cli',dict(device=f'Router{i}',commands=commands,timeout=30.0,auto_confirm=False,show=False,capture=False),f'R{i}_state')
                async def host(device,command,label):
                    return await call('pt_host_command',dict(device=device,command=command,timeout=45.0,show=False,capture=False),label)
                top,e=await call('pt_query_topology',{},'topology')
                names={f'Router{i}' for i in range(5)}|{'PC0','Server0','Switch0'}
                missing=[n for n in names if not re.search(r'(?<![\w-])'+re.escape(n)+r'(?![\w-])',top)]
                check('设备名称',not missing,'缺少'+str(missing) if missing else '已找到8个预期设备名称。',e)
                if missing:raise ValueError('设备显示名称不符。')
                texts={};files={}
                for i in range(5):texts[i],files[i]=await cli(i)
                r0=texts[0]
                primary_cfg=cfg_line(r0,'ip route 0.0.0.0 0.0.0.0 198.51.100.2') or cfg_line(r0,'ip route 0.0.0.0 0.0.0.0 198.51.100.2 1')
                secondary_cfg=cfg_line(r0,'ip route 0.0.0.0 0.0.0.0 198.51.100.6 10')
                check('主备默认路由配置',primary_cfg and secondary_cfg,'主AD1、备AD10，两条配置都保留。',files[0])
                hop='198.51.100.6' if backup else '198.51.100.2';ad=10 if backup else 1
                check('当前活动默认路由',route_present(r0,'S*','0.0.0.0/0',hop,ad),f'{args.stage}应为[{ad}/0] via {hop}。',files[0])
                oldhop='198.51.100.2' if backup else '198.51.100.6'
                check('非当前出口未占用默认路由',not route_present(r0,'S*','0.0.0.0/0',oldhop,1 if backup else 10),'不能只看配置，必须核对实际安装的默认路由。',files[0])
                primary_resolver=route_present(r0,'O','198.51.100.0/30','10.0.1.2')
                check('主下一跳解析路由',not primary_resolver if backup else primary_resolver,'主链路断开时OSPF应撤销主WAN前缀，正常及恢复时应存在。',files[0])
                check('备用下一跳解析路由',route_present(r0,'O','198.51.100.4/30','10.0.2.2'),'备用WAN前缀始终经R2可达。',files[0])
                for i,count,passive in [(0,2,'GigabitEthernet0/0'),(1,1,'GigabitEthernet0/1'),(2,1,'GigabitEthernet0/1')]:
                    protocol=bool(re.search(r'Routing Protocol is\s+"ospf 100"',texts[i],re.I))
                    full=len(re.findall(r'\bFULL/',texts[i]))
                    check(f'R{i}内部OSPF',protocol and full==count and cfg_line(texts[i],'passive-interface '+passive),f'要求OSPF100、{count}个FULL邻居及指定被动接口。',files[i])
                for i,hop in [(1,'10.0.1.1'),(2,'10.0.2.1')]:
                    check(f'R{i}总部返回路由',route_present(texts[i],'O','10.1.0.0/16',hop),'内部OSPF应学习总部/16。',files[i])
                status=r'administratively down\s+down' if backup else r'up\s+up'
                state=bool(re.search(r'^\s*GigabitEthernet0/1\s+198\.51\.100\.1\s+YES\s+\S+\s+'+status+r'\s*$',texts[1],re.M))
                check('主出口接口状态',state,'backup应administratively down/down，其他阶段up/up。',files[1])
                return_hop='203.0.113.2' if backup else '198.51.100.1';return_ad=10 if backup else 1
                check('ISP1总部返回路由',route_present(texts[3],'S','10.1.0.0/16',return_hop,return_ad),f'服务器网关应使用[{return_ad}/0] via {return_hop}返回总部。',files[3])
                check('ISP2总部返回路由',route_present(texts[4],'S','10.1.0.0/16','198.51.100.5',1),'ISP2应通过R2返回总部。',files[4])
                for device,target,label in [('PC0','203.0.113.100','PC_to_Server'),('Server0','10.1.0.10','Server_to_PC')]:
                    await host(device,'ping '+target,label+'_warmup')
                    text,e=await host(device,'ping '+target,label+'_ping')
                    ok,detail=common.ping_assert(text,target);check(label,ok,detail,e)
                expected=['10.1.0.254','10.0.2.2','198.51.100.6','203.0.113.100'] if backup else ['10.1.0.254','10.0.1.2','198.51.100.2','203.0.113.100']
                text,e=await host('PC0','tracert 203.0.113.100','PC_path')
                ok,detail=common.trace_assert(text,expected);check('出口路径',ok,detail,e)
                report['expected_path']=expected
                report['status']='PASS' if all(c['passed'] for c in report['checks']) else 'FAIL'
    except Exception as exc:
        report['status']='ERROR';report['errors'].append(f'{type(exc).__name__}: {exc}')
        print('连接/采集错误：',type(exc).__name__,str(exc),flush=True)
    finally:
        report['finished']=datetime.now(timezone.utc).isoformat();save()
        lines=['# UC-08 '+args.stage+' 验收','','状态：'+report['status'],'','|检查|结果|说明|','|---|---|---|']
        lines.extend(f"|{c['name']}|{'PASS' if c['passed'] else 'FAIL'}|{c['detail']}|" for c in report['checks'])
        lines+=['','只读执行；实际断开和恢复由用户在本地仿真手动完成，非Agent故障修复测试。','仅证明该主链路断开的切换，不证明远端ISP黑洞故障监测。','错误：'+str(report['errors'])]
        (out/'summary.md').write_text('\n'.join(lines),encoding='utf-8')
    print('总结果：',report['status'],'；报告：',out/'acceptance_report.json')
    return 0 if report['status']=='PASS' else 1


def self_test():
    line='S* 0.0.0.0/0 [10/0] via 198.51.100.6'
    assert route_present(line,'S*','0.0.0.0/0','198.51.100.6',10)
    assert not route_present(line,'S*','0.0.0.0/0','198.51.100.6',1)
    assert not route_present(line,'S*','0.0.0.0/0','198.51.100.2',10)
    assert route_present('O 198.51.100.0/30 [110/2] via 10.0.1.2, 00:00:12, GigabitEthernet0/1','O','198.51.100.0/30','10.0.1.2')
    print('4项离线主备路由解析检查通过；不是PT实际切换结果。')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--run-dir',type=Path,default=Path('runs/UC08_acceptance'))
    p.add_argument('--stage',choices=['primary','backup','restored']);p.add_argument('--self-test',action='store_true')
    a=p.parse_args()
    if a.self_test:self_test()
    elif not a.stage:p.error('必须指定primary、backup或restored阶段。')
    else:sys.exit(asyncio.run(run(a)))
