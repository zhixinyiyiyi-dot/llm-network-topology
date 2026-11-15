共用工具升级：静态路由、简单二层交换机/服务器、单地址NAPT。

将包中内容合并到项目根目录，替换build_configs.py和uc01_validator内代码/Schema；保留其他程序和所有runs。
新增generate_case.py、requirements_uc04.txt、accept_uc04.py。accept_uc04.py依赖项目中已有accept_uc01.py。

真实模型生成（需当前PowerShell有SILICONFLOW_API_KEY，会产生API用量）：
.\.venv\Scripts\python.exe .\generate_case.py --requirements .\requirements_uc04.txt

生成通过后：
.\.venv\Scripts\python.exe .\build_configs.py <新运行目录>\topology.yaml --omit-nat

注意文件：R0.cfg、R1.cfg、Switch0.cfg是基线配置；R0_NAPT.cfg是随后才启用的NAPT增量配置。
不要在基线测试前粘贴R0_NAPT.cfg。
在新建的UC-04_NAPT.pkt中手工部署R0.cfg/R1.cfg/Switch0.cfg到对应设备，按指南设置PC/Server地址。
PC0=192.168.0.1/24、PC1=192.168.0.2/24，网关均192.168.0.254。
Server0=218.75.230.1/25，网关218.75.230.126。
PC与Server不需要配置HTTP等服务，本用例验证IP访问和NAPT。

MCP服务保持运行、扩展桥接连接到当前拓扑。新建拓扑后如扩展失去连接，重开MCP BUILDER确认。
等待交换端口和路由稳定后运行基线：
.\.venv\Scripts\python.exe .\accept_uc04.py --run-dir <新运行目录> --stage before

before中PC到Server不通是预期，仍必须确认R0自身到Server可达及ISP直连路由正常，不能把基础连接失败当成NAPT对比成功。
基线通过后，人工审查R0_NAPT.cfg，只粘贴到Router0。随后：
.\.venv\Scripts\python.exe .\accept_uc04.py --run-dir <新运行目录> --stage after

after检查两台PC零丢包、实际ICMP转换表（私网地址转为.253）、路径、默认路由及受限源范围。
地址池和源ACL条目精确检查，但当前不是通用ACL安全策略验证器。
若解析失败，保留实际输出诊断，不能直接修改PASS条件掩盖真实失败。

全部测试只在本地PT；R1与Server0是模拟ISP和模拟公网，不能对真实公网执行网络测试。
此包的离线样例不计作模型生成或实际设备测试成功。当前尚未完成VLAN、通用ACL或应用服务DSL支持。
PT部署仍为人工粘贴，验收只读执行；本包没有自动部署CONFIRM门，已有修复程序的CONFIRM功能继续保留。
