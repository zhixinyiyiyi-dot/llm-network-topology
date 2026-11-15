"""Read-only state and selected ping acceptance for generated course DSL."""
import argparse,asyncio,importlib.util,ipaddress as ip,json,re,sys
from datetime import datetime,timedelta,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT.parent))
import accept_uc01 as common
spec=importlib.util.spec_from_file_location('cv',ROOT/'uc01_validator/validate.py');cv=importlib.util.module_from_spec(spec);spec.loader.exec_module(cv)
import yaml

def display(name):return 'Router'+name[1:] if re.fullmatch(r'R\d+',name) else name
def line(text,want):return re.search(r'^\s*'+re.escape(want)+r'\s*$',text,re.M|re.I) is not None
def section(text,header):
 m=re.search(r'^'+re.escape(header)+r'\s*\n((?:[ \t][^\n]*\n|!\n)*)',text,re.M|re.I)
 return m.group(1) if m else ''
def linkset(text):
 return {frozenset(((a,ai),(b,bi))) for a,ai,b,bi in re.findall(r'^\s*(\S+):(\S+)\s+<--\[[^\]]+\]-->\s+(\S+):(\S+)\s*$',text,re.M)}
def pc_params(text,addr,gateway):
 # Supports the standard Packet Tracer English ipconfig form.
 found=re.search(r'IPv4 Address[^\n]*?:\s*([0-9.]+)',text,re.I)
 mask=re.search(r'Subnet Mask[^\n]*?:\s*([0-9.]+)',text,re.I)
 gateways=re.search(r'Default Gateway[^\n]*?:\s*([^\n]+)(?:\n\s+([0-9.]+))?',text,re.I)
 values=[] if not gateways else re.findall(r'\b(?:\d{1,3}\.){3}\d{1,3}\b',gateways.group(0))
 return bool(found and mask and found.group(1)==str(addr.ip) and mask.group(1)==str(addr.netmask) and (gateway in values if gateway else not values or set(values)=={'0.0.0.0'}))

def route_config(dev,text):
 missing=[]
 for r in dev['routing']:
  if r['protocol']=='static':
   for entry in r['routes']:
    n=ip.ip_network(entry['prefix']);want=f'ip route {n.network_address} {n.netmask} {entry["next_hop"]}'
    if not line(text,want):missing.append(want)
  elif r['protocol']=='rip':
   block=section(text,'router rip')
   for want in ['version 2','no auto-summary']+['network '+n for n in r['networks']]:
    if not line(block,want):missing.append(want)
   if not re.search(r'send version 2, receive 2',text,re.I):missing.append('实际协议send2/receive2')
  else:
   block=section(text,'router ospf '+str(r['process_id']))
   for e in r['networks']:
    want=f'network {e["network"]} {e["wildcard"]} area {e["area"]}'
    if not line(block,want):missing.append(want)
 return missing

class CollectionError(ValueError):pass

def fresh_output(text, command):
 # Last command echo is the only accepted boundary; raw history is retained separately.
 pattern=r'(?m)^\s*(?:>\s*|[^\n#>]*[>#]\s*)'+re.escape(command)+r'\s*(?:\[(?:ok|TIMEOUT|ERROR)\])?\s*$'
 matches=list(re.finditer(pattern,text))
 if not matches:raise CollectionError('缺少本次命令边界：'+command)
 boundary=matches[-1]; header=boundary.group(0)
 body=text[boundary.end():].strip()
 if re.search(r'TIMEOUT|ERROR',header) or re.search(r'\[TIMEOUT\]|aborted after|--More--|% Invalid|% Incomplete|% Ambiguous',body,re.I):
  raise CollectionError('本次命令超时、分页或执行失败：'+command)
 body=re.split(r'(?m)^\s*Final prompt:',body)[0]
 body=re.sub(r'(?m)^\s*[^\n#>]*[>#]\s*$','',body).strip()
 if not body:raise CollectionError('本次命令输出为空：'+command)
 required={'show ip interface brief':r'Interface\s+IP-Address','show ip route':r'Gateway of last resort|Codes:', 'show ip protocols':r'Routing Protocol is|not configured','ipconfig':r'IPv4 Address','show access-lists':r'access list'}
 if command.startswith('ping '):marker=r'Packets\s*:'
 else:marker=required.get(command, r'(?:Inbound|Outgoing)\s+access\s+list\s+is')
 if not re.search(marker,body,re.I):raise CollectionError('本次命令缺少完整结果：'+command)
 return body

