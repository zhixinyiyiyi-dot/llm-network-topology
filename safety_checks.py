"""Offline checks of project guards/validator; no MCP, API calls, or device writes."""
import copy,importlib.util,json,sys
from datetime import datetime,timezone
from pathlib import Path
import yaml
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT))
import build_configs as compiler
import repair_uc01 as repair
spec=importlib.util.spec_from_file_location('validator_under_test',ROOT/'uc01_validator/validate.py');validator=importlib.util.module_from_spec(spec);spec.loader.exec_module(validator)
schema=json.loads((ROOT/'uc01_validator/schema.json').read_text(encoding='utf-8'))
out=ROOT/'runs'/('safety_checks_'+datetime.now().strftime('%Y%m%d_%H%M%S_%f'));out.mkdir(parents=True)
report=dict(mode='offline_guard_and_validator_tests',started=datetime.now(timezone.utc).isoformat(),tests=[],device_writes=0,api_calls=0,scope='真实调用现有编译器guard、DSL校验器及修复计划护栏；不是完整IOS语法分析器、Batfish或正式设备排障')
def record(name,ok,detail):
 report['tests'].append(dict(name=name,passed=bool(ok),detail=detail));print(('PASS ' if ok else 'FAIL ')+name+'：'+detail,flush=True)
def blocked(name,command):
 try:compiler.guard([command]);record(name,False,'危险/未知命令未拒绝')
 except ValueError as e:record(name,True,'ALERT_BLOCKED '+str(e))
print('离线安全检查：不会连接或修改PT',flush=True)
try:compiler.guard(['enable','configure terminal','interface GigabitEthernet0/0','no shutdown','end']);record('合法模板正例',True,'合法模板允许，仅离线检查')
except Exception as e:record('合法模板正例',False,str(e))
for name,cmd in [('黑名单reload','reload'),('黑名单write erase','write erase'),('黑名单format','format flash:'),('未知CLI白名单','show version'),('不完整IP命令','ip address 192.168.1.1'),('命令拼接','no shutdown; reload')]:blocked(name,cmd)
expected=yaml.load((ROOT/'runs/20261114_172847_213246/topology.fixed.yaml').read_text(encoding='utf-8-sig'),Loader=validator.UniqueLoader)
record('正确DSL正例',not validator.validate(expected,schema),'现有UC01修正后目标应合法')
for name,kind in [('非法地址/掩码','mask'),('错误终端网关','gateway'),('非法重叠地址','duplicate')]:
 d=copy.deepcopy(expected)
 if kind=='mask':d['devices'][0]['interfaces'][0]['ipv4']='192.168.16.126/255.255.255.1'
 elif kind=='gateway':next(x for x in d['devices'] if x['type']=='pc')['default_gateway']='203.0.113.254'
 else:
  ips=[i for x in d['devices'] for i in x['interfaces'] if i['ipv4']];ips[1]['ipv4']=ips[0]['ipv4']
 try:errors=validator.validate(d,schema);record(name,bool(errors),'拦截代码：'+str([e['code'] for e in errors]))
 except Exception as e:record(name,False,'校验器异常而非结构化拒绝：'+str(e))
vlan=ROOT/'runs/20261115_004629_787997/topology.fixed.yaml'
if vlan.exists():
 d=yaml.load(vlan.read_text(encoding='utf-8-sig'),Loader=validator.UniqueLoader)
 next(i for x in d['devices'] if x['type']=='switch' for i in x['interfaces'] if i.get('access_vlan')==10)['access_vlan']=20
 errors=validator.validate(d,schema);record('网关/VLAN一致性',bool(errors),'拦截代码：'+str([e['code'] for e in errors]))
else:record('网关/VLAN一致性',False,'缺少本地VLAN目标文件，未测试')
action=dict(device='R2',kind='enable_interface',interface='GigabitEthernet0/0')
def plan(a):return dict(diagnosis='离线测试',evidence=['离线受控输入'],actions=[a])
for name,bad in [('越界接口',dict(action,interface='GigabitEthernet0/9')),('未知修复动作',dict(action,kind='reload')),('额外任意命令',dict(action,command='write erase'))]:
 try:repair.build_plan(plan(bad),expected,{});record(name,False,'未拒绝')
 except ValueError as e:record(name,True,str(e))
report['status']='PASS' if all(t['passed'] for t in report['tests']) else 'FAIL';report['finished']=datetime.now(timezone.utc).isoformat()
(out/'safety_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
(out/'summary.md').write_text('# 离线安全检查\n\n状态：'+report['status']+'\n\n'+'\n'.join('- '+t['name']+'：'+('PASS' if t['passed'] else 'FAIL')+'；'+t['detail'] for t in report['tests'])+'\n\n无设备写入；不冒充线上危险命令下发、CONFIRM门实测、Batfish或盲测。',encoding='utf-8')
print('总结果：',report['status'],'；报告：',out/'safety_report.json')
sys.exit(0 if report['status']=='PASS' else 1)
