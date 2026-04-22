#!/bin/bash
# AI Agent V2.0 - Linux/macOS 启动脚本
# 支持命名空间隔离、30分钟心跳、会话持久化

set -e

# =============================================
# 配置
# =============================================
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
SERVICE_NAME="ai-agents-v2"
NAMESPACE="ai_agents_v2"
HEARTBEAT_INTERVAL=1800  # 30分钟（秒）

# 配置目录
CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/ai-agents"
DATA_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/ai-agents"
LOG_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/ai-agents/logs"

# PID文件
PID_FILE="/tmp/$SERVICE_NAME.pid"

# SurrealDB配置
SURREALDB_HOST="${SURREALDB_HOST:-localhost}"
SURREALDB_PORT="${SURREALDB_PORT:-11001}"
SURREALDB_NAMESPACE="${SURREALDB_NAMESPACE:-$NAMESPACE}"
SURREALDB_DATABASE="${SURREALDB_DATABASE:-agent_system}"

# =============================================
# 辅助函数
# =============================================

log() {
    local level="$1"
    shift
    local message="[$(date '+%Y-%m-%d %H:%M:%S')] [$level] $*"
    echo "$message"

    # 确保日志目录存在
    mkdir -p "$LOG_DIR"
    echo "$message" >> "$LOG_DIR/agent-$(date '+%Y%m%d').log"
}

write_heartbeat() {
    cat > "$DATA_DIR/heartbeat.json" << EOF
{
    "timestamp": "$(date '+%Y-%m-%d %H:%M:%S')",
    "status": "running",
    "namespace": "$NAMESPACE",
    "uptime_seconds": $UPTIME_SECONDS,
    "memory_mb": $(ps -p $$ -o rss= 2>/dev/null || echo 0)
}
EOF
}

start_heartbeat_monitor() {
    log "INFO" "启动心跳监控（间隔: $((HEARTBEAT_INTERVAL/60))分钟）"

    (
        tick=0
        while true; do
            sleep "$HEARTBEAT_INTERVAL"
            tick=$((tick + 1))

            write_heartbeat

            echo "[$(date '+%Y-%m-%d %H:%M:%S')] [HEARTBEAT] Tick #$tick" >> "$LOG_DIR/agent-$(date '+%Y%m%d').log"
        done
    ) &

    HEARTBEAT_PID=$!
    echo $HEARTBEAT_PID > "$DATA_DIR/heartbeat.pid"
}

stop_heartbeat_monitor() {
    if [ -f "$DATA_DIR/heartbeat.pid" ]; then
        kill $(cat "$DATA_DIR/heartbeat.pid") 2>/dev/null || true
        rm -f "$DATA_DIR/heartbeat.pid"
        log "INFO" "心跳监控已停止"
    fi
}

save_session_summary() {
    local session_data="$1"

    local session_file="$DATA_DIR/sessions/$(date '+%Y%m%d-%H%M%S').json"
    mkdir -p "$(dirname "$session_file")"

    echo "$session_data" | jq -s '.[0] * .[1]' > "$session_file" 2>/dev/null || echo "$session_data" > "$session_file"

    log "INFO" "会话摘要已保存: $session_file"
}

check_environment() {
    log "INFO" "检查运行环境..."

    # 创建配置目录
    mkdir -p "$CONFIG_DIR" "$DATA_DIR" "$LOG_DIR"

    # 检查.env文件
    if [ ! -f "$CONFIG_DIR/.env" ]; then
        log "WARN" "未找到.env文件，创建默认配置..."
        cat > "$CONFIG_DIR/.env" << EOF
# AI Agents V2.0 环境配置
SURREALDB_HOST=localhost
SURREALDB_PORT=11001
SURREALDB_NAMESPACE=$NAMESPACE
SURREALDB_DATABASE=agent_system
SURREALDB_USER=root
SURREALDB_PASS=AgentSecurePass2026
WECHAT_WEBHOOK_URL=
LOG_LEVEL=INFO
EOF
    fi

    # 加载环境变量
    if [ -f "$CONFIG_DIR/.env" ]; then
        set -a
        source "$CONFIG_DIR/.env"
        set +a
    fi

    log "INFO" "环境检查完成"
}

# =============================================
# Systemd 服务安装
# =============================================

install_systemd() {
    log "INFO" "安装Systemd服务..."

    cat > "/etc/systemd/system/$SERVICE_NAME.service" << EOF
[Unit]
Description=AI Agent V2.0 System Service
After=network.target surrealdb.service
Wants=surrealdb.service

[Service]
Type=simple
User=$USER
WorkingDirectory=$PROJECT_ROOT
ExecStart=$SCRIPT_DIR/startup.sh
Restart=always
RestartSec=10
EnvironmentFile=$CONFIG_DIR/.env

# 日志配置
StandardOutput=append:$LOG_DIR/service.log
StandardError=append:$LOG_DIR/service-error.log

# 资源限制
LimitNOFILE=65536
MemoryMax=2G

[Install]
WantedBy=multi-user.target
EOF

    systemctl daemon-reload
    systemctl enable "$SERVICE_NAME.service"

    log "SUCCESS" "服务安装完成！"
    log "INFO" "运行以下命令启动服务:"
    log "INFO" "  sudo systemctl start $SERVICE_NAME"
    log "INFO" "  sudo systemctl status $SERVICE_NAME"
}

