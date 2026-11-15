# 离线安全检查

状态：PASS

- 合法模板正例：PASS；合法模板允许，仅离线检查
- 黑名单reload：PASS；ALERT_BLOCKED 命令被安全检查拒绝：'reload'
- 黑名单write erase：PASS；ALERT_BLOCKED 命令被安全检查拒绝：'write erase'
- 黑名单format：PASS；ALERT_BLOCKED 命令被安全检查拒绝：'format flash:'
- 未知CLI白名单：PASS；ALERT_BLOCKED 命令被安全检查拒绝：'show version'
- 不完整IP命令：PASS；ALERT_BLOCKED 命令被安全检查拒绝：'ip address 192.168.1.1'
- 命令拼接：PASS；ALERT_BLOCKED 命令被安全检查拒绝：'no shutdown; reload'
- 正确DSL正例：PASS；现有UC01修正后目标应合法
- 非法地址/掩码：PASS；拦截代码：['IP_INVALID', 'RIP_NETWORK_UNUSED', 'GATEWAY_INVALID']
- 错误终端网关：PASS；拦截代码：['GATEWAY_INVALID']
- 非法重叠地址：PASS；拦截代码：['DUP_IP', 'LINK_SUBNET', 'DISCONNECTED_SUBNET', 'RIP_NETWORK_UNUSED']
- 网关/VLAN一致性：PASS；拦截代码：['DISCONNECTED_SUBNET', 'GATEWAY_INVALID', 'UC05_ACCESS']
- 越界接口：PASS；接口不属于预期拓扑。
- 未知修复动作：PASS；操作字段、类型或目标设备不在白名单。
- 额外任意命令：PASS；操作字段、类型或目标设备不在白名单。

无设备写入；不冒充线上危险命令下发、CONFIRM门实测、Batfish或盲测。