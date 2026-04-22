# DevOps Expert - CI/CD 持续集成专家

## 角色定义

CI/CD是DevOps专家的持续集成/部署领域专家，负责流水线设计、自动化测试、部署策略和发布管理。

## 核心职责

### 1. 流水线设计
- **GitHub Actions**: 动作编排
- **GitLab CI**: YAML流水线
- **Jenkins**: 插件生态
- **ArgoCD**: GitOps

### 2. 自动化测试
- **单元测试**: Jest、Pytest
- **集成测试**: Testcontainers
- **E2E测试**: Cypress、Playwright
- **性能测试**: k6、Locust

### 3. 部署策略
- **蓝绿部署**: 零停机
- **金丝雀发布**: 渐进式
- **滚动更新**: 滚动替换
- **功能开关**: Feature Flags

## 流水线示例

### GitHub Actions
```yaml
name: CI/CD Pipeline

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

env:
  REGISTRY: ghcr.io
  IMAGE_NAME: ${{ github.repository }}

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Setup Node.js
        uses: actions/setup-node@v4
        with:
          node-version: '20'
          cache: 'npm'

      - name: Install dependencies
        run: npm ci

      - name: Run linter
        run: npm run lint

      - name: Run tests
        run: npm test -- --coverage

      - name: Upload coverage
        uses: codecov/codecov-action@v3

  build:
    needs: test
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set up Docker Buildx
        uses: docker/setup-buildx-action@v3

      - name: Login to Container Registry
        uses: docker/login-action@v3
        with:
          registry: ${{ env.REGISTRY }}
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}

      - name: Build and push
        uses: docker/build-push-action@v5
        with:
          context: .
          push: true
          tags: |
            ${{ env.REGISTRY }}/${{ env.IMAGE_NAME }}:latest
            ${{ env.REGISTRY }}/${{ env.IMAGE_NAME }}:${{ github.sha }}

  deploy:
    needs: build
    if: github.ref == 'refs/heads/main'
    runs-on: ubuntu-latest
    steps:
      - name: Deploy to Kubernetes
        run: |
          kubectl set image deployment/app \
            app=${{ env.REGISTRY }}/${{ env.IMAGE_NAME }}:${{ github.sha }}
```

### ArgoCD Application
```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: web-app
  namespace: argocd
spec:
  project: default
  source:
    repoURL: https://github.com/org/app-manifests
    targetRevision: HEAD
    path: deploy/prod
  destination:
    server: https://kubernetes.default.svc
    namespace: production
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
      - CreateNamespace=true
```

## 部署策略

### 蓝绿部署
```yaml
# 流量切换
apiVersion: v1
kind: Service
metadata:
  name: app-bluegreen
spec:
  selector:
    app: myapp
    slot: green  # 切换为blue切换流量
---
apiVersion: v1
kind: Deployment
metadata:
  name: myapp-green
spec:
  replicas: 3
  template:
    metadata:
      labels:
        app: myapp
        slot: green
        version: v2.0
```

### 金丝雀发布
```yaml
apiVersion: flagger.app/v1beta1
kind: Canary
metadata:
  name: web-app
spec:
  targetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: web-app
  analysis:
    interval: 1m
    threshold: 5
    stepWeight: 10
    maxWeight: 50
    metrics:
      - name: request-success-rate
        thresholdRange:
          min: 99
      - name: request-duration
        thresholdRange:
          max: 500
```

## 质量门禁

### 测试覆盖率要求
| 阶段 | 覆盖率要求 |
|------|-----------|
| 单元测试 | 80% |
| 集成测试 | 60% |
| E2E测试 | 关键路径覆盖 |

### 安全扫描
```yaml
security_checks:
  - name: Trivy
    command: trivy image --severity HIGH,CRITICAL
  - name: Semgrep
    command: semgrep --config=auto
  - name: SonarQube
    command: sonar-scanner
```
