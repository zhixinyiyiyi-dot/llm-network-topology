"""Five course-derived LLM trials; no automatic device writes or fabricated deployment results."""
import argparse,csv,importlib.util,json,os,re,subprocess,sys
from pathlib import Path
from datetime import datetime,timezone
import yaml
ROOT=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('course_validator',ROOT/'uc01_validator/validate.py');validator=importlib.util.module_from_spec(spec);spec.loader.exec_module(validator)
def dump(path,obj):path.write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding='utf-8')
def main():
 from openai import OpenAI
 p=argparse.ArgumentParser();p.add_argument('--case',default='all',choices=['all','COURSE-4-5','COURSE-4-10','COURSE-4-11','COURSE-6-6','COURSE-7-1']);p.add_argument('--repair-batch',type=Path);args=p.parse_args()
 cases=json.loads((ROOT/'course_cases.json').read_text(encoding='utf-8'));schema=json.loads((ROOT/'uc01_validator/schema.json').read_text(encoding='utf-8'))
 key=os.environ.get('SILICONFLOW_API_KEY')
 if not key:raise ValueError('当前PowerShell未设置SILICONFLOW_API_KEY')
 client=OpenAI(api_key=key,base_url='https://api.siliconflow.cn/v1',timeout=180,max_retries=0)
 batch=ROOT.parent/'runs'/('course_batch_'+datetime.now().strftime('%Y%m%d_%H%M%S_%f'));batch.mkdir(parents=True)
 print('批次目录：',batch,flush=True)
 report=dict(started=datetime.now(timezone.utc).isoformat(),mode='generation_validation_compilation_only',stage='model_revision' if args.repair_batch else 'first_generation',parent_batch=str(args.repair_batch) if args.repair_batch else None,cases=[],deployment='PENDING',scope='五个课程来源；改编及与UC01/02重复范围明示，不重复凑独立需求数')
 def save():dump(batch/'batch_report.json',report)
 save()
 selected=list(cases) if args.case=='all' else [args.case]
 for cid in selected:
  out=batch/cid;out.mkdir();requirement=(ROOT/'requirements'/(cid+'.txt')).read_text(encoding='utf-8');(out/'requirements.txt').write_text(requirement,encoding='utf-8');dump(out/'source_manifest.json',{k:v for k,v in cases[cid].items() if k!='expected'})
  prompt='你是本地Packet Tracer网络规划助手。把自然语言需求转换为严格符合Schema的YAML，只输出YAML。所有设备name/type/interfaces/default_gateway/routing必填；非终端网关null。PC与server无路由时routing=[]。交换机接口ipv4=null，无VLAN时vlans=[]。RIP networks填有类主网络；OSPF按反掩码精确覆盖。静态路由不能遗漏远端或新增默认路由。ACL规则保持顺序，TCP目的端口用destination_port整数。services仅server允许，pages里是HTML字符串，禁止脚本外链。checks目标填IPv4而不是设备名，要求deny时明确expect:deny，其余按需求。不要输出CLI或答案说明。Schema：'+json.dumps(schema,ensure_ascii=False)
  prompt+=' 课程专用约定：绝对不要输出variant、ip_routing、nat；不适用的services/acls字段必须省略，不写null、不写全false空对象。只有server可写services。router默认IPv4转发无需ip_routing字段。expect省略等价allow；deny必须显式填写。'
  if args.repair_batch:
   old=args.repair_batch/cid
   if not old.is_dir():raise ValueError('修订源目录不存在：'+str(old))
   prior=(old/'raw_output.txt').read_text(encoding='utf-8-sig')
   feedback=(old/'validation_report.json').read_text(encoding='utf-8-sig')
   prompt+='\n这是后续修订，不是首轮。本次需求文本若声明原题映射纠正，以本次需求为准，不继承旧映射。其他内容按当前Schema和需求核对。不得擅改当前需求。\n原始输出：\n'+prior+'\n旧校验记录（其中默认allow导致的比较差异已修复；其他错误仍应核对）：\n'+feedback
   (out/'previous_raw_output.txt').write_text(prior,encoding='utf-8');(out/'previous_validation_report.json').write_text(feedback,encoding='utf-8')
  (out/'prompt.txt').write_text(prompt,encoding='utf-8');record=dict(case_id=cid,source=cases[cid]['source'],adaptation=cases[cid]['adaptation'],model_requests=1,generation_status='RUNNING',compile_status='NOT_RUN',runtime_status='PENDING',automatic_repair_rounds=None,manual_changes=False,is_first_output=not bool(args.repair_batch),original_first_output_status='FAIL' if args.repair_batch else None,errors=[]);report['cases'].append(record);save()
  print('\n'+cid+'：模型请求1次，最多等待180秒；不自动重试……',flush=True)
  try:
   r=client.chat.completions.create(model='deepseek-ai/DeepSeek-V3.2',messages=[dict(role='system',content=prompt),dict(role='user',content=requirement)],temperature=0,max_tokens=12288,extra_body={'enable_thinking':False})
   raw=r.choices[0].message.content or '';(out/'raw_output.txt').write_text(raw,encoding='utf-8');dump(out/'metadata.json',dict(model=r.model,id=r.id,finish_reason=r.choices[0].finish_reason,usage=r.usage.model_dump(mode='json') if r.usage else None))
   if r.choices[0].finish_reason!='stop':raise ValueError('模型输出截断，保留失败，不编译')
   text=raw.strip()
   if text.startswith('```'):
    m=re.fullmatch(r'```(?:yaml|yml)?\s*\n(.*?)\n```',text,re.S|re.I)
    if not m:raise ValueError('输出不是纯YAML或单个完整YAML围栏')
    text=m.group(1)
   data=yaml.load(text,Loader=validator.UniqueLoader);(out/'topology.yaml').write_text(yaml.safe_dump(data,allow_unicode=True,sort_keys=False),encoding='utf-8');errors=validator.validate(data,schema)
   if data.get('case_id')!=cid:errors.append(dict(code='REQUEST_ID',message='模型用例编号与请求不符'))
   record['errors']=errors;record['generation_status']='FAIL' if errors else 'PASS';dump(out/'validation_report.json',dict(passed=not errors,errors=errors,first_output=not bool(args.repair_batch),manual_changes=False))
   if not errors:
    built=subprocess.run([sys.executable,str(ROOT/'course_build.py'),str(out/'topology.yaml')],capture_output=True,text=True,encoding='utf-8',errors='replace',env={**os.environ,'PYTHONIOENCODING':'utf-8'})
    (out/'compile_console.txt').write_text(built.stdout+'\n'+built.stderr,encoding='utf-8');record['compile_status']='PASS' if built.returncode==0 else 'FAIL'
    print(built.stdout,flush=True)
    if built.returncode:record['errors'].append(dict(code='COMPILE',message=built.stderr or built.stdout))
  except Exception as exc:
   record['generation_status']='ERROR';record['errors'].append(dict(code='ERROR',message=type(exc).__name__+': '+str(exc)));dump(out/'validation_report.json',dict(passed=False,errors=record['errors'],first_output=not bool(args.repair_batch)))
  save();print(cid+'：本次生成='+record['generation_status']+'；编译='+record['compile_status']+'；实际部署=PENDING',flush=True)
  for error in record['errors']:print(error,flush=True)
 report['finished']=datetime.now(timezone.utc).isoformat();report['current_output_passed']=sum(c['generation_status']=='PASS' for c in report['cases']);report['generation_attempts']=len(report['cases']);report['current_output_rate']=report['current_output_passed']/len(report['cases']);report['first_generation_rate']=None if args.repair_batch else report['current_output_rate'];report['configuration_first_runtime_pass_rate']=None;report['repair_average_rounds']=None;save()
 with (batch/'evaluation.csv').open('w',encoding='utf-8-sig',newline='') as f:
  w=csv.writer(f);w.writerow(['case_id','generation_status','compile_status','runtime_status','automatic_repair_rounds']);w.writerows([c[k] for k in ['case_id','generation_status','compile_status','runtime_status','automatic_repair_rounds']] for c in report['cases'])
 print('\n生成阶段结束：'+str(report['current_output_passed'])+'/'+str(len(report['cases']))+'；尚未部署，不计算配置运行一次通过率或排障均值。',flush=True);print('报告：',batch/'batch_report.json',flush=True)
 return 0 if all(c['generation_status']=='PASS' and c['compile_status']=='PASS' for c in report['cases']) else 1
if __name__=='__main__':
 try:sys.exit(main())
 except Exception as e:print('已停止：'+type(e).__name__+': '+str(e));sys.exit(1)
