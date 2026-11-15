共用VLAN升级：单臂路由 + 三层交换机SVI

合并到项目根目录，替换generate_case.py、build_configs.py、uc01_validator下代码/Schema。
保留所有runs以及其他验收/排障脚本。新增accept_uc05.py、两份UC05需求。
文件夹名uc01_validator仅为向后兼容，现已支持多个用例，不是每个用例独立的一套程序。

单臂路由真实生成：
.\.venv\Scripts\python.exe .\generate_case.py --case UC-05 --requirements .\requirements_uc05_roas.txt
需要当前窗口设置SILICONFLOW_API_KEY，会产生模型用量。
模型输出与校验记录保存到新的runs时间目录，不包含预先伪造的成功记录。

通过后生成配置：
.\.venv\Scripts\python.exe .\build_configs.py <新目录>\topology.yaml
生成R0.cfg和Switch0.cfg，人工在UC-05_router_on_a_stick.pkt的新拓扑中粘贴。
PC0/1/2分别192.168.1.1/.2/.3，掩码/24，网关192.168.1.254。
PC3/4/5分别192.168.2.1/.2/.3，掩码/24，网关192.168.2.254。
对应Switch0 Fa0/1..Fa0/6，Router0 G0/0连Switch0 G0/1。
等待端口稳定后：
.\.venv\Scripts\python.exe .\accept_uc05.py --run-dir <新目录> --variant router_on_a_stick
验收只读，包含30个有向PC两两ping、2条跨VLAN路径、实际VLAN/access/trunk/子接口与直连路由检查。运行通常数分钟；失败也保存原始证据。

SVI方案待单臂完成后再做：另建UC-05_SVI.pkt，1台3560-24PS（显示名改Switch0）+6台PC，无路由器。PC接Fa0/1..Fa0/6，IP及网关不变。
生成需求换为requirements_uc05_svi.txt；配置只生成Switch0.cfg。
验收使用--variant svi。SVI方案不需要Trunk，需ip routing、Vlan10/Vlan20及对应access成员。
两方案属于同一UC-05需求的两种实现，不应直接冒充两个独立需求样例来凑评估数量。

校验器：加入VLAN引用、接入/Trunk模式、子接口/父接口、SVI与ip_routing约束，二层可达性检查按VLAN区分，避免跨VLAN错误地当成同一广播域。
旧RIP、OSPF多区域、NAPT样例已离线回归通过；新两方案及错误VLAN/Trunk遗漏/子接口未定义等负例已检查。
验收的Windows换行及接口分段解析也已测试。以上均不是实际用户PT验收结果。

支持范围：本次VLAN是UC05两套固定语义；不是任意复杂园区网络或完整Cisco语义验证器。通用ACL、HTTP服务、RIPv1对照等仍需扩展。
没有自动下发设备配置，部署为人工粘贴；本包不会执行故障修复。所有测试只在本地PT仿真环境。
