课程需求系统评测批次（五来源，非自动部署）

解压后把整个course_eval文件夹放到计网拓展根目录，不覆盖原共享生成器。
执行：
.\.venv\Scripts\python.exe .\course_eval\course_eval.py

将连续调用硅基流动模型5次，每条原始输出只请求一次，无自动重试或自动修正。当前会话需有SILICONFLOW_API_KEY。每条最多等待180秒，失败后继续下一条。
输出计网拓展/runs/course_batch_时间/，分别保存自然语言需求、课内来源及改编说明、prompt、模型原文、元数据、YAML、独立校验、配置、指南和审计。

重要口径：
- 模型只接收requirements和Schema，不接收course_cases.json中的独立预期结果。此文件用于离线校验；不要改它来迎合模型输出。
- 这些是有明确编址和策略约束的课程需求，不是对未知任意拓扑的泛化能力测试。
- 首次生成PASS仅说明通过Schema、通用地址/网关/链路/协议检查及独立需求约束。配置编译PASS不代表实际部署通过。
- 初次配置运行通过率与排障均值在此阶段保留null；等待实际部署记录后统计。没有自动部署，不触发MCP写操作。
- COURSE4-10与4-11明确复用三Serial改编拓扑，不能冒充课件混合链路原拓扑；与UC01/02重复场景不重复凑独立需求数。课程4-5采用原CIDR布局第一方案，第二编址方案未含；其他未覆盖步骤不得写已完成。
- COURSE6-6生成新的course_index.html及导入指南，需PC实际访问后留证，旧报告不是本次新页面验收。
- COURSE7-1生成有序端口ACL及服务指南，需新配置实际应用和测试，旧报告仅为参考，不直接替代本次配置验收。

每次重跑新建批次目录，保留此前失败。仅补跑指定来源可加 --case COURSE-7-1 等，但会成为后续尝试，不会覆盖首轮统计。

现在只需运行批次并上传batch_report.json和完整course_batch目录，之后核对生成内容并在现有pkt副本应用，避免重新搭建。

版本2修订：课程Schema去除variant/ip_routing/nat等无关字段，并按设备角色限制services。默认expect省略等价allow，修正比较器误判。
对已保存首次批次做模型修订（每样例再请求一次，绝不覆盖首轮）：
.\.venv\Scripts\python.exe .\course_eval\course_eval.py --repair-batch .\runs\course_batch_20261115_124318_000777
修订输出另建批次，stage=model_revision、is_first_output=false，首次通过率保留null。原五个FAIL不变。
