共用工具UC-03升级：支持同物理拓扑重新编址、多区域OSPF及旧进程清理。
保留原有runs和已完成PT文件，不要删除。先将UC-02_OSPF.pkt另存为UC-03_OSPF_multi_area.pkt。

安装：将本包所有内容合并到项目根目录，允许替换build_configs.py、generate_v2.py、uc01_validator下的代码和Schema。
accept_uc01.py、accept_ospf.py、repair_uc01.py不需要替换。原有RIP、UC-02功能保留。
新增requirements_uc03.txt与accept_uc03.py。

生成：
.\.venv\Scripts\python.exe .\generate_v2.py --case UC-03 --requirements .\requirements_uc03.txt --reference .\runs\20261114_225933_109486\topology.yaml
需要当前窗口有SILICONFLOW_API_KEY；会调用模型、产生API用量，真实输出保存到新的runs目录。

配置生成（<新目录>替换为刚生成的runs时间目录）：
.\.venv\Scripts\python.exe .\build_configs.py <新目录>\topology.yaml --replace-ospf-process 100
生成配置包含no router ospf 100，随后接口主IP设置替换旧地址，启用router ospf 1及新区域。
只生成文件，不自动下发。审查后在UC-03副本中按设备粘贴，不能覆盖UC-02。
PC0改为192.168.0.10/24，网关192.168.0.254；PC1改为192.168.1.10/24，网关192.168.1.254。
接线和DCE不变。路由器的新地址与区域见需求和生成配置。

验收：
.\.venv\Scripts\python.exe .\accept_uc03.py --run-dir <新目录>
PT及MCP服务保持运行；验收不修改配置。
检查双向ping/路径、OSPF进程1、无RIP、各台邻居、区域声明、R1 ABR、关键路由及R2到总部的O IA。

题意解释：R1本身连接area0与area100，是ABR，其已连接区域内的路由可仍标记O。检查R1并记录实际标记，在仅属area100的R2上验证到总部的O IA。不能为了让R1出现O IA伪改拓扑；最终报告应明确解释这一点。
扩展链路按现有三角形的R0-R2链路实现，划为area100；HQ LAN为area0、分部LAN为area100。

离线测试已验证正常示例、错误进程/区域/测试目标拦截、旧OSPF100清理、O IA断言与原有RIP兼容。
尚未在用户PT中实际运行UC-03，不能把离线样例作为LLM生成或真实验收成功记录。
VLAN/静态路由/NAT/HTTP/ACL仍待扩展。
