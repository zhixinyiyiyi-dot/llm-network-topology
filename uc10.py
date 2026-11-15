"""UC10: model generation, independent validation, local compilation; never deploys."""
import argparse,copy,hashlib,ipaddress as ip,json,os,re,sys
from pathlib import Path
from datetime import datetime,timezone
import yaml
from jsonschema import Draft202012Validator

def plan():
    def iface(name,v4=None,v6=None):return dict(name=name,ipv4=v4,ipv6=v6)
    def dev(name,kind,interfaces,gw=None,v4routes=None,v6routes=None,tunnel=None):
        return dict(name=name,type=kind,interfaces=interfaces,ipv6_gateway=gw,ipv4_routes=v4routes or [],ipv6_routes=v6routes or [],tunnel=tunnel)
    def tun(src,dst,addr):return dict(name='Tunnel0',mode='ipv6ip',source=src,destination=dst,ipv6=addr)
    ds=[dev('R0','router',[iface('GigabitEthernet0/0',v6='2001::1/64'),iface('GigabitEthernet0/1','10.0.0.1/30')],v4routes=[dict(prefix='10.0.0.4/30',next_hop='10.0.0.2')],v6routes=[dict(prefix='2002::/64',next_hop='2003::2')],tunnel=tun('10.0.0.1','10.0.0.6','2003::1/64')),
        dev('R1','router',[iface('GigabitEthernet0/0','10.0.0.2/30'),iface('GigabitEthernet0/1','10.0.0.5/30')]),
        dev('R2','router',[iface('GigabitEthernet0/0',v6='2002::1/64'),iface('GigabitEthernet0/1','10.0.0.6/30')],v4routes=[dict(prefix='10.0.0.0/30',next_hop='10.0.0.5')],v6routes=[dict(prefix='2001::/64',next_hop='2003::1')],tunnel=tun('10.0.0.6','10.0.0.1','2003::2/64')),
        dev('PC0','pc',[iface('FastEthernet0',v6='2001::10/64')],gw='2001::1'),dev('PC1','pc',[iface('FastEthernet0',v6='2002::10/64')],gw='2002::1')]
    links=[]
    for a,ai,b,bi in [('PC0','FastEthernet0','R0','GigabitEthernet0/0'),('R0','GigabitEthernet0/1','R1','GigabitEthernet0/0'),('R1','GigabitEthernet0/1','R2','GigabitEthernet0/1'),('R2','GigabitEthernet0/0','PC1','FastEthernet0')]:links.append(dict(a=dict(device=a,interface=ai),b=dict(device=b,interface=bi)))
    return dict(case_id='UC-10',status='ready',devices=ds,links=links,checks=[dict(source='R0',destination='10.0.0.6',family='ipv4'),dict(source='R2',destination='10.0.0.1',family='ipv4'),dict(source='PC0',destination='2002::10',family='ipv6'),dict(source='PC1',destination='2001::10',family='ipv6')])

def schema_for(value):
    if isinstance(value,dict):return dict(type='object',required=list(value),additionalProperties=False,properties={k:schema_for(v) for k,v in value.items()})
    if isinstance(value,list):
        types=[]
        for x in value:
            t=schema_for(x)
            if t not in types:types.append(t)
        return dict(type='array',items=types[0] if len(types)==1 else dict(anyOf=types)) if types else dict(type='array')
    if value is None:return dict(type=['string','null'])
    return dict(type='string')

class Loader(yaml.SafeLoader):pass
def unique(loader,node):
    out={}
    for k,v in node.value:
        key=loader.construct_object(k)
        if key in out:raise ValueError('重复YAML字段：'+str(key))
        out[key]=loader.construct_object(v)
    return out
Loader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,unique)
def canonical(data):
    if isinstance(data,dict):return {k:canonical(v) for k,v in data.items()}
    if isinstance(data,list):return sorted([canonical(v) for v in data],key=lambda v:json.dumps(v,sort_keys=True))
    if isinstance(data,str):
        try:return str(ip.ip_interface(data)) if '/' in data and ':' in data else str(ip.ip_address(data)) if ':' in data else data
        except ValueError:return data
    return data

