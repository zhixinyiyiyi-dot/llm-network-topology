"""Correct an assistant-authored requirement mapping; never changes PT or old outputs."""
import copy,json,re,sys
from pathlib import Path
from datetime import datetime
root=Path(__file__).resolve().parent/'course_eval'
p=root/'course_cases.json';cases=json.loads(p.read_text(encoding='utf-8'))
if cases['COURSE-4-5'].get('mapping_revision')=='original_topology_v2':
 print('映射已修正，无需重复执行。');sys.exit(0)
backup=root/('mapping_backup_'+datetime.now().strftime('%Y%m%d_%H%M%S'));backup.mkdir()
for f in [p,root/'requirements/COURSE-4-5.txt',root/'course_eval.py']:(backup/f.name).write_bytes(f.read_bytes())
d=cases['COURSE-4-5']['expected'];rename={'PC1':'PC2','PC2':'PC1','PC5':'PC6','PC6':'PC5'}
for dev in d['devices']:dev['name']=rename.get(dev['name'],dev['name'])
for link in d['links']:
 for end in ['a','b']:
  e=link[end];e['device']=rename.get(e['device'],e['device'])
  if e['device']=='Switch3':e['interface']={'FastEthernet0/1':'FastEthernet0/2','FastEthernet0/2':'FastEthernet0/3','FastEthernet0/3':'FastEthernet0/1'}[e['interface']]
for c in d['checks']:c['source']=rename.get(c['source'],c['source'])
cases['COURSE-4-5']['mapping_revision']='original_topology_v2'
cases['COURSE-4-5']['adaptation']='按用户实际原题拓扑纠正PC1/PC2和PC5/PC6映射及Switch3端口；旧需求由助手整理错误，不归因模型。沿用原CIDR第一方案，第二编址方案未覆盖。'
p.write_text(json.dumps(cases,ensure_ascii=False,indent=2),encoding='utf-8')
lines=['课内来源：实验4-5 IPv4无分类编址。','本次需求是经用户原拓扑确认后的纠正版。此前助手把主机编号与Switch3端口整理错了。若旧输出与本次需求冲突，以本次需求为准；记录为需求版本修订，非模型自动排障。','case_id=COURSE-4-5，status=ready，questions=[]，vlans=[]。不使用NAT/VLAN/服务或动态路由。没有ACL/services的设备省略这些字段。']
for dev in d['devices']:
 lines.append('设备'+dev['name']+'，类型'+dev['type']+'，接口：'+'；'.join(i['name']+'='+str(i['ipv4']) for i in dev['interfaces'])+'；网关='+str(dev['default_gateway'])+'。')
 if not dev['routing']:lines.append('该设备routing=[]。')
 for r in dev['routing']:lines.append('静态路由：'+'；'.join(x['prefix']+' 经 '+x['next_hop'] for x in r['routes']))
lines.append('物理接线（所有dce=null）：'+'；'.join(l['a']['device']+' '+l['a']['interface']+'—'+l['b']['device']+' '+l['b']['interface'] for l in d['links']))
lines.append('checks仅包含以下ping，目标用IPv4，均expect allow：'+'；'.join(x['source']+' 到 '+x['destination'] for x in d['checks']))
(root/'requirements/COURSE-4-5.txt').write_text('\n'.join(lines),encoding='utf-8')
f=root/'course_eval.py';t=f.read_text(encoding='utf-8');t=t.replace("这是后续修订，不是首轮。根据本次收窄Schema与原需求修订，保留正确拓扑/地址/协议/有序ACL，移除不适用字段。不得改变原需求。","这是后续修订，不是首轮。本次需求文本若声明原题映射纠正，以本次需求为准，不继承旧映射。其他内容按当前Schema和需求核对。不得擅改当前需求。")
f.write_text(t,encoding='utf-8')
print('已纠正4-5需求映射；原配置、原批次与PT未修改。备份：',backup)
print('下一步仅重新生成4-5：')
print(r'.\.venv\Scripts\python.exe .\course_eval\course_eval.py --case COURSE-4-5 --repair-batch .\runs\course_batch_20261115_125404_810573')
