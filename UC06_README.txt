共用工具UC-06增量升级：同网段、无路由器、无默认网关。

合并包内文件到项目根目录，替换generate_case.py/build_configs.py/uc01_validator下代码与Schema。
保留所有runs和原有验收脚本。新增requirements_uc06.txt、accept_uc06.py；依赖现有accept_uc01.py。

生成：
.\.venv\Scripts\python.exe .\generate_case.py --case UC-06 --requirements .\requirements_uc06.txt
需当前PowerShell有SILICONFLOW_API_KEY，产生API用量，保存真实模型输出与校验报告。

配置：
.\.venv\Scripts\python.exe .\build_configs.py <新运行目录>\topology.yaml
只生成Switch0.cfg和指南。新建UC-06_LAN.pkt的PC0接Fa0/1、PC1接Fa0/2；交换机2960。
手工粘贴配置到Switch0；PC0设192.168.1.1/24、PC1设192.168.1.2/24；默认网关留空或PT显示0.0.0.0，不填写.254。
不需管理IP、NAT或额外VLAN，使用默认VLAN1。

等待交换端口稳定后自动验收：
.\.venv\Scripts\python.exe .\accept_uc06.py --run-dir <新运行目录>
PT和MCP服务保持运行；只读采集ipconfig、VLAN1、双向正式ping及同网段路径。
该用例无需路由表验证，报告中记为不适用，而不是虚构一条路由断言通过。

UC06免网关只对该用例开放；其他需要网关的旧用例仍检查网关。
离线检查：无网关样例通过，错误网关/掩码被拦截，RIP/OSPF/NAPT/两种VLAN旧样例回归通过，5项ipconfig解析检查通过。
离线结果不算模型生成或真实PT实验成功，最终以用户本机运行记录为准。
