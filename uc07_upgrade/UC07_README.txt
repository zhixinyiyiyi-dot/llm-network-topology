共用工具升级：UC07咖啡馆VLAN + 双内网NAPT + 扩展ACL。

适用前提：UC-04_NAPT.pkt已另存为UC-07_Cafe_ACL.pkt，设备和接线不变；只在本地PT。
安装：合并包内文件到项目根目录，替换generate_case.py/build_configs.py/uc01_validator，保留所有runs及旧验收程序。
accept_uc07.py依赖项目已有accept_uc01.py、修正过NAT连列解析的accept_uc04.py、accept_uc05.py，不要删掉它们。

模型生成：
.\.venv\Scripts\python.exe .\generate_case.py --case UC-07 --requirements .\requirements_uc07.txt
需要当前PowerShell有SILICONFLOW_API_KEY，会产生API用量；保存真实模型输出与校验，不预填成功。

通过后生成迁移配置：
.\.venv\Scripts\python.exe .\build_configs.py <新目录>\topology.yaml --from-uc04

--from-uc04仅允许UC07。R0.cfg先清理已有ICMP动态转换，移除UC04旧NAPT绑定/地址池/源ACL、父接口内网地址及inside标记；然后配置子接口、UC07地址池、源范围和GUEST_IN。
这些是待人工审查并粘贴的配置，不会自动下发。
只在UC07副本粘贴R0.cfg到Router0、R1.cfg到Router1、Switch0.cfg到Switch0；不额外粘贴R0_NAPT.cfg（完整R0.cfg已包含NAPT）。
出现命令错误应停止排查，不跳过错误假称成功。

终端地址：PC0客人192.168.30.10/24，网关192.168.30.254；PC1收银192.168.40.10/24，网关192.168.40.254。
Server0保留218.75.230.1/25，网关218.75.230.126。
交换机Fa0/1为VLAN30、Fa0/2为VLAN40、Fa0/24为Trunk30,40。物理接线不变。

自动验收：
.\.venv\Scripts\python.exe .\accept_uc07.py --run-dir <新目录>
保持MCP服务、PT及扩展连接；只读，不修改配置。
检查ACL顺序和绑定、客人不能ping收银、收银能主动ping客人、两PC均能访问Server0、实际转换表和路径、拒绝与echo-reply命中计数。

策略范围说明：普通扩展ACL是无状态的。先允许echo-reply及TCP established标志回包，再deny guest→cashier，最后permit其他流量。
实际验收测试ICMP方向与NAPT；TCP established仅检查配置，未做业务验证；不宣称完整状态防火墙或任意UDP会话回流支持。报告需保留此范围。
这一用例不是课内7-1原拓扑的完整复现，不能未经核对直接当成课内实验已完成。

离线：UC07正常样例、错误ACL顺序/方向/协议、NAT范围、测试预期等拦截及RIP/OSPF/NAPT/两种VLAN/同LAN旧样例回归通过。
离线结果不算真实用户PT通过，最终以运行日志为准。