def ping_result(text,target,deny=False):
 stats=re.findall(r'Packets\s*:\s*Sent\s*=\s*(\d+)\s*,\s*Received\s*=\s*(\d+)\s*,\s*Lost\s*=\s*(\d+)',text,re.I)
 if len(stats)!=1:raise CollectionError('ping统计缺失或混入多次结果')
 replies=re.findall(r'Reply from\s+'+re.escape(target)+r':[^\n]*\bTTL=\d+',text,re.I)
 expected=('4','0','4') if deny else ('4','4','0')
 return stats[0]==expected and (not replies if deny else len(replies)==4), '实际发送/收到/丢失='+str(stats[0])+('；预期拒绝（仅证明探测未成功）' if deny else '；要求4/4、0丢包')

async def run(args):
 from mcp import ClientSession
 from mcp.client.streamable_http import streamablehttp_client
 d=yaml.load((args.case_dir/'topology.yaml').read_text(encoding='utf-8-sig'),Loader=cv.UniqueLoader);errors=cv.validate(d,json.loads((ROOT/'uc01_validator/schema.json').read_text(encoding='utf-8')))
 if errors:raise ValueError('目标YAML未通过独立校验：'+str(errors))
 out=args.case_dir/(('preflight_' if args.preflight else 'runtime_')+datetime.now().strftime('%Y%m%d_%H%M%S_%f'));out.mkdir()
 report=dict(case_id=d['case_id'],mode='preflight_read_only' if args.preflight else 'live_read_only',started=datetime.now(timezone.utc).isoformat(),status='RUNNING',checks=[],calls=[],errors=[],deployed_by_this_script=False,first_runtime_pass_claim='PENDING_HUMAN_DEPLOYMENT_HISTORY')
 def save(): (out/'runtime_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
 def check(name,ok,detail,evidence):report['checks'].append(dict(name=name,passed=bool(ok),detail=detail,evidence=evidence));save();print(('MATCH ' if ok else 'MISMATCH ')+name+'：'+detail,flush=True)
 print('版本：短命令隔离采集 v5（只读，ACL空格兼容）',flush=True);print('记录目录：',out,flush=True);save()
 names={display(x['name']) for x in d['devices']}
 try:
  async with streamablehttp_client('http://127.0.0.1:39400/mcp') as streams:
   async with ClientSession(streams[0],streams[1]) as session:
    await session.initialize()
    async def call(tool,params,label):
     allowed=tool=='pt_query_topology' and params=={}
     if tool=='pt_cli':allowed=params.get('device') in names and all(x in ['enable','show ip interface brief','show ip protocols','show ip route','show access-lists'] or x in ['show ip interface '+it['name'] for dev in d['devices'] for it in dev['interfaces']] for x in params.get('commands',[]))
     if tool=='pt_host_command':allowed=params.get('device') in names and (params.get('command')=='ipconfig' or any(params.get('device')==display(c['source']) and params.get('command')=='ping '+c['destination'] for c in d['checks']))
     if not allowed:raise ValueError('只读白名单拒绝')
     n=len(report['calls'])+1;print(f'[{n}] {label}',flush=True);rec=dict(tool=tool,arguments=params,label=label);report['calls'].append(rec);save()
     result=await session.call_tool(tool,params,read_timeout_seconds=timedelta(seconds=120));text=common.result_text(result).replace('\r\n','\n');file=f'{n:02}_{label}.txt';(out/file).write_text(text,encoding='utf-8');(out/file.replace('.txt','.json')).write_text(json.dumps(result.model_dump(mode='json'),ensure_ascii=False,indent=2),encoding='utf-8');rec['evidence']=file;save()
     if result.isError:raise CollectionError('工具错误：'+file)
     if tool=='pt_cli' and params.get('commands')==['enable']:
      if re.search(r'\[TIMEOUT\]|\[ERROR\]|aborted after',text,re.I) or not re.search(r'Final prompt:\s*[^\n]*#',text):raise CollectionError('未确认进入特权模式：'+file)
     elif tool in ['pt_cli','pt_host_command']:
      text=fresh_output(text,params['commands'][0] if tool=='pt_cli' else params['command'])
      (out/file.replace('.txt','_parsed.txt')).write_text(text,encoding='utf-8')
     return text,file
    privileged=set()
    async def cli(name,cmds,label):
     if name not in privileged:
      await call('pt_cli',dict(device=display(name),commands=['enable'],timeout=45.0,auto_confirm=False,show=False,capture=False),name+'_enable')
      privileged.add(name)
     return await call('pt_cli',dict(device=display(name),commands=cmds,timeout=45.0,auto_confirm=False,show=False,capture=False),label)
    async def host(name,cmd,label):return await call('pt_host_command',dict(device=display(name),command=cmd,timeout=45.0,show=False,capture=False),label)
    t,e=await call('pt_query_topology',{},'topology')
    if not all(re.search(r'(?<![\w-])'+re.escape(n)+r'(?![\w-])',t) for n in names):raise ValueError('设备名不齐：请确认打开了对应课程pkt')
    expected={frozenset((display(l[k]['device']),l[k]['interface']) for k in ['a','b']) for l in d['links']}
    toplevel=t;top_evidence=e
    got=linkset(t);check('完整物理接线',got==expected,f'预期{len(expected)}条，实际识别{len(got)}条；缺失{[list(x) for x in expected-got]}；多余{[list(x) for x in got-expected]}',e)
    for dev in d['devices']:
     name=dev['name']
     if dev['type'] in ['pc','server']:
      t,e=await host(name,'ipconfig',name+'_ipconfig');addr=ip.ip_interface(dev['interfaces'][0]['ipv4']);check(name+'地址/掩码/网关',pc_params(t,addr,dev['default_gateway']),'需与本轮YAML一致',e)
     elif dev['type']=='router':
      row=re.search(r'^\s*'+re.escape(display(name))+r'\s+\[[^\n]+',toplevel,re.M)
      missing=[]
      for it in dev['interfaces']:
       addr=ip.ip_interface(it['ipv4']);token=it['name']+'='+str(addr.ip)+'/'+str(addr.netmask)
       if not row or token not in row.group(0):missing.append(token)
      check(name+'实际接口地址/掩码',not missing,str(missing),top_evidence)
      t,e=await cli(name,['show ip interface brief'],name+'_interfaces')
      missing=[it['name'] for it in dev['interfaces'] if not re.search(r'^\s*'+re.escape(it['name'])+r'\s+'+re.escape(str(ip.ip_interface(it['ipv4']).ip))+r'\s+.*?\bup\s+up\s*$',t,re.M)]
      check(name+'接口up/up',not missing,str(missing),e)
      for routing in dev['routing']:
       if routing['protocol']=='static':
        t,e=await cli(name,['show ip route'],name+'_routes');missing=[]
        for entry in routing['routes']:
         prefix=str(ip.ip_network(entry['prefix']))
         if not re.search(r'^\s*S\s+'+re.escape(prefix)+r'\s+.*?via\s+'+re.escape(entry['next_hop'])+r'(?:\s|,|$)',t,re.M):missing.append(entry)
        check(name+'已安装静态路由',not missing,str(missing),e)
       else:
        t,e=await cli(name,['show ip protocols'],name+'_protocols');missing=[]
        if routing['protocol']=='ospf':
         if not re.search(r'Routing Protocol is "ospf '+str(routing['process_id'])+r'"',t):missing.append('OSPF进程')
         for n in routing['networks']:
          if not re.search(r'^\s*'+re.escape(n['network'])+r'\s+'+re.escape(n['wildcard'])+r'\s+area\s+'+str(n['area'])+r'\s*$',t,re.M):missing.append(n)
        else:
         if not re.search(r'send version 2, receive 2',t,re.I):missing.append('RIPv2发送/接收')
         if not re.search(r'[Aa]utomatic network summarization is not in effect',t):missing.append('禁用自动汇总')
         for n in routing['networks']:
          if not line(t,n):missing.append(n)
        check(name+'实际路由协议声明',not missing,str(missing),e)
      for acl in dev.get('acls',[]):
       t,e=await cli(name,['show access-lists'],name+'_acl')
       # Parse headers and rule lines explicitly; IOS alignment uses variable whitespace.
       block_lines=[];active=False
       for acl_line in t.splitlines():
        header=re.match(r'^\s*(?:Extended IP access list|ip access-list extended)\s+(\S+)\s*$',acl_line,re.I)
        if header:
         active=header.group(1)==str(acl['name']);continue
        if active and re.match(r'^\s*(?:\d+\s+)?(?:permit|deny)\s+',acl_line,re.I):block_lines.append(acl_line)
       block='\n'.join(block_lines)
       def address(v):
        if v=='any':return 'any'
        net=ip.ip_network(v);return str(net.network_address)+' '+str(net.hostmask)
       expected_rules=[]
       for rule in acl['rules']:
        ruletext=rule['action']+' '+rule['protocol']+' '+address(rule['source'])+' '+address(rule['destination'])
        if 'destination_port' in rule:ruletext+=' eq '+str(rule['destination_port'])
        expected_rules.append(ruletext)
       normalized=block.replace('eq www','eq 80').replace('eq ftp-data','eq 20').replace('eq ftp','eq 21')
       normalized=re.sub(r'host\s+([0-9.]+)',r'\1 0.0.0.0',normalized)
       actual=[re.sub(r'\s*\(\d+ match(?:es)?\)','',re.sub(r'^\s*\d+\s+','',x)).strip() for x in normalized.splitlines() if re.search(r'\b(?:permit|deny)\b',x)]
       check(name+'ACL有序规则',actual==expected_rules,'实际='+str(actual)+'；预期='+str(expected_rules),e)
       t,e=await cli(name,['show ip interface '+acl['interface']],name+'_acl_binding')
       direction='Inbound' if acl['direction']=='in' else 'Outgoing'
       check(name+'ACL接口绑定',bool(re.search(direction+r'\s+access\s+list\s+is\s+'+re.escape(str(acl['name']))+r'\s*$',t,re.M|re.I)),acl['interface']+' '+acl['direction'],e)
    if not args.preflight:
     for i,c in enumerate(d['checks']):
      await host(c['source'],'ping '+c['destination'],f'ping_{i}_warmup');t,e=await host(c['source'],'ping '+c['destination'],f'ping_{i}')
      ok,detail=ping_result(t,c['destination'],c.get('expect','allow')=='deny')
      check(c['source']+'到'+c['destination'],ok,detail,e)
    report['status']='MATCH' if all(x['passed'] for x in report['checks']) else 'MISMATCH'
    if not args.preflight and report['status']=='MATCH':report['status']='PASS_NETWORK_CHECKS'
    report['application_evidence']='REQUIRES_MANUAL_HTTP_FTP_EVIDENCE' if any(x.get('services') for x in d['devices']) else 'NOT_APPLICABLE'
 except Exception as exc:
  import traceback
  def leaves(x):return [item for child in x.exceptions for item in leaves(child)] if getattr(x,'exceptions',None) else [type(x).__name__+': '+str(x)]
  report['status']='ERROR_COLLECTION';report['errors']=leaves(exc)
  (out/'error_details.txt').write_text(traceback.format_exc(),encoding='utf-8')
  for detail in report['errors']:print('内部原因：',detail,flush=True)
 finally:report['finished']=datetime.now(timezone.utc).isoformat();save()
 print('结果：',report['status'],'；报告：',out/'runtime_report.json',flush=True);return 0 if report['status'] in ['MATCH','PASS_NETWORK_CHECKS'] else 1
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--case-dir',type=Path,required=True);p.add_argument('--preflight',action='store_true');a=p.parse_args()
 try:sys.exit(asyncio.run(run(a)))
 except Exception as exc:print('已停止：'+type(exc).__name__+': '+str(exc));sys.exit(1)
