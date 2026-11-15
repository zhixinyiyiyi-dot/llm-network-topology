"""Generate a topology through SiliconFlow; retain raw output and run static checks."""
import argparse
import copy
import hashlib
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
    parser.add_argument('--reference',type=Path,required=True)
    parser.add_argument('--case',choices=['UC-02','UC-03'],default='UC-02')
    args=parser.parse_args()
    root=Path(__file__).resolve().parent
    spec=importlib.util.spec_from_file_location('validator',root/'uc01_validator/validate.py')
    validator=importlib.util.module_from_spec(spec);spec.loader.exec_module(validator)
    schema=json.loads((root/'uc01_validator/schema.json').read_text(encoding='utf-8'))
    reference=yaml.load(args.reference.read_text(encoding='utf-8-sig'),Loader=validator.UniqueLoader)
    if validator.validate(reference,schema):
        raise ValueError('参考拓扑必须先通过校验。')
    requirement=args.requirements.read_text(encoding='utf-8-sig')
    key=os.environ.get('SILICONFLOW_API_KEY')
    if not key:
        raise ValueError('请先在本PowerShell设置 SILICONFLOW_API_KEY。')
    out=root/'runs'/datetime.now().strftime('%Y%m%d_%H%M%S_%f');out.mkdir(parents=True)
    prompt='''你是本地Packet Tracer网络规划助手。将需求转为YAML。只输出YAML，不要代码围栏。
遵守下面JSON Schema。UC-02必须保留参考UC-01的全部设备、名称、接口、地址、网关、链路、DCE及验证目标，
只将case_id改为UC-02，路由器routing改为OSPF，进程100，所有area 0。
每个已编址路由器接口用准确子网地址和反掩码声明，不要掩码/反掩码混淆。
删除所有RIP声明。每台设备的routing列表最多一项；PC保持空列表。
需求矛盾时status=needs_clarification并给出questions，不能自行更改用户要求。
拓扑YAML不包含Cisco命令，迁移时删除RIP由部署配置生成器处理。
JSON Schema：\n'''+json.dumps(schema,ensure_ascii=False)
    if args.case=='UC-03':
        prompt='''你是本地Packet Tracer网络规划助手。只输出符合以下Schema的YAML，不加代码围栏。
UC-03沿用参考拓扑的设备、接口、物理链路和DCE，但必须按新需求重新分配全部IP、网关和路由；不能沿用UC-02地址。
case_id为UC-03，OSPF进程1，每个接口使用准确网络和反掩码，area按需求。所有checks目标改成新PC地址。
R1是ABR，其连接区域内的路由可能仍标记O，不得为追求R1出现O IA而伪造结果。在R2验证总部路由O IA。
没有矛盾时status=ready、questions=[]；存在无法解决的矛盾时列出问题。
Schema：'''+json.dumps(schema,ensure_ascii=False)
    user='需求：\n'+requirement+'\n参考UC-01拓扑：\n'+yaml.safe_dump(reference,allow_unicode=True,sort_keys=False)
    (out/'requirements.txt').write_text(requirement,encoding='utf-8')
    (out/'prompt.txt').write_text(prompt,encoding='utf-8')
    (out/'reference.yaml').write_bytes(args.reference.read_bytes())
    (out/'model_input.txt').write_text(user,encoding='utf-8')
    print('运行目录：',out,flush=True)
    client=OpenAI(api_key=key,base_url='https://api.siliconflow.cn/v1',timeout=120,max_retries=0)
    response=client.chat.completions.create(model='deepseek-ai/DeepSeek-V3.2',messages=[{'role':'system','content':prompt},{'role':'user','content':user}],temperature=0,max_tokens=4096,extra_body={'enable_thinking':False})
    raw=response.choices[0].message.content or ''
    (out/'raw_output.txt').write_text(raw,encoding='utf-8')
    (out/'metadata.json').write_text(json.dumps(dict(model=response.model,response_id=response.id,finish_reason=response.choices[0].finish_reason,reference_sha256=hashlib.sha256(args.reference.read_bytes()).hexdigest(),usage=response.usage.model_dump() if response.usage else None),ensure_ascii=False,indent=2),encoding='utf-8')
    errors=[]
    if response.choices[0].finish_reason!='stop':
        errors.append(dict(code='INCOMPLETE',message='模型输出未正常结束。'))
    try:
        text=raw.strip()
        if text.startswith('```'):
            match=re.fullmatch(r'```(?:yaml|yml)?\s*\n(.*?)\n```',text,re.S|re.I)
            if not match:raise ValueError('非单个完整YAML代码块。')
            text=match.group(1)
        data=yaml.load(text,Loader=validator.UniqueLoader)
        (out/'topology.yaml').write_text(yaml.safe_dump(data,allow_unicode=True,sort_keys=False),encoding='utf-8')
        errors.extend(validator.validate(data,schema))
        if not errors:
            def fixed_part(t):
                d=copy.deepcopy(t)
                for device in d['devices']:
                    device.pop('routing',None)
                    if args.case=='UC-03':
                        device.pop('default_gateway',None)
                        for interface in device['interfaces']:interface.pop('ipv4',None)
                if args.case=='UC-03':d.pop('checks',None)
                d.pop('case_id',None);d.pop('status',None);d.pop('questions',None)
                d['devices']=sorted(d['devices'],key=lambda x:x['name'])
                for device in d['devices']:device['interfaces']=sorted(device['interfaces'],key=lambda x:x['name'])
                return d
            if data['case_id']!=args.case or fixed_part(data)!=fixed_part(reference):
                errors.append(dict(code='UC02_REFERENCE_CHANGED',message='生成结果改变了本用例要求保留的参考字段，或case_id不符。'))
    except (ValueError,yaml.YAMLError) as exc:
        errors.append(dict(code='PARSE',message=str(exc)))
    report=dict(case_id=args.case,passed=not errors,errors=errors,manual_changes=False)
    (out/'validation_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    for error in errors:print(error)
    print('PASS：生成并校验通过。' if not errors else 'FAIL：原始输出已保存，请检查校验报告。')
    print('YAML：',out/'topology.yaml')
    return 1 if errors else 0


if __name__=='__main__':
    sys.exit(main())
