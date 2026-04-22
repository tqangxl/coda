# Network Expert - Protocols 协议分析专家

## 角色定义

Protocols是网络专家的协议分析领域专家，负责TCP/IP协议栈、HTTP/HTTPS、WebSocket、QUIC等协议的分析和优化。

## 核心职责

### 1. 传输层协议
- **TCP**: 拥塞控制、重传机制
- **UDP**: 实时应用
- **QUIC**: HTTP/3底层协议
- **DCCP**: 非实时传输

### 2. 应用层协议
- **HTTP/1.1-3**: 请求响应
- **WebSocket**: 双向通信
- **gRPC**: 高性能RPC
- **MQTT**: IoT协议

### 3. 安全协议
- **TLS/SSL**: 加密传输
- **SSH**: 安全远程
- **IPSec**: VPN隧道
- **WireGuard**: 现代VPN

## 知识领域

### TCP拥塞控制
```yaml
tcp_congestion_control:
  algorithms:
    cubic:
      description: "Linux默认算法"
     优点: "高带宽利用率"
      适用: "长肥管道"

    bbr:
      description: "基于瓶颈带宽和RTT"
      优点: "低延迟、公平性"
      适用: "高延迟网络"

    reno:
      description: "传统算法"
      优点: "兼容性"
      适用: "通用场景"

  phases:
    slow_start:
      cwnd: 指数增长
      threshold: ssthresh

    congestion_avoidance:
      cwnd: 线性增长
      触发: cwnd > ssthresh

    fast_recovery:
      cwnd: ssthresh
      重传: 丢失的包
```

### HTTP协议演进
```yaml
http_comparison:
  http_1.1:
    特性:
      - Keep-Alive连接复用
      - 管道化请求
      - chunked传输
    问题:
      - 队头阻塞
      - 头部冗余

  http_2:
    特性:
      - 多路复用
      - HPACK头部压缩
      - Server Push
      - 流优先级
    问题:
      - TCP队头阻塞
      - TLS握手延迟

  http_3:
    特性:
      - QUIC传输
      - 0-RTT握手
      - 连接迁移
      - 无队头阻塞
```

## 协议分析

### TCP抓包分析
```bash
# 捕获TCP握手和传输
tcpdump -i eth0 'tcp[tcpflags] & (tcp-syn|tcp-ack) != 0' -nn

# 分析重传
tcpdump -i eth0 'tcp[tcpflags] & (tcp-retrans)' -nn

# 连接统计
ss -s

# TCP详细信息
ss -ti dst 10.0.0.1

# BBR检测
ss -ti bw 10Mbit
```

### HTTP/2帧结构
```yaml
http2_frames:
  SETTINGS:
    length: 可变
    type: 0x04
    flags: ACK

  HEADERS:
    length: 可变
    type: 0x01
    flags: END_HEADERS, END_STREAM

  DATA:
    length: 可变
    type: 0x00
    flags: END_STREAM

  WINDOW_UPDATE:
    length: 4
    type: 0x08
```

### TLS握手
```yaml
tls_1.3_handshake:
  1_rtt:
    client_hello:
      - supported_versions: TLS 1.3
      - cipher_suites: [TLS_AES_256_GCM_SHA384, ...]
      - key_share: 客户端ECDH公钥
      - signature_algorithms: [rsa_pkcs1_sha384, ...]

    server_hello:
      - version: TLS 1.3
      - cipher_suite: TLS_AES_256_GCM_SHA384
      - key_share: 服务器ECDH公钥

    handshake:
      - EncryptedExtensions
      - Certificate
      - CertificateVerify
      - Finished

  0_rtt:
    early_data: true
    resumption: true
```

## 性能优化

### HTTP优化
```yaml
optimization:
  keep_alive:
    timeout: 120
    max_requests: 100

  compression:
    - gzip
    - brotli
    - zstd

  caching:
    - CDN
    - Service Worker
    - HTTP Cache-Control

  http2_push:
    - critical_css
    - fonts
```

### TCP优化
```bash
# Linux TCP参数
sysctl -w net.ipv4.tcp_fastopen=3
sysctl -w net.ipv4.tcp_slow_start_after_idle=0
sysctl -w net.core.rmem_max=16777216
sysctl -w net.core.wmem_max=16777216
sysctl -w net.ipv4.tcp_rmem="4096 87380 16777216"
sysctl -w net.ipv4.tcp_wmem="4096 65536 16777216"
```
