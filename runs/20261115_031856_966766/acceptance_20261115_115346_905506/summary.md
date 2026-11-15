# UC-10 验收

状态：PASS

IPv4门槛通过：True

|检查|结果|说明|
|---|---|---|
|设备名称|PASS|要求五个预期设备名；非完整接线证明|
|Router0隧道端点IPv4|PASS|IOS正式ping要求100%、5/5；实际[('100', '5', '5')]|
|Router2隧道端点IPv4|PASS|IOS正式ping要求100%、5/5；实际[('100', '5', '5')]|
|Router0隧道配置|PASS|接口形式隧道源；不匹配项：[]|
|Router0隧道状态|PASS|要求show ipv6 interface brief明确显示Tunnel0 [up/up]|
|Router2隧道配置|PASS|接口形式隧道源；不匹配项：[]|
|Router2隧道状态|PASS|要求show ipv6 interface brief明确显示Tunnel0 [up/up]|
|骨干保持纯IPv4|PASS|中间路由器不得配置IPv6转发、IPv6地址或隧道|
|PC0端到端IPv6|PASS|发送 4，收到 4，丢失 0；验收要求 4/4、0 丢包。|
|PC1端到端IPv6|PASS|发送 4，收到 4，丢失 0；验收要求 4/4、0 丢包。|

路径输出只保留原始证据，未声明精确路径自动断言通过。
本次为只读验收，不计Agent修复轮数。
错误：[]