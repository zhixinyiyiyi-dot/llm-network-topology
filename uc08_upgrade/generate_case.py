"""Schema-driven generation for local Packet Tracer cases; no device writes."""
import argparse
import importlib.util
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

import yaml
from openai import OpenAI


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--requirements',type=Path,required=True)
    parser.add_argument('--case',choices=['UC-04','UC-05','UC-06','UC-07','UC-08'],default='UC-04')
    args=parser.parse_args()
    root=Path(__file__).resolve().parent
    spec=importlib.util.spec_from_file_location('validator',root/'uc01_validator/validate.py')
    validator=importlib.util.module_from_spec(spec);spec.loader.exec_module(validator)
    schema=json.loads((root/'uc01_validator/schema.json').read_text(encoding='utf-8'))
    requirement=args.requirements.read_text(encoding='utf-8-sig')
    key=os.environ.get('SILICONFLOW_API_KEY')
    if not key:raise ValueError('当前PowerShell未设置SILICONFLOW_API_KEY。')
    out=root/'runs'/datetime.now().strftime('%Y%m%d_%H%M%S_%f');out.mkdir(parents=True)
    prompt='''你是本地Packet Tracer网络规划助手。将需求转成符合Schema的YAML，不加代码围栏。
必须准确保留需求指定的设备类型、名称、接口、接线、IP/前缀、网关。
需要澄清时status=needs_clarification并列questions；正常时status=ready，questions=[]。
设备字段name/type/interfaces/default_gateway/routing都必须出现。没有路由的终端routing=[]。
静态路由用routing:[{protocol: static, routes:[{prefix: CIDR, next_hop: IPv4}]}。
ISP路由器routing为[{protocol: static, routes: []}]，只用直连路由，不增加私网返回路由。
交换机type=switch，端口ipv4=null，default_gateway=null，routing=[]。服务器type=server。
NAT只在内网出口路由器的nat对象描述，严格按Schema，不放到其他设备。
配置文件分阶段部署由后续程序控制，目标YAML必须包含最终NAPT意图。
links包含两端设备和接口，所有非串行链路dce=null。vlans=[]。
checks使用需求指定的两个PC到Server0的ping。
Schema：\n'''+json.dumps(schema,ensure_ascii=False)
    if args.case=='UC-05':
        prompt='''你是本地Packet Tracer VLAN规划助手。将需求转为符合Schema的YAML，不加代码围栏。
case_id=UC-05，variant为router_on_a_stick或svi。正常status=ready、questions=[]。
所有设备都含name/type/interfaces/default_gateway/routing；本用例所有routing=[]，不需要静态或动态路由。
PC接口仅name和ipv4两个字段，网关写default_gateway。PC不添加vlan_id等字段。
vlans为[{id:10,name:FINANCE},{id:20,name:MARKETING}]。
交换机access接口含name/ipv4:null/switchport_mode:access/access_vlan。
Trunk含name/ipv4:null/switchport_mode:trunk/allowed_vlans:[10,20]，不含access_vlan。
单臂方案R0物理父接口ipv4:null，子接口另列，含name/ipv4/encapsulation_vlan。
SVI方案仅有type=multilayer_switch的Switch0、ip_routing:true和6台PC，SVI接口含name:Vlan10或Vlan20/ipv4/vlan_id。不使用路由器。
只有物理接口列在links中，子接口和SVI不能写物理链路。dce全null。没有nat。
checks必须列出6台PC全部30个有向两两ping，不含自己，不漏项。
严格按需求逐个接口地址，不能新增设备或交换端口。Schema：'''+json.dumps(schema,ensure_ascii=False)
    if args.case=='UC-06':
        prompt='''你是本地Packet Tracer规划助手。严格按需求生成符合Schema的YAML，不加代码围栏。
case_id=UC-06，status=ready，questions=[]，不添加variant。
只用PC0/PC1（type=pc）和Switch0（type=switch）。所有设备default_gateway:null、routing:[]。
PC接口只有name和ipv4；交换机接口只有name和ipv4:null，不添加switchport/VLAN字段。
vlans=[]，不划分VLAN，默认VLAN1即可，不使用路由器、nat或其他服务。
checks.destination必须是IPv4字符串，不能填设备名。精确使用以下两项：
- {type: ping, source: PC0, destination: 192.168.1.2}
- {type: ping, source: PC1, destination: 192.168.1.1}
所有links的dce为null；按需求准确接线。Schema：'''+json.dumps(schema,ensure_ascii=False)
    if args.case=='UC-07':
        prompt='''你是仅针对本地Packet Tracer的网络规划助手。按需求输出符合Schema的YAML，不加代码围栏。
case_id=UC-07，status=ready、questions=[]。不要添加variant字段。
设备name/type/interfaces/default_gateway/routing均必填；无网关用null，终端和交换机routing=[]。
路由器静态路由用protocol:static和routes列表；ISP routes=[]只保留直连。
VLAN30/40的子接口含encapsulation_vlan、父接口ipv4:null；交换端口用access或trunk字段。
R0 nat使用inside_interfaces和source_networks两个列表，不能混用旧的单接口字段。
R0 acls列表用name/interface/direction/rules，严格按需求顺序保留echo-reply、established、deny、permit。
checks.destination必须是IPv4字符串而不是设备名；expect字段allow或deny表达实际预期。
其他设备不能配置nat/acls；PC接口仅name/ipv4，不加VLAN字段。所有非终端default_gateway:null。
只描述目标，不在YAML里添加清理命令；旧UC04配置清理由后续生成器负责。Schema：'''+json.dumps(schema,ensure_ascii=False)
    if args.case=='UC-08':
        prompt='''你是本地Packet Tracer网络规划助手。按需求生成符合Schema的YAML，不加代码围栏。
case_id=UC-08，status=ready、questions=[]；不加variant、不加nat/acls、vlans=[]。
所有设备含name/type/interfaces/default_gateway/routing。非终端default_gateway:null。
R0/R1/R2各routing含一项OSPF和一项static；R3/R4仅一项static；终端和Switch0 routing=[]。
OSPF用process_id:100、networks列表与passive_interfaces。每个已编址接口都列入准确子网和反掩码、area0。
静态routes条目必须准确含prefix/next_hop/distance，只有R0两条非直连默认路由带recursive:true，其他条目不加recursive字段。
严格保留主备AD1/10和ISP返回路由；不能只配置核心却遗漏边界默认路由或服务器返回路径。
Switch0接口只name和ipv4:null，默认VLAN1，无switchport/VLAN字段。所有物理links.dce=null。
checks.destination必须为IPv4，不是设备名。只列PC0到203.0.113.100和Server0到10.1.0.10。
Schema：'''+json.dumps(schema,ensure_ascii=False)
    (out/'requirements.txt').write_text(requirement,encoding='utf-8')
    (out/'prompt.txt').write_text(prompt,encoding='utf-8')
    print('运行目录：',out,flush=True)
    client=OpenAI(api_key=key,base_url='https://api.siliconflow.cn/v1',timeout=120,max_retries=0)
    response=client.chat.completions.create(model='deepseek-ai/DeepSeek-V3.2',messages=[dict(role='system',content=prompt),dict(role='user',content=requirement)],temperature=0,max_tokens=8192,extra_body={'enable_thinking':False})
    raw=response.choices[0].message.content or ''
    (out/'raw_output.txt').write_text(raw,encoding='utf-8')
    (out/'metadata.json').write_text(json.dumps(dict(model=response.model,id=response.id,finish_reason=response.choices[0].finish_reason,usage=response.usage.model_dump() if response.usage else None),ensure_ascii=False,indent=2),encoding='utf-8')
    errors=[]
    try:
        if response.choices[0].finish_reason!='stop':raise ValueError('模型输出未正常结束。')
        text=raw.strip()
        if text.startswith('```'):
            match=re.fullmatch(r'```(?:yaml|yml)?\s*\n(.*?)\n```',text,re.S|re.I)
            if not match:raise ValueError('输出不是纯YAML或单个完整YAML代码块。')
            text=match.group(1)
        data=yaml.load(text,Loader=validator.UniqueLoader)
        (out/'topology.yaml').write_text(yaml.safe_dump(data,allow_unicode=True,sort_keys=False),encoding='utf-8')
        errors=validator.validate(data,schema)
        if isinstance(data,dict) and data.get('case_id')!=args.case:errors.append(dict(code='CASE_ID',message='模型case_id与请求用例不符。'))
    except (ValueError,yaml.YAMLError) as exc:
        errors=[dict(code='PARSE',message=str(exc))]
    (out/'validation_report.json').write_text(json.dumps(dict(passed=not errors,errors=errors),ensure_ascii=False,indent=2),encoding='utf-8')
    for error in errors:print(error)
    print('PASS：生成并校验通过。' if not errors else 'FAIL：原始输出已保存。')
    print('YAML：',out/'topology.yaml')
    return 1 if errors else 0


if __name__=='__main__':
    sys.exit(main())