uninstall_systemd() {
    log "INFO" "卸载Systemd服务..."

    systemctl stop "$SERVICE_NAME.service" 2>/dev/null || true
    systemctl disable "$SERVICE_NAME.service" 2>/dev/null || true
    rm -f "/etc/systemd/system/$SERVICE_NAME.service"
    systemctl daemon-reload

    log "SUCCESS" "服务已卸载"
}

# =============================================
# 启动脚本
# =============================================

do_start() {
    log "========================================" "INFO"
    log "INFO" "AI Agent V2.0 启动中..." "INFO"
    log "INFO" "命名空间: $NAMESPACE" "INFO"
    log "========================================" "INFO"

    # 检查是否已运行
    if [ -f "$PID_FILE" ] && kill -0 $(cat "$PID_FILE") 2>/dev/null; then
        log "ERROR" "服务已在运行 (PID: $(cat "$PID_FILE"))"
        exit 1
    fi

    # 环境检查
    check_environment

    # 保存PID
    echo $$ > "$PID_FILE"

    # 启动心跳监控
    start_heartbeat_monitor

    # 记录启动信息
    SESSION_DATA=$(cat << EOF
{
    "start_time": "$(date '+%Y-%m-%d %H:%M:%S')",
    "pid": $$,
    "namespace": "$NAMESPACE",
    "pid_file": "$PID_FILE"
}
EOF
)

    # 清理函数
    cleanup() {
        log "INFO" "正在停止服务..."

        # 保存会话摘要
        SESSION_DATA=$(echo "$SESSION_DATA" | jq ".end_time = \"$(date '+%Y-%m-%d %H:%M:%S')\"")
        save_session_summary "$SESSION_DATA"

        # 停止心跳监控
        stop_heartbeat_monitor

        # 清理PID文件
        rm -f "$PID_FILE"

        log "SUCCESS" "服务已停止"
        exit 0
    }

    trap cleanup SIGINT SIGTERM

    # 检查Python环境
    if ! command -v python3 &> /dev/null; then
        log "ERROR" "未找到Python3，请先安装Python 3.10+"
        exit 1
    fi

    # 安装依赖
    if [ -f "$PROJECT_ROOT/requirements.txt" ]; then
        log "INFO" "安装Python依赖..."
        pip3 install -r "$PROJECT_ROOT/requirements.txt" -q
    fi

    # 启动后端服务
    log "INFO" "启动AI Agent后端服务..."

    cd "$PROJECT_ROOT"
    python3 -m uvicorn main:app --host 127.0.0.1 --port 8001 &

    BACKEND_PID=$!
    log "INFO" "后端服务已启动 (PID: $BACKEND_PID)"

    # 主循环
    log "INFO" "服务运行中，按 Ctrl+C 正常退出..."

    while true; do
        sleep 5

        # 检查后端进程
        if ! kill -0 $BACKEND_PID 2>/dev/null; then
            log "WARN" "后端进程意外退出，尝试重启..."
            sleep 5
            python3 -m uvicorn main:app --host 127.0.0.1 --port 8001 &
            BACKEND_PID=$!
            log "INFO" "后端服务已重启 (PID: $BACKEND_PID)"
        fi
    done
}

do_stop() {
    if [ -f "$PID_FILE" ]; then
        log "INFO" "正在停止服务..."
        kill $(cat "$PID_FILE") 2>/dev/null || true
        rm -f "$PID_FILE"
        log "SUCCESS" "服务已停止"
    else
        log "WARN" "服务未运行"
    fi
}

do_status() {
    echo "========================================"
    echo "  AI Agent V2.0 服务状态"
    echo "========================================"
    echo ""

    if [ -f "$PID_FILE" ] && kill -0 $(cat "$PID_FILE") 2>/dev/null; then
        echo "状态: 运行中"
        echo "PID: $(cat "$PID_FILE")"
        echo "命名空间: $NAMESPACE"
    else
        echo "状态: 未运行"
    fi

    echo ""

    if [ -f "$DATA_DIR/heartbeat.json" ]; then
        echo "最近心跳:"
        cat "$DATA_DIR/heartbeat.json" | jq -r '"  时间: \(.timestamp)\n  状态: \(.status)\n  命名空间: \(.namespace)"'
    fi
}

# =============================================
# 主逻辑
# =============================================

case "${1:-}" in
    start)
        do_start
        ;;
    stop)
        do_stop
        ;;
    restart)
        do_stop
        sleep 2
        do_start
        ;;
    status)
        do_status
        ;;
    install)
        if command -v systemctl &> /dev/null; then
            install_systemd
        else
            log "ERROR" "系统不支持Systemd"
            exit 1
        fi
        ;;
    uninstall)
        if command -v systemctl &> /dev/null; then
            uninstall_systemd
        else
            log "ERROR" "系统不支持Systemd"
            exit 1
        fi
        ;;
    *)
        echo @"
========================================
  AI Agent V2.0 - Linux/macOS 启动脚本
========================================

用法:
  $0 start      启动服务
  $0 stop       停止服务
  $0 restart    重启服务
  $0 status     查看状态
  $0 install    安装为系统服务（需sudo）
  $0 uninstall  卸载系统服务（需sudo）

配置:
  - 命名空间: $NAMESPACE
  - 心跳间隔: $((HEARTBEAT_INTERVAL/60))分钟
  - 配置目录: $CONFIG_DIR
  - 数据目录: $DATA_DIR
  - 日志目录: $LOG_DIR

"@
        ;;
esac
