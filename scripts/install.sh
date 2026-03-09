#!/bin/bash

# KT8900 Copilot - 玩客云环境安装脚本
# 用于安装 Python、ALSA、Direwolf 等依赖

set -e  # 遇到任何错误立即退出

echo "====================================="
echo "KT8900 Copilot - 环境安装脚本"
echo "====================================="

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
WORK_DIR="/opt/kt8900copilot"

GITHUB_REPO="${KT_GH_REPO:-}"
GITHUB_REF="${KT_GH_REF:-main}"

# 检查是否为 root 用户
if [ "$EUID" -ne 0 ]; then
    echo "请使用 sudo 运行此脚本"
    exit 1
fi

# 更新软件包列表
echo "[1/8] 更新软件包列表..."
apt update

# 安装基础工具
echo "[2/8] 安装基础工具 (git, curl, vim)..."
for pkg in git curl vim build-essential; do
    if dpkg -l | grep -q "^ii  $pkg "; then
        echo "$pkg 已安装，跳过"
    else
        apt install -y $pkg
    fi
done

# 安装 Python 3 和 pip
echo "[3/8] 安装 Python 3 和 pip..."
for pkg in python3 python3-pip python3-dev; do
    if dpkg -l | grep -q "^ii  $pkg "; then
        echo "$pkg 已安装，跳过"
    else
        apt install -y $pkg
    fi
done

# 安装 ALSA 音频库
echo "[4/8] 安装 ALSA 音频库和工具..."
for pkg in alsa-utils alsa-tools libasound2-dev; do
    if dpkg -l | grep -q "^ii  $pkg "; then
        echo "$pkg 已安装，跳过"
    else
        apt install -y $pkg
    fi
done

# 安装 PortAudio (用于 PyAudio)
echo "[5/8] 安装 PortAudio..."
apt install -y portaudio19-dev

# 安装 Direwolf (APRS 调制解调器)
echo "[6/8] 安装 Direwolf..."
apt install -y direwolf

# 安装 Python 依赖包
echo "[7/8] 安装 Python 依赖包..."
pip3 install --upgrade pip
pip3 install 'websockets>=11.0'
pip3 install 'pyserial>=3.5'

# 拉取/更新项目代码（可选）
echo ""
echo "同步项目代码..."
if [ -z "$GITHUB_REPO" ]; then
    read -rp "GitHub 仓库 (user/repo，留空则使用本地目录): " GITHUB_REPO
fi

if [ -n "$GITHUB_REPO" ]; then
    REPO_URL="https://github.com/${GITHUB_REPO}.git"
    echo "使用远程仓库: $REPO_URL (分支: $GITHUB_REF)"
    if [ -d "$WORK_DIR/.git" ]; then
        git -C "$WORK_DIR" fetch origin "$GITHUB_REF"
        git -C "$WORK_DIR" checkout "$GITHUB_REF"
        git -C "$WORK_DIR" pull --ff-only origin "$GITHUB_REF"
    else
        rm -rf "$WORK_DIR"
        git clone --depth 1 --branch "$GITHUB_REF" "$REPO_URL" "$WORK_DIR"
    fi
    PROJECT_ROOT="$WORK_DIR"
    SCRIPT_DIR="$PROJECT_ROOT/scripts"
else
    echo "未指定远程仓库，使用当前本地目录: $PROJECT_ROOT"
fi

if [ ! -f "$SCRIPT_DIR/bootstrap_config.py" ]; then
    echo "错误: 未找到 bootstrap_config.py ($SCRIPT_DIR/bootstrap_config.py)"
    echo "请设置 KT_GH_REPO 或在项目根目录执行安装脚本"
    exit 1
fi

if [ -f "$PROJECT_ROOT/server/requirements.txt" ]; then
    echo "安装项目依赖: $PROJECT_ROOT/server/requirements.txt"
    pip3 install -r "$PROJECT_ROOT/server/requirements.txt"
fi

# 检查 USB 声卡设备
echo "[8/8] 检查音频设备..."
ls -la /dev/snd/