def validate(data):
    expected=plan();schema=json.loads((Path(__file__).parent/'uc10_schema.json').read_text())
    errors=[dict(code='SCHEMA',path='/'.join(map(str,e.path)),message=e.message) for e in Draft202012Validator(schema).iter_errors(data)]
    if errors:return errors
    seen=set()
    for d in data['devices']:
        for it in d['interfaces']:
            for family in ['ipv4','ipv6']:
                if not it[family]:continue
                try:
                    addr=ip.ip_interface(it[family]);assert addr.version==(4 if family=='ipv4' else 6)
                    assert not addr.ip.is_multicast and not addr.ip.is_unspecified
                    assert addr.ip not in seen;seen.add(addr.ip)
                    if addr.version==4:assert addr.ip in addr.network.hosts()
                except (ValueError,AssertionError):errors.append(dict(code='ADDRESS',path=d['name']+'/'+it['name'],message='地址无效、重复、非可用主机或版本不符'))
        if d['type']=='pc':
            try:
                own=ip.ip_interface(d['interfaces'][0]['ipv6']);gw=ip.ip_address(d['ipv6_gateway']);assert gw in own.network and gw!=own.ip
            except (ValueError,TypeError,AssertionError):errors.append(dict(code='GATEWAY',path=d['name'],message='IPv6网关必须在本站点子网且不等于终端地址'))
    # Fixed case intent independently constrains every link, prefix, gateway, route and tunnel endpoint.
    for field in ['case_id','status','devices','links','checks']:
        if canonical(data[field])!=canonical(expected[field]):errors.append(dict(code='UC10_INTENT',path=field,message='与requirements_uc10指定规划不一致；检查/30底层、/64站点、网关、对称隧道端点和路由。'))
    return errors

def sha(text):return hashlib.sha256(text.encode()).hexdigest()
def write_json(p,d):p.write_text(json.dumps(d,ensure_ascii=False,indent=2),encoding='utf-8')
def generate(args):
    from openai import OpenAI
    root=Path(__file__).resolve().parent;out=root/'runs'/datetime.now().strftime('%Y%m%d_%H%M%S_%f');out.mkdir(parents=True)
    print('运行目录：',out,flush=True)
    req=args.requirements.read_text(encoding='utf-8-sig');(out/'requirements.txt').write_text(req,encoding='utf-8')
    schema=(root/'uc10_schema.json').read_text()
    prompt='将需求转成严格符合下列Schema的YAML。只输出YAML，不要围栏或额外解释。所有字段必填，空值null，空列表[]。interfaces仅物理接口，隧道写独立tunnel字段。R1为纯IPv4骨干，ipv6全null且没有隧道。checks按IPv4先、IPv6后。'+schema
    (out/'prompt.txt').write_text(prompt,encoding='utf-8')
    key=os.environ.get('SILICONFLOW_API_KEY')
    if not key:raise ValueError('当前PowerShell没有SILICONFLOW_API_KEY')
    print('正在请求模型，最多等待120秒……',flush=True)
    r=OpenAI(api_key=key,base_url='https://api.siliconflow.cn/v1',timeout=120,max_retries=0).chat.completions.create(model='deepseek-ai/DeepSeek-V3.2',messages=[dict(role='system',content=prompt),dict(role='user',content=req)],temperature=0,max_tokens=8192,extra_body={'enable_thinking':False})
    raw=r.choices[0].message.content or '';(out/'model_raw_output.txt').write_text(raw,encoding='utf-8');write_json(out/'metadata.json',r.model_dump(mode='json'))
    (out/'topology.yaml').write_text(raw,encoding='utf-8')
    try:
        if r.choices[0].finish_reason!='stop':raise ValueError('模型输出未完整结束')
        d=yaml.load(raw,Loader=Loader);errors=validate(d)
    except Exception as e:errors=[dict(code='PARSE',message=str(e))]
    write_json(out/'validation_report.json',dict(status='FAIL' if errors else 'PASS',errors=errors))
    print('FAIL：保留原始输出。' if errors else 'PASS：生成并校验通过。');print('YAML：',out/'topology.yaml')
    for e in errors:print(e)
    return bool(errors)

