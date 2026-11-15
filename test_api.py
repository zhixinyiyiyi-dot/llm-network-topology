import os
from openai import OpenAI

key = os.environ.get("SILICONFLOW_API_KEY")
if not key:
    raise SystemExit("未设置 SILICONFLOW_API_KEY，请先在 PowerShell 输入密钥。")

client = OpenAI(
    api_key=key,
    base_url="https://api.siliconflow.cn/v1",
    timeout=60.0,
    max_retries=0,
)

try:
    response = client.chat.completions.create(
        model="deepseek-ai/DeepSeek-V3.2",
        messages=[
            {"role": "user", "content": "请只回答：连接成功"}
        ],
        max_tokens=64,
        extra_body={"enable_thinking": False},
    )
    print("模型回复：", response.choices[0].message.content)
except Exception as exc:
    status = getattr(exc, "status_code", None)
    print("调用失败，错误类型：", type(exc).__name__)
    if status:
        print("HTTP 状态码：", status)