echo ""
echo "初始化默认站点与管理员配置..."
read -rp "电台名称 (默认: KT8900 Station): " RADIO_NAME
RADIO_NAME=${RADIO_NAME:-KT8900 Station}

read -rp "默认管理员 client_id (默认: admin): " ADMIN_ID
ADMIN_ID=${ADMIN_ID:-admin}

read -rp "默认管理员显示名 (默认: Admin User): " ADMIN_NAME
ADMIN_NAME=${ADMIN_NAME:-Admin User}

while true; do
    read -rsp "默认管理员 passkey (必填): " ADMIN_PASSKEY
    echo ""
    if [ -n "$ADMIN_PASSKEY" ]; then
        break
    fi
    echo "passkey 不能为空，请重新输入"
done

# 创建工作目录
echo ""
echo "创建工作目录: $WORK_DIR"
mkdir -p "$WORK_DIR"
mkdir -p "$WORK_DIR/server"

python3 "$SCRIPT_DIR/bootstrap_config.py" \
    --output "$WORK_DIR/server/config.json" \
    --radio-name "$RADIO_NAME" \
    --admin-id "$ADMIN_ID" \
    --admin-name "$ADMIN_NAME" \
    --admin-passkey "$ADMIN_PASSKEY" \
    --force

if [ -d "$PROJECT_ROOT/server" ] && [ "$PROJECT_ROOT" != "$WORK_DIR" ]; then
    python3 "$SCRIPT_DIR/bootstrap_config.py" \
        --output "$PROJECT_ROOT/server/config.json" \
        --radio-name "$RADIO_NAME" \
        --admin-id "$ADMIN_ID" \
        --admin-name "$ADMIN_NAME" \
        --admin-passkey "$ADMIN_PASSKEY" \
        --force
    echo "项目目录配置已更新: $PROJECT_ROOT/server/config.json"
fi

# 创建音频配置目录
mkdir -p /var/lib/kt8900/audio

# 添加用户到 audio 用户组
echo ""
echo "将当前用户添加到 audio 用户组..."
USER=$(logname 2>/dev/null || echo $SUDO_USER)
if [ -n "$USER" ]; then
    usermod -a -G audio "$USER"
    echo "用户 $USER 已添加到 audio 组"
    echo "请注销并重新登录以使更改生效"
fi

# 配置 ALSA (可选)
echo ""
echo "配置 ALSA..."
if [ -f /etc/asound.conf ]; then
    echo "备份现有 asound.conf..."
    cp /etc/asound.conf /etc/asound.conf.backup
fi

# 安装并启用 systemd 服务
echo ""
echo "安装 systemd 服务..."
if [ -f "$PROJECT_ROOT/scripts/kt8900copilot.service" ]; then
    cp "$PROJECT_ROOT/scripts/kt8900copilot.service" /etc/systemd/system/kt8900copilot.service
fi
if [ -f "$PROJECT_ROOT/scripts/kt8900copilot-api.service" ]; then
    cp "$PROJECT_ROOT/scripts/kt8900copilot-api.service" /etc/systemd/system/kt8900copilot-api.service
fi

systemctl daemon-reload
systemctl enable kt8900copilot.service
systemctl enable kt8900copilot-api.service
systemctl restart kt8900copilot.service
systemctl restart kt8900copilot-api.service

echo ""
echo "====================================="
echo "安装完成！"
echo "====================================="
echo ""
echo "后续步骤："
echo "1. 检查 USB 声卡: arecord -l 和 aplay -l"
echo "2. 测试录音: arecord -f cd -d 5 test.wav"
echo "3. 测试播放: aplay test.wav"
echo "4. 检查 Direwolf: direwolf -h"
echo "5. 项目目录: $PROJECT_ROOT"
echo "6. 检查默认配置: $WORK_DIR/server/config.json"
echo "7. 服务状态: systemctl status kt8900copilot --no-pager"
echo "8. API状态: systemctl status kt8900copilot-api --no-pager"
echo "9. 查看日志: journalctl -u kt8900copilot -f"
echo ""
