UC10 独立工具，不覆盖前面用例的共享生成器/校验器。
把本包文件复制到计网拓展根目录，保留已有accept_uc01.py（用于MCP输出及ping解析）。
生成：.\.venv\Scripts\python.exe .\uc10.py generate --requirements .\requirements_uc10.txt
编译：.\.venv\Scripts\python.exe .\uc10.py build .\runs\实际目录\topology.yaml
人工审查配置后将R0/R1/R2.cfg分别贴到Router0/1/2；PC按PT_GUIDE设置IPv6。
验收：.\.venv\Scripts\python.exe .\accept_uc10.py --run-dir .\runs\实际目录
保留MCP服务及扩展连接。验收先双向IPv4端点ping，再检查隧道配置/状态、纯IPv4骨干及双向PC IPv6 ping。IPv6 tracert保留原始返回，不宣称精确路径断言；若仿真器不支持命令会如实报错并保留证据。
本包只做离线检查，未在用户PT中验收。生成配置为本地文件，没有自动部署；禁止命令硬拦截只覆盖此编译器生成的命令，不是完整IOS语法分析器。
纯IPv4路由R1无需ipv6 unicast-routing，两端用手动tunnel mode ipv6ip，非自动6to4。
依据Cisco官方文档：https://www.cisco.com/c/en/us/td/docs/routers/ios-xe/ip-routing/b-ip-routing/m_ip6-man-tunls-xe.html
最终报告需原题、原模型输出、YAML、静态校验、首设备完整配置、实际验收、排障轮数与备注；本工具不会自动补写最终六页报告。
