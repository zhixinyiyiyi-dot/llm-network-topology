"""Read-only live RIP phase evidence. Does not apply protocol configuration."""
import argparse, asyncio, json, re, sys, traceback
from pathlib import Path
from datetime import datetime,timezone,timedelta

class CollectionError(ValueError):pass

def result_text(r):
 s=getattr(r,'structuredContent',None)
 if isinstance(s,dict) and isinstance(s.get('result'),str):return s['result']
 parts=[]
 for b in getattr(r,'content',[]):
  if getattr(b,'type',None)!='text':continue
  text=b.text
  try:
   obj=json.loads(text)
   if isinstance(obj,dict) and isinstance(obj.get('result'),str):text=obj['result']
  except ValueError:pass
  parts.append(text)
 return '\n'.join(parts).replace('\r\n','\n')

def current(text,cmd):
 matches=list(re.finditer(r'(?m)^\s*(?:>\s*|[^\n#>]*[>#]\s*)'+re.escape(cmd)+r'\s*(?:\[(?:ok|ERROR|TIMEOUT)\])?[ \t]*$',text))
 if not matches:raise CollectionError('No command boundary: '+cmd)
 m=matches[-1];body=text[m.end():]
 if re.search('ERROR|TIMEOUT',m.group()) or re.search(r'\[TIMEOUT\]|aborted after|--More--|% Invalid|% Incomplete',body,re.I):raise CollectionError('Command failed or paginated: '+cmd)
 body=re.split(r'(?m)^\s*Final prompt:',body)[0].strip()
 marker={'show ip protocols':'Routing Protocol is','show ip route':'Codes:','show ip interface brief':'IP-Address'}.get(cmd,'Packets')
 if marker not in body:raise CollectionError('Missing result fields: '+cmd)
 return body

def ping_stats(text,target):
 stats=re.findall(r'Packets\s*:\s*Sent\s*=\s*(\d+)\s*,\s*Received\s*=\s*(\d+)\s*,\s*Lost\s*=\s*(\d+)',text,re.I)
 if len(stats)!=1:raise CollectionError('Missing/ambiguous ping summary')
 replies=len(re.findall(r'Reply from\s+'+re.escape(target)+r':[^\n]*\bTTL=\d+',text,re.I))
 return dict(sent=int(stats[0][0]),received=int(stats[0][1]),lost=int(stats[0][2]),echo_replies=replies,passed=stats[0]==('4','4','0') and replies==4)

