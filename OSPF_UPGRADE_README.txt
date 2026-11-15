共用工具升级：IPv4 RIP + OSPF

将本包中的文件直接合并到“计网拓展”项目根目录，不要把外层目录套在项目下面。
允许替换：build_configs.py、uc01_validator/validate.py、uc01_validator/schema.json。
新增：generate_v2.py、accept_ospf.py、requirements_uc02.txt。
原来的 generate.py、accept_uc01.py、repair_uc01.py 和所有 runs 文件不需要删除。
建议替换前备份工具旧版；保留源码版本以便复现之前实验。

uc01_validator 的文件夹名出于兼容旧程序而保留；其校验器现在支持 RIP 和 OSPF，不是一套单独的UC-02程序。
目前仍不支持 VLAN、IPv6、NAT、ACL；不能声称完成所有 DSL 要求。
generate_v2.py 当前用于参考UC-01生成UC-02；通用多场景入口尚待继续扩展。

1. PT 另存为 UC-02_OSPF.pkt，不覆盖正常 UC-01_generated.pkt；拓扑、接口、地址不变。
2. 在已设置 SILICONFLOW_API_KEY 的 PowerShell 中执行：
.\.venv\Scripts\python.exe .\generate_v2.py --requirements .\requirements_uc02.txt --reference .\runs\20261114_172847_213246\topology.fixed.yaml

将调用硅基流动模型并产生API用量。输出到新的 runs/时间目录，保留原始模型输出及参考拓扑、校验记录。
若输出 FAIL，先看错误，不要为了凑通过率覆写原始文件。

3. 生成通过后（把 <新运行目录> 换成真实路径）：
.\.venv\Scripts\python.exe .\build_configs.py <新运行目录>\topology.yaml --migrate-from-rip

--migrate-from-rip 会在各路由器配置中加入 no router rip；只接受全OSPF目标拓扑。
本程序只生成文件，不会自动下发。部署前需审查并在UC-02副本中操作。
PC 地址和网关保持不变。迁移完成后等待 OSPF 邻接及路由收敛。

4. PT与MCP服务保持运行，然后执行：
.\.venv\Scripts\python.exe .\accept_ospf.py --run-dir <新运行目录>

验收：双向ping、双向路径、四条关键OSPF路由、各路由器进程100、清除旧RIP、每台2个FULL邻居。
只读采集，不修改配置。输出原始返回、JSON报告和摘要。
两条终端路径在本用例预期仍经R0-R2直连链路。不能把该三角形拓扑预先宣称为ECMP；实际路由表另行记录观察。
这个验收脚本针对UC-02固定断言，不是任意拓扑的通用验收器。

离线验证：7项Schema/协议语义测试、3台迁移配置检查、11项验收解析测试通过。
这些不等于用户电脑上的LLM生成或Packet Tracer测试通过，真实结果需要后续运行记录。
本包不包含预先填写成功状态的UC-02日志。
