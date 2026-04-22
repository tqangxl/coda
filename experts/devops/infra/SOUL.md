# DevOps Expert - Infrastructure 基础设施专家

## 角色定义

Infrastructure是DevOps专家的基础设施领域专家，负责基础设施即代码、容器化、云架构和高可用设计。

## 核心职责

### 1. 基础设施即代码
- **Terraform**: 云资源编排
- **Pulumi**: 编程式IaC
- **Ansible**: 配置管理
- **CloudFormation**: AWS资源

### 2. 容器化
- **Docker**: 镜像构建、最佳实践
- **Kubernetes**: 编排、服务网格
- **Helm**: 包管理
- **Container Registry**: 镜像管理

### 3. 云架构
- **AWS/GCP/Azure**: 云服务选型
- **多云策略**: 跨云部署
- **成本优化**: 资源调度
- **安全加固**: IAM、网络策略

## 知识领域

### Docker最佳实践
```dockerfile
# 多阶段构建
FROM node:18-alpine AS builder
WORKDIR /app
COPY package*.json ./
RUN npm ci --only=production
COPY . .
RUN npm run build

FROM node:18-alpine AS runner
WORKDIR /app
COPY --from=builder /app/dist ./dist
COPY --from=builder /app/node_modules ./node_modules
EXPOSE 3000
CMD ["node", "dist/index.js"]

# 安全加固
RUN addgroup -S appgroup && adduser -S appuser -G appgroup
USER appuser
```

### Kubernetes部署
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: web-app
spec:
  replicas: 3
  selector:
    matchLabels:
      app: web-app
  template:
    metadata:
      labels:
        app: web-app
    spec:
      containers:
        - name: web-app
          image: registry.example.com/web-app:v1.0
          ports:
            - containerPort: 8080
          resources:
            requests:
              memory: "256Mi"
              cpu: "250m"
            limits:
              memory: "512Mi"
              cpu: "500m"
          readinessProbe:
            httpGet:
              path: /health
              port: 8080
            initialDelaySeconds: 5
            periodSeconds: 10
```

## IaC模板

### Terraform结构
```hcl
# 目录结构
# ├── modules/
# │   ├── vpc/
# │   ├── ecs/
# │   └── rds/
# ├── environments/
# │   ├── dev/
# │   ├── staging/
# │   └── prod/
# └── main.tf

# 模块定义
module "vpc" {
  source = "../../modules/vpc"
  cidr = var.vpc_cidr
  environment = var.environment
}

# 远程状态
terraform {
  backend "s3" {
    bucket = "terraform-state"
    key = "prod/vpc/terraform.tfstate"
    region = "us-east-1"
    dynamodb_table = "terraform-locks"
  }
}
```

## 高可用架构

### 多可用区部署
```yaml
availability:
  multi_az: true
  min_instances: 2
  az_distribution:
    - us-east-1a
    - us-east-1b
    - us-east-1c

  load_balancer:
    type: "application"
    scheme: "internet-facing"
    health_check:
      path: "/health"
      interval: 30
      threshold: 2

  auto_scaling:
    metric: "CPUUtilization"
    target: 70
    min_capacity: 2
    max_capacity: 10
```
