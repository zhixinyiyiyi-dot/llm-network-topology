# UC-05 router_on_a_stick 自动验收

状态：PASS

|检查|结果|说明|
|---|---|---|
|设备存在|PASS|已找到所有预期设备名称。|
|VLAN10存在|PASS|show vlan brief应显示该VLAN active。|
|VLAN20存在|PASS|show vlan brief应显示该VLAN active。|
|FastEthernet0/1接入VLAN|PASS|要求access VLAN 10。|
|FastEthernet0/2接入VLAN|PASS|要求access VLAN 10。|
|FastEthernet0/3接入VLAN|PASS|要求access VLAN 10。|
|FastEthernet0/4接入VLAN|PASS|要求access VLAN 20。|
|FastEthernet0/5接入VLAN|PASS|要求access VLAN 20。|
|FastEthernet0/6接入VLAN|PASS|要求access VLAN 20。|
|上联Trunk|PASS|Gi0/1配置允许10,20，实际状态trunking。|
|GigabitEthernet0/0.10|PASS|要求dot1Q、网关正确且up/up。|
|GigabitEthernet0/0.20|PASS|要求dot1Q、网关正确且up/up。|
|192.168.1.0/24直连路由|PASS|要求通过对应子接口/SVI直连。|
|192.168.2.0/24直连路由|PASS|要求通过对应子接口/SVI直连。|
|PC0→PC1|PASS|发送 4，收到 4，丢失 0；验收要求 4/4、0 丢包。|
|PC0→PC2|PASS|发送 4，收到 4，丢失 0；验收要求 4/4、0 丢包。|
|PC0→PC3|PASS|发送 4，收到 4，丢失 0；验收要求 4/4、0 丢包。|
|PC0→PC4|PASS|发送 4，收到 4，丢失 0；验收要求 4/4、0 丢包。|
|PC0→PC5|PASS|发送 4，收到 4，丢失 0；验收要求 4/4、0 丢包。|
|PC1→PC0|PASS|发送 4，收到 4，丢失 0；验收要求 4/4、0 丢包。|
|PC1→PC2|PASS|发送 4，收到 4，丢失 0；验收要求 4/4、0 丢包。|
|PC1→PC3|PASS|发送 4，收到 4，丢失 0；验收要求 4/4、0 丢包。|
|PC1→PC4|PASS|发送 4，收到 4，丢失 0；验收要求 4/4、0 丢包。|
|PC1→PC5|PASS|发送 4，收到 4，丢失 0；验收要求 4/4、0 丢包。|
|PC2→PC0|PASS|发送 4，收到 4，丢失 0；验收要求 4/4、0 丢包。|
|PC2→PC1|PASS|发送 4，收到 4，丢失 0；验收要求 4/4、0 丢包。|
|PC2→PC3|PASS|发送 4，收到 4，丢失 0；验收要求 4/4、0 丢包。|
|PC2→PC4|PASS|发送 4，收到 4，丢失 0；验收要求 4/4、0 丢包。|
|PC2→PC5|PASS|发送 4，收到 4，丢失 0；验收要求 4/4、0 丢包。|
|PC3→PC0|PASS|发送 4，收到 4，丢失 0；验收要求 4/4、0 丢包。|
|PC3→PC1|PASS|发送 4，收到 4，丢失 0；验收要求 4/4、0 丢包。|
|PC3→PC2|PASS|发送 4，收到 4，丢失 0；验收要求 4/4、0 丢包。|
|PC3→PC4|PASS|发送 4，收到 4，丢失 0；验收要求 4/4、0 丢包。|
|PC3→PC5|PASS|发送 4，收到 4，丢失 0；验收要求 4/4、0 丢包。|
|PC4→PC0|PASS|发送 4，收到 4，丢失 0；验收要求 4/4、0 丢包。|
|PC4→PC1|PASS|发送 4，收到 4，丢失 0；验收要求 4/4、0 丢包。|
|PC4→PC2|PASS|发送 4，收到 4，丢失 0；验收要求 4/4、0 丢包。|
|PC4→PC3|PASS|发送 4，收到 4，丢失 0；验收要求 4/4、0 丢包。|
|PC4→PC5|PASS|发送 4，收到 4，丢失 0；验收要求 4/4、0 丢包。|
|PC5→PC0|PASS|发送 4，收到 4，丢失 0；验收要求 4/4、0 丢包。|
|PC5→PC1|PASS|发送 4，收到 4，丢失 0；验收要求 4/4、0 丢包。|
|PC5→PC2|PASS|发送 4，收到 4，丢失 0；验收要求 4/4、0 丢包。|
|PC5→PC3|PASS|发送 4，收到 4，丢失 0；验收要求 4/4、0 丢包。|
|PC5→PC4|PASS|发送 4，收到 4，丢失 0；验收要求 4/4、0 丢包。|
|PC0跨VLAN路径|PASS|实际路径 ['192.168.1.254', '192.168.2.1']；预期 ['192.168.1.254', '192.168.2.1']。|
|PC3跨VLAN路径|PASS|实际路径 ['192.168.2.254', '192.168.1.1']；预期 ['192.168.2.254', '192.168.1.1']。|

6台PC的30个有向ping，网关预热单独留档；本程序不修改配置。
错误：[]