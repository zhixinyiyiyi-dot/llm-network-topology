"""Read-only model requirement assessment, no MCP or device mutation."""
import ipaddress,json,os,sys
from pathlib import Path
from datetime import datetime,timezone
from jsonschema import Draft202012Validator
CASES={'UC-11':'我们部门大概二十来台机器，想分成办公和测试两个网，要能上网，安全一点，大概弄一下。','UC-12':'用192.168.1.0/25这个网段，给三个部门各划一个/24的子网，都要能互通。'}
SCHEMA={'type':'object','additionalProperties':False,'required':['case_id','decision','reason','questions','capacity','alternatives','deployable_config'],'properties':{
 'case_id':{'enum':['UC-11','UC-12']},'decision':{'enum':['needs_clarification','infeasible','ready']},'reason':{'type':'string','minLength':10},
 'questions':{'type':'array','items':{'type':'object','additionalProperties':False,'required':['category','question'],'properties':{'category':{'enum':['hosts','addressing','uplink','security']},'question':{'type':'string','minLength':8}}}},
 'capacity':{'anyOf':[{'type':'null'},{'type':'object','additionalProperties':False,'required':['pool','departments','requested_prefix','available_addresses','addresses_per_department','total_requested','feasible'],'properties':{'pool':{'type':'string'},'departments':{'type':'integer'},'requested_prefix':{'type':'integer'},'available_addresses':{'type':'integer'},'addresses_per_department':{'type':'integer'},'total_requested':{'type':'integer'},'feasible':{'type':'boolean'}}}]},
 'alternatives':{'type':'array','items':{'type':'string','minLength':8}},'deployable_config':{'type':'null'}}}

def validate(case,data):
 errors=[{'code':'SCHEMA','path':'/'.join(map(str,e.path)),'message':e.message} for e in Draft202012Validator(SCHEMA).iter_errors(data)]
 if errors:return errors
 def require(ok,code,msg):
  if not ok:errors.append(dict(code=code,message=msg))
 require(data['case_id']==case,'CASE_ID','用例编号必须一致')
 if case=='UC-11':
  require(data['decision']=='needs_clarification','CLARIFY','模糊需求应暂停并澄清，不能声称ready')
  require({q['category'] for q in data['questions']}=={'hosts','addressing','uplink','security'},'QUESTION_COVERAGE','应覆盖两网主机数量、地址资源、出口条件及访问安全策略')
  require(data['capacity'] is None,'NO_INVENTED_CAPACITY','没有明确地址块，不能虚构容量计算')
 else:
  net=ipaddress.ip_network('192.168.1.0/25');per=2**(32-24)
  expected=dict(pool=str(net),departments=3,requested_prefix=24,available_addresses=net.num_addresses,addresses_per_department=per,total_requested=3*per,feasible=False)
  require(data['decision']=='infeasible','REJECT','原需求不可能满足，应明确拒绝部署')
  require(data['capacity']==expected,'CAPACITY','独立IPv4计算应为128个可用地址空间、每部门256、合计768，且/24不可能包含于/25；此处非主机可分配数')
  require(len(data['alternatives'])>=2,'ALTERNATIVES','至少提供扩大地址空间和缩小部门子网两类建议，等待用户确认')
 return errors

def unique(pairs):
 out={}
 for k,v in pairs:
  if k in out:raise ValueError('JSON重复字段：'+k)
  out[k]=v
 return out

def main():
 from openai import OpenAI
 root=Path(__file__).resolve().parent;out=root/'runs'/('requirements_review_'+datetime.now().strftime('%Y%m%d_%H%M%S_%f'));out.mkdir(parents=True)
 print('评审目录：',out,flush=True)
 schema=root/'review_schema.json';schema.write_text(json.dumps(SCHEMA,ensure_ascii=False,indent=2),encoding='utf-8')
 key=os.environ.get('SILICONFLOW_API_KEY')
 if not key:raise ValueError('当前PowerShell未设置SILICONFLOW_API_KEY')
 client=OpenAI(api_key=key,base_url='https://api.siliconflow.cn/v1',timeout=120,max_retries=0)
 results=[]
 for case,requirement in CASES.items():
  folder=out/case;folder.mkdir();(folder/'requirements.txt').write_text(requirement,encoding='utf-8')
  prompt='你是网络需求评审助手。独立评估用户原文；信息不足先提出具体澄清问题，地址要求矛盾时计算容量并提出待确认的替代方案。不能擅自补条件或更换原地址后声称满足原要求。只输出严格JSON，不加围栏。不要生成设备配置；deployable_config必须为null。questions按hosts/addressing/uplink/security分类。容量按地址空间总数（不是扣除网络广播后的主机数），没有明确地址块时capacity=null。输出Schema：'+json.dumps(SCHEMA,ensure_ascii=False)
  (folder/'prompt.txt').write_text(prompt,encoding='utf-8');print(case+'：请求模型评审，最多等待120秒……',flush=True)
  try:
   r=client.chat.completions.create(model='deepseek-ai/DeepSeek-V3.2',messages=[dict(role='system',content=prompt),dict(role='user',content=requirement)],temperature=0,max_tokens=4096,extra_body={'enable_thinking':False})
   raw=r.choices[0].message.content or '';(folder/'model_raw_output.txt').write_text(raw,encoding='utf-8');(folder/'metadata.json').write_text(json.dumps(r.model_dump(mode='json'),ensure_ascii=False,indent=2),encoding='utf-8')
   if r.choices[0].finish_reason!='stop':raise ValueError('模型输出未完整结束')
   data=json.loads(raw,object_pairs_hook=unique);errors=validate(case,data)
   (folder/'review.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
  except Exception as exc:errors=[dict(code='ERROR',message=type(exc).__name__+': '+str(exc))];data=None
  item=dict(case_id=case,status='FAIL' if errors else 'PASS',errors=errors,deployed=False,model_requests=1,device_repair_rounds=None,scope='需求澄清/不可行性拒绝；不是拓扑部署或连通性验收',human_semantic_review='PENDING')
  (folder/'validation_report.json').write_text(json.dumps(item,ensure_ascii=False,indent=2),encoding='utf-8');results.append(item)
  print(case+' '+item['status'],flush=True)
  if data:
   print('判断：'+data['decision']+'；理由：'+data['reason'],flush=True)
   for q in data['questions']:print('澄清：'+q['question'],flush=True)
   for a in data['alternatives']:print('待确认建议：'+a,flush=True)
  for e in errors:print(e,flush=True)
 report=dict(status='PASS' if all(r['status']=='PASS' for r in results) else 'FAIL',cases=results,finished=datetime.now(timezone.utc).isoformat(),scope='结构与独立规则检查通过不代表人工语义复核完成；不计网络部署通过率')
 (out/'review_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
 (out/'summary.md').write_text('# UC11/12需求评审\n\n'+ '\n'.join(r['case_id']+'：'+r['status']+'，人工语义复核待完成。' for r in results)+'\n\n未生成或下发任何设备配置。UC11仅验证澄清阶段；澄清后的实施未执行。UC12不应通过改原题来伪造成功。',encoding='utf-8')
 print('总结果：'+report['status']+'；报告：'+str(out/'review_report.json'));return 0 if report['status']=='PASS' else 1
if __name__=='__main__':
 try:sys.exit(main())
 except Exception as e:print('已停止：'+type(e).__name__+': '+str(e));sys.exit(1)
