#!/bin/bash

# 默认值
STACK_NAME="default-stack"
REGION="default-region"
declare -a TARGETS=()

# curl 参数配置（可调整）
MAX_TIME=10            # 单次最大执行时间（秒）
CONNECT_TIMEOUT=5      # 连接超时时间（秒）
RETRY_TIMES=2          # 重试次数
RETRY_DELAY=2          # 每次重试间隔（秒）

# ========================
# 工具函数
# ========================

get_timestamp() {
    date "+%Y-%m-%d %H:%M:%S"
}

check_url() {
    local url="$1"
    # 获取开始时间（毫秒）
    local start_time=$(date +%s)
    local start_ms=$(echo $((1000 + $(date +%-N)/1000000)) | cut -c2-)
    local start_time_ms="${start_time}${start_ms}"
    \curl -sSf \
         -m $MAX_TIME \
         --connect-timeout $CONNECT_TIMEOUT \
         --retry $RETRY_TIMES \
         --retry-delay $RETRY_DELAY \
         "$url" > /dev/null
    local exit_code=$?
    # 获取结束时间（毫秒）
    local end_time=$(date +%s)
    local end_ms=$(echo $((1000 + $(date +%-N)/1000000)) | cut -c2-)
    local end_time_ms="${end_time}${end_ms}"
    # 计算耗时（秒，保留一位小数）
    local duration_ms=$((end_time_ms - start_time_ms))
    local duration_sec=$(awk "BEGIN {printf \"%.1f\", $duration_ms / 1000}")
    echo "$exit_code $duration_sec"
}

# ========================
# 解析命令行参数
# ========================

while [[ $# -gt 0 ]]; do
    key="$1"

    case $key in
        --stack)
            STACK_NAME="$2"
            shift
            shift
            ;;
        --region)
            REGION="$2"
            shift
            shift
            ;;
        --target)
            TARGETS+=("$2")
            shift
            shift
            ;;
        --config)
            CONFIG_FILE="$2"
            if [ -f "$CONFIG_FILE" ]; then
                source "$CONFIG_FILE"
            else
                echo "Error: Config file '$CONFIG_FILE' not found."
                exit 1
            fi
            shift
            shift
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

# 如果没有指定 target，使用默认示例
if [ ${#TARGETS[@]} -eq 0 ]; then
    echo "No targets provided. Using example targets."
    TARGETS=(
        "public_api:http://example.com"
        "private_api:http://localhost:8080"
    )
fi

# ========================
# 输出报告
# ========================

clear
echo "ComputeNest Curl Health Check Report"
echo "========================"
echo
echo "Stack: $STACK_NAME"
echo "Region: $REGION"
echo "Timestamp: $(get_timestamp)"
echo
echo "Health Check Results:"
echo "┌──────────────────────┬────────────────────────────────────────────┬───────────┬─────────────┬─────────────┐"
echo "│ Target               │ URL                                        │ Status    │ Duration    │ Exit Code   │"
echo "├──────────────────────┼────────────────────────────────────────────┼───────────┼─────────────┼─────────────┤"


for item in "${TARGETS[@]}"; do
    target=$(echo "$item" | cut -d: -f1)
    url=$(echo "$item" | cut -d: -f2-)
    read exit_code duration_sec <<< "$(check_url "$url")"

    if [ "$exit_code" -eq 0 ]; then
        status="✓ Success"
    else
        status="✗ FAIL"
    fi

    printf "│ %-20s │ %-42s │ %-11s │ %10ss │ %11s │\n" \
           "$target" "$url" "$status" "$duration_sec" "$exit_code"
done

echo "└──────────────────────┴────────────────────────────────────────────┴───────────┴─────────────┴─────────────┘"
