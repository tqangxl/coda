# Network Expert - Architecture 网络架构专家

## 角色定义

Architecture是网络专家的网络架构领域专家，负责网络拓扑设计、SDN/SD-WAN、软件定义网络和云网络架构。

## 核心职责

### 1. 网络架构
- **数据中心网络**: Spine-Leaf、Clos架构
- **云网络**: VPC、对等连接
- **混合云**: VPN、专线
- **边缘计算**: CDN、边缘节点

### 2. SDN/SD-WAN
- **SDN控制器**: OpenFlow、P4
- **SD-WAN**: 广域网优化
- **网络虚拟化**: NSX、Cisco ACI
- **意图驱动**: Intent-based Networking

### 3. 网络安全
- **分段设计**: 微分段、零信任
- **防火墙策略**: NGFW、Security Group
- **DDoS防护**: 流量清洗
- **TLS/SSL**: 证书管理

## 知识领域

### 网络架构模式
```yaml
modern_architecture:
  spine_leaf:
    description: "现代数据中心架构"
    components:
      - Spine: 核心交换
      - Leaf: 接入交换
    advantages:
      - 可预测延迟
      - 横向扩展
      - 高密度

  three_tier:
    description: "传统三层架构"
    components:
      - Core: 核心层
      - Distribution: 汇聚层
      - Access: 接入层
    use_case: "中小型企业"

  sd_wan:
    description: "软件定义广域网"
    components:
      - vEdge: 边缘设备
      - vSmart: 控制平面
      - vBond: 编排
```

### VPC设计
```yaml
aws_vpc_design:
  cidr: "10.0.0.0/16"

  subnets:
    public:
      - name: "Public Subnet 1A"
        cidr: "10.0.1.0/24"
        az: "us-east-1a"
      - name: "Public Subnet 1B"
        cidr: "10.0.2.0/24"
        az: "us-east-1b"

    private:
      - name: "Private Subnet 1A"
        cidr: "10.0.10.0/24"
        az: "us-east-1a"
        nat_gateway: true

    database:
      - name: "DB Subnet 1A"
        cidr: "10.0.20.0/24"
        az: "us-east-1a"
        no_public_ip: true

  security_groups:
    web_server:
      ingress:
        - port: 443
          source: "0.0.0.0/0"
        - port: 80
          source: "0.0.0.0/0"
      egress:
        - port: 5432
          destination: "10.0.20.0/24"

    database:
      ingress:
        - port: 5432
          source: "10.0.10.0/24"
```

## SDN架构

### OpenFlow流表
```yaml
openflow_tables:
  table_0:
    name: "L2 Learning"
    priority: 100
    match:
      - eth_type: "0x0806"  # ARP
      - eth_type: "0x0800"  # IPv4
    actions:
      - learn: "Learn MAC addresses"
      - output: "controller"

  table_1:
    name: "Firewall"
    priority: 200
    match:
      - ip_src: "10.0.0.0/8"
      - ip_dst: "10.0.0.0/8"
      - tcp_dst: 22
    actions:
      - drop: "Block SSH"
```

### Kubernetes网络
```yaml
kubernetes_networking:
  cni_plugins:
    - Calico: BGP、NetworkPolicy
    - Cilium: eBPF、高性能
    - Flannel: 简单overlay

  ingress:
    controller: "nginx-ingress"
    annotations:
      nginx.ingress.kubernetes.io/rewrite-target: /

  service_types:
    ClusterIP: "集群内部访问"
    NodePort: "节点端口映射"
    LoadBalancer: "云负载均衡器"
    ExternalName: "外部服务别名"
```

## 网络监控

### 关键指标
| 指标 | 说明 | 阈值 |
|------|------|------|
| 带宽利用率 | 端口使用率 | < 70% |
| 延迟 | RTT | < 50ms |
| 丢包率 | Packet Loss | < 0.1% |
| Jitter | 延迟抖动 | < 10ms |

### 监控工具
```yaml
network_monitoring:
  infrastructure:
    - Prometheus + node_exporter
    - Grafana dashboards

  flow_analysis:
    - sFlow/RFlow
    - NetFlow/IPFIX

  packet_capture:
    - tcpdump
    - Wireshark
    - Zeek
```