ALLOWED=[r'enable',r'configure terminal',r'hostname R[012]',r'ipv6 unicast-routing',r'interface (?:GigabitEthernet0/[01]|Tunnel0)',r'ip address [0-9.]+ [0-9.]+',r'ipv6 address [0-9a-fA-F:/]+',r'no shutdown',r'exit',r'end',r'tunnel source [0-9.]+',r'tunnel destination [0-9.]+',r'tunnel mode ipv6ip',r'ip route [0-9.]+ [0-9.]+ [0-9.]+',r'ipv6 route [0-9a-fA-F:/]+ [0-9a-fA-F:]+']
def guard(lines):
    for line in lines:
        if re.search(r'reload|erase|format|delete|write|[;|\r\n]',line,re.I) or not any(re.fullmatch(p,line) for p in ALLOWED):raise ValueError('命令白名单拒绝：'+line)
def build(args):
    raw=args.topology.read_text(encoding='utf-8-sig');d=yaml.load(raw,Loader=Loader);errors=validate(d)
    if errors:raise ValueError(str(errors))
    out=args.topology.resolve().parent/('configs_'+datetime.now().strftime('%Y%m%d_%H%M%S_%f'));out.mkdir()
    guide=['UC10：仅生成文件，未部署。先人工审查后粘贴Router0/1/2对应R0/1/2.cfg。','PC手工设置IPv6地址/前缀/默认网关；IPv4留空；Tunnel0是软件接口，不接线。']
    files={}
    for dev in d['devices']:
        if dev['type']=='pc':guide.append(dev['name']+'：IPv6 '+dev['interfaces'][0]['ipv6']+'，默认网关 '+dev['ipv6_gateway']);continue
        lines=['enable','configure terminal','hostname '+dev['name']]
        if dev['tunnel']:lines+=['ipv6 unicast-routing']
        for it in dev['interfaces']:
            lines+=['interface '+it['name']]
            if it['ipv4']:
                addr=ip.ip_interface(it['ipv4']);lines+=['ip address '+str(addr.ip)+' '+str(addr.netmask)]
            if it['ipv6']:lines+=['ipv6 address '+it['ipv6']]
            lines+=['no shutdown','exit']
        for r in dev['ipv4_routes']:
            net=ip.ip_network(r['prefix']);lines+=['ip route '+str(net.network_address)+' '+str(net.netmask)+' '+r['next_hop']]
        t=dev['tunnel']
        if t:lines+=['interface Tunnel0','ipv6 address '+t['ipv6'],'tunnel source '+t['source'],'tunnel destination '+t['destination'],'tunnel mode ipv6ip','no shutdown','exit']
        for r in dev['ipv6_routes']:lines+=['ipv6 route '+r['prefix']+' '+r['next_hop']]
        lines+=['end'];guard(lines);content='\n'.join(lines)+'\n';(out/(dev['name']+'.cfg')).write_text(content,encoding='utf-8');files[dev['name']+'.cfg']=sha(content)
    guide+=['配置好后运行accept_uc10.py，先验证两端IPv4；底层失败时停止，不继续IPv6验收。','通过后路由器手工copy running-config startup-config并保存UC-10_IPv6_Tunnel.pkt。']
    (out/'PT_GUIDE.txt').write_text('\n'.join(guide),encoding='utf-8');write_json(out/'generation_audit.json',dict(source_sha256=sha(raw),validated=True,command_guard_passed=True,deployed=False,files=files))
    print('配置生成成功（尚未部署）：',out)

def main():
    p=argparse.ArgumentParser();sub=p.add_subparsers(dest='action',required=True)
    g=sub.add_parser('generate');g.add_argument('--requirements',type=Path,required=True)
    b=sub.add_parser('build');b.add_argument('topology',type=Path)
    a=p.parse_args();return generate(a) if a.action=='generate' else build(a)
if __name__=='__main__':
    try:sys.exit(main())
    except Exception as e:print('已停止：',type(e).__name__,str(e));sys.exit(1)
