import json
import os
from datetime import datetime
from pathlib import Path

import yaml
from openai import OpenAI

ROOT = Path(__file__).resolve().parent
MODEL = "deepseek-ai/DeepSeek-V3.2"

PROMPT = """
你是本地 Packet Tracer 网络规划助手。
将用户需求转换为 YAML，只输出 YAML，不要 Markdown 代码围栏或解释。
不能遗漏用户明确指定的接口、地址、DCE 端及验证要求。
若需求矛盾或信息不足，status 为 needs_clarification，
在 questions 中列出问题，不得偷偷更改要求。

必须使用以下结构：
case_id: 用例编号
status: ready 或 needs_clarification
questions: 问题字符串列表，无问题时为 []
devices: 设备列表，每项包含：
  name: 设备名称
  type: router 或 pc 或 switch
  interfaces: 接口列表，每项包含：
    name: 接口名称
    ipv4: 带前缀长度的 IPv4 字符串，无地址时为 null
  default_gateway: PC 的网关字符串，其他设备为 null
  routing: 路由协议列表，无路由时为 []；
    RIP 每项包含 protocol: rip、version: 2、
    auto_summary: false、networks: 有类主网络地址字符串列表
links: 链路列表，每项包含：
  a: {device: 设备名, interface: 接口名}
  b: {device: 设备名, interface: 接口名}
  dce: {device: 设备名, interface: 接口名}，非串行链路为 null
vlans: VLAN 列表，无 VLAN 时为 []
checks: 验证列表，每项包含：
  type: ping
  source: 源设备名
  destination: 目的 IPv4 地址字符串
本任务只生成拓扑数据，不执行命令、不部署配置。
"""

def main():
    key = os.environ.get("SILICONFLOW_API_KEY")
    if not key:
        raise SystemExit("请先在当前 PowerShell 设置 API Key。")

    requirement = (ROOT / "requirements.txt").read_text(
        encoding="utf-8-sig"
    )
    run = ROOT / "runs" / datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    run.mkdir(parents=True)
    (run / "requirements.txt").write_text(requirement, encoding="utf-8")
    (run / "prompt.txt").write_text(PROMPT, encoding="utf-8")

    client = OpenAI(
        api_key=key,
        base_url="https://api.siliconflow.cn/v1",
        timeout=120.0,
        max_retries=0,
    )
    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": PROMPT},
            {"role": "user", "content": requirement},
        ],
        temperature=0,
        max_tokens=4096,
        extra_body={"enable_thinking": False},
    )

    raw = response.choices[0].message.content or ""
    (run / "raw_output.txt").write_text(raw, encoding="utf-8")
    metadata = {
        "model": MODEL,
        "response_id": response.id,
        "finish_reason": response.choices[0].finish_reason,
        "usage": response.usage.model_dump() if response.usage else None,
    }
    (run / "metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    if response.choices[0].finish_reason != "stop":
        raise ValueError("模型输出未正常结束，请查看本次运行记录。")

    data = yaml.safe_load(raw)
    if not isinstance(data, dict):
        raise ValueError("输出不是 YAML 对象，请查看 raw_output.txt。")

    required = {"case_id", "status", "questions", "devices",
                "links", "vlans", "checks"}
    missing = required - data.keys()
    if missing:
        raise ValueError(f"缺少字段：{sorted(missing)}")

    if data["status"] != "ready":
        print("需求需要澄清：", data["questions"])
        print("运行记录：", run)
        return

    if not isinstance(data["devices"], list) or not data["devices"]:
        raise ValueError("devices 必须是非空列表。")

    output = run / "topology.yaml"
    output.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    print("YAML 已生成：", output)
    print("设备数量：", len(data["devices"]))
    print("注意：目前仅做基础格式检查，尚未完成地址及 Schema 校验。")

if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("运行失败，错误类型：", type(exc).__name__)
        if isinstance(exc, (ValueError, OSError, yaml.YAMLError)):
            print(str(exc))
        elif getattr(exc, "status_code", None):
            print("HTTP 状态码：", exc.status_code)