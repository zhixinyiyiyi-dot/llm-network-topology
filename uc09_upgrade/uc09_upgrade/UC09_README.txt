UC-09 eBGP 本地Packet Tracer升级包
合并本目录内容到计网拓展项目根目录，保留现有文件及runs。
设备：两台2911，显示名称Router0和Router1，G0/0对接，交叉线。

1. 生成（调用模型，但不部署）
.\.venv\Scripts\python.exe .\generate_case.py --case UC-09 --requirements .\requirements_uc09.txt
2. 使用上一步实际运行目录编译topology.yaml：
.\.venv\Scripts\python.exe .\build_configs.py .\runs\实际目录\topology.yaml
3. 人工审查后把R0.cfg贴到Router0、R1.cfg贴到Router1的CLI。
Loopback0是软件接口，不增加设备、不连接网线。等待邻居建立。
4. 只读自动验收：
.\.venv\Scripts\python.exe .\accept_uc09.py --run-dir .\runs\实际目录
5. 通过后两台路由器保存startup-config，保存UC-09_eBGP.pkt。

题意补充需写入报告：原宣告10.0.0.0/24也是两端共同直连网段，R1的IP路由表对此优先C，不能据此认定eBGP失败。本例保留原宣告，额外增加R0的Loopback0 10.1.0.1/24及10.1.0.0/24宣告。R1的Loopback0为20.0.0.1/24。分别证明R0安装B 20.0.0.0/24、R1安装B 10.1.0.0/24，核对AS_PATH及Established邻居。此项是对原需求的明确补充，不声称原要求无歧义。

本包已做离线格式、正负例、解析和配置生成检查；尚未在用户实际PT中验收。离线测试不计入真实用例成功率。