async def run(args):
 from mcp import ClientSession
 from mcp.client.streamable_http import streamablehttp_client
 args.case_dir.mkdir(parents=True,exist_ok=True)
 out=args.case_dir/('rip_compare_'+args.phase+'_'+datetime.now().strftime('%Y%m%d_%H%M%S_%f'));out.mkdir()
 report=dict(case_id='COURSE-4-10',phase=args.phase,status='RUNNING',started=datetime.now(timezone.utc).isoformat(),calls=[],protocols={},routes={},pings=[],errors=[],configuration_writes=0,scope='Live evidence of requested phase; RIPv1 ping failure is an observation, not automatically an acceptance failure. Name/link checks do not prove every configuration line.')
 def save():(out/'comparison_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
 async def call(s,tool,params,label,cmd=None):
  n=len(report['calls'])+1;rec=dict(tool=tool,arguments=params,label=label);report['calls'].append(rec);save();print(f'[{n}] {label}',flush=True)
  r=await s.call_tool(tool,params,read_timeout_seconds=timedelta(seconds=100));text=result_text(r)
  file=f'{n:02}_{label}.txt';(out/file).write_text(text,encoding='utf-8');(out/file.replace('.txt','.json')).write_text(json.dumps(r.model_dump(mode='json'),ensure_ascii=False,indent=2),encoding='utf-8');rec['evidence']=file;save()
  if getattr(r,'isError',False):raise CollectionError('Tool error: '+file)
  if cmd=='enable':
   if not re.search(r'Final prompt:\s*[^\n]*#',text):raise CollectionError('No privileged prompt: '+file)
  elif cmd:
   text=current(text,cmd);(out/file.replace('.txt','_parsed.txt')).write_text(text,encoding='utf-8')
  return text
 print('RIP comparison collector v1 - READ ONLY - phase:',args.phase,flush=True);print('Evidence:',out.resolve(),flush=True);save()
 try:
  async with streamablehttp_client('http://127.0.0.1:39400/mcp') as streams:
   async with ClientSession(streams[0],streams[1]) as session:
    await session.initialize()
    top=await call(session,'pt_query_topology',{},'topology')
    expected={frozenset((a,ai,b,bi)) for a,ai,b,bi in []} # Exact endpoint pairs below.
    pairs=[(('PC0','FastEthernet0'),('Router0','GigabitEthernet0/0')),(('Router0','Serial0/0/0'),('Router1','Serial0/0/0')),(('Router1','Serial0/0/1'),('Router2','Serial0/0/0')),(('Router0','Serial0/0/1'),('Router2','Serial0/0/1')),(('Router2','GigabitEthernet0/0'),('PC1','FastEthernet0'))]
    expected={frozenset(p) for p in pairs}
    actual={frozenset(((a,ai),(b,bi))) for a,ai,b,bi in re.findall(r'^\s*(\S+):(\S+)\s+<--\[[^\]]+\]-->\s+(\S+):(\S+)\s*$',top,re.M)}
    if actual!=expected:raise CollectionError('Physical topology does not match the five expected links; stop without changing configuration')
    for dev in ['Router0','Router1','Router2']:
     for cmd,label in [('enable','enable'),('show ip interface brief','interfaces'),('show ip protocols','protocols'),('show ip route','routes')]:
      text=await call(session,'pt_cli',dict(device=dev,commands=[cmd],timeout=45.0,auto_confirm=False,show=False,capture=False),dev+'_'+label,cmd)
      if label=='protocols':
       header=bool(re.search(r'Routing Protocol is "rip"',text,re.I));v=re.search(r'Default version control:\s*send version\s+(\d+),\s*receive\s+([^\n]+)',text,re.I)
       want='2' if args.phase=='ripv2' else '1'
       info=dict(rip_present=header,send_version=v.group(1) if v else None,receive=v.group(2).strip() if v else None,phase_matches=header and bool(v) and v.group(1)==want)
       report['protocols'][dev]=info;print(dev,'protocol:',info,flush=True);save()
      if label=='routes':
       report['routes'][dev]=[line.strip() for line in text.splitlines() if re.match(r'^\s*R\s+',line)];save()
    if not all(x['phase_matches'] for x in report['protocols'].values()):raise CollectionError('Actual RIP send version differs from requested phase; evidence retained, do not relabel')
    for dev,target in [('PC0','192.168.16.130'),('PC1','192.168.16.10')]:
     cmd='ping '+target
     for warm in [True,False]:
      text=await call(session,'pt_host_command',dict(device=dev,command=cmd,timeout=45.0,show=False,capture=False),dev+('_warmup' if warm else '_ping'),cmd)
      if not warm:
       stats=ping_stats(text,target);report['pings'].append(dict(source=dev,destination=target,**stats));save();print(dev,'->',target,stats,flush=True)
    report['status']='EVIDENCE_COLLECTED'
    if args.phase=='ripv2' and not all(p['passed'] for p in report['pings']):report['status']='RIPV2_CONNECTIVITY_FAIL'
 except Exception as exc:
  def leaves(e):return [v for c in e.exceptions for v in leaves(c)] if getattr(e,'exceptions',None) else [type(e).__name__+': '+str(e)]
  report['status']='ERROR_COLLECTION';report['errors']=leaves(exc);(out/'error_details.txt').write_text(traceback.format_exc(),encoding='utf-8')
  for error in report['errors']:print('ERROR:',error,flush=True)
 finally:report['finished']=datetime.now(timezone.utc).isoformat();save()
 print('Result:',report['status'],'; report:',out/'comparison_report.json',flush=True)
 return 0 if report['status']=='EVIDENCE_COLLECTED' else 1

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--phase',choices=['ripv1','ripv2'],required=True);p.add_argument('--case-dir',type=Path,default=Path('runs/course_batch_20261115_125404_810573/COURSE-4-10'))
 try:sys.exit(asyncio.run(run(p.parse_args())))
 except Exception as e:print(type(e).__name__+': '+str(e));sys.exit(1)
