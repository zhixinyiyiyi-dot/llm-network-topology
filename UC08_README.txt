共用工具UC08增量升级：OSPF与静态路由共存、主备管理距离、被动接口及三阶段验收。

安装：将包内文件合并到项目根目录，替换generate_case.py/build_configs.py/uc01_validator下代码及Schema；保留所有旧runs和验收脚本。
新增requirements_uc08.txt、accept_uc08.py；验收依赖已有accept_uc01.py。

拓扑已按5台2911（Router0..4）+2960（Switch0）+PC0+Server0搭好。仅在本地PT运行。
生成：
.\.venv\Scripts\python.exe .\generate_case.py --case UC-08 --requirements .\requirements_uc08.txt
需当前窗口有SILICONFLOW_API_KEY，会产生模型用量。输出新runs目录及真实原始模型记录。

配置生成：
.\.venv\Scripts\python.exe .\build_configs.py <新运行目录>\topology.yaml
人工审查并粘贴R0..R4.cfg到对应Router0..4，Switch0.cfg到Switch0；本工具不自动下发。
PC0：10.1.0.10，掩码255.255.0.0，网关10.1.0.254。
Server0：203.0.113.100，掩码255.255.255.0，网关203.0.113.1。

设计要点：R0两条静态默认路由下一跳分别为ISP1的198.51.100.2（AD1）、ISP2的198.51.100.6（AD10）；通过内部OSPF所学WAN前缀解析。
R1/R2的WAN接口在OSPF中被动，只发布本机网段，不与ISP建立邻居。R1/R2各自具备出口默认路由。
主链路关闭后，R1失去198.51.100.0/30直连前缀并通过OSPF撤销；核心应移除主默认路由并启用AD10备用。
Server网关始终是ISP1的203.0.113.1；ISP1必须有到总部10.1.0.0/16经ISP2 203.0.113.2、AD10的备用返回路由，否则只切正向会失败。
这是依据路由解析规则设计的预期，需要实际PT三阶段验证，不把离线配置检查当成真实切换成功。

1 正常阶段（等待OSPF收敛后）：
.\.venv\Scripts\python.exe .\accept_uc08.py --run-dir <新运行目录> --stage primary

2 正常阶段通过后，由用户在Router1的CLI手动执行受控链路关闭：
enable
configure terminal
interface GigabitEthernet0/1
shutdown
end
等待约40秒，再运行：
.\.venv\Scripts\python.exe .\accept_uc08.py --run-dir <新运行目录> --stage backup
只关闭此本地仿真WAN接口，不修改静态路由来制造切换结果。

3 验收完成后恢复同一接口：
configure terminal
interface GigabitEthernet0/1
no shutdown
end
等待约40秒，再运行：
.\.venv\Scripts\python.exe .\accept_uc08.py --run-dir <新运行目录> --stage restored

每个阶段分别保存原始输出、JSON报告和摘要；主备实际路由/AD、WAN解析路由撤销、返回路径、双向ping、tracert路径均检查。
故障开关是人为控制测试条件，非Agent自动排障，不把本实验当成C3教师/同学预置故障盲测。
只在接口恢复且正常后copy running-config startup-config并保存UC-08_Dual_ISP.pkt；不要把关闭状态当最终正常版保存。
此例仅验证本地链路down，未配置IP SLA/track，不能声称检测了远端ISP黑洞或全部业务故障。

技术依据：Cisco IOS静态路由文档（递归下一跳、管理距离、不能自递归）：
https://www.cisco.com/c/en/us/support/docs/dial-access/floating-static-route/118263-technote-nexthop-00.html
https://www.cisco.com/c/en/us/td/docs/ios/iproute_pi/command/reference/iri_book/iri_pi1.html

离线已检查UC08样例、错误AD/被动接口/返回路由拦截、7类旧样例回归和4项路由解析测试。离线结果不计为用户实际模型生成或PT通过。
