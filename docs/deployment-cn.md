# 中国大陆部署指南（结构化版）

本指南面向玩客云 Armbian（ARM 32 位）与同类 Linux 设备，覆盖公网与内网穿透两种部署方式。

---

## 1. 目标架构

推荐采用控制面/数据面分离：

```text
浏览器
  ├─ HTTPS -> Cloudflare Worker -> 后端 API（管理）
  └─ WSS   -> 后端 WebSocket      （语音直连）
```

优点：

- 管理接口统一入口，便于运维。
- 语音不绕 Worker，延迟更低。

---

## 2. 部署前准备

### 2.1 服务器要求

- 系统：Armbian / Debian（ARM 32 位可用）
- Python 3.10+
- 可用串口（用于 ESP32）
- 可用音频设备（USB 声卡）

### 2.2 域名与入口

建议准备两个域名：

- `radio.your-domain.com`：语音 WSS
- `admin.your-domain.com`：管理 API

公网 IP 与 NAT 穿透均可用，只要最终浏览器访问是有效的 `https/wss`。

---

## 3. 一键安装

```bash
curl -fsSL https://raw.githubusercontent.com/amnssb/KT8900Copilot-Python/main/scripts/install.sh | \
  sudo KT_GH_REPO=amnssb/KT8900Copilot-Python KT_GH_REF=main bash
```

安装脚本会：

- 安装依赖
- 拉取项目
- 交互生成 `config.json`（电台名称、默认管理员）
- 安装并启用 systemd 服务

---

## 4. 服务管理（systemd）

安装完成后默认启用两个服务：

- `kt8900copilot.service`（主服务，WS）
- `kt8900copilot-api.service`（管理 API）

常用命令：

```bash
sudo systemctl status kt8900copilot --no-pager
sudo systemctl status kt8900copilot-api --no-pager

sudo systemctl restart kt8900copilot
sudo systemctl restart kt8900copilot-api

sudo journalctl -u kt8900copilot -f
sudo journalctl -u kt8900copilot-api -f
```

---

## 5. Cloudflare Worker 配置

Worker 文件：`cloudflare_workers/worker.js`

环境变量：

```text
FRONTEND_ORIGIN=https://your-frontend.pages.dev
API_ORIGIN=https://admin.your-domain.com
WS_URL=wss://radio.your-domain.com
CLIENT_ID=user01
PASSKEY=user01-password
```

注意：

- Worker 不代理语音 WebSocket。
- Worker 提供 `/config.js` 注入前端运行时参数。
- 默认不允许把管理员账号注入前端配置。

---

## 6. 证书与穿透

### 6.1 公网 IP 场景

- 可直接使用 443（推荐）
- 反向代理入口（Nginx/Caddy）终止 TLS

### 6.2 NAT/内网穿透场景

- 可使用高位端口（如 `24443` / `28080`）
- 建议使用 DNS-01 方式签发证书
- 示例：
  - `wss://radio.your-domain.com:24443`
  - `https://admin.your-domain.com:28080`

证书必须与访问域名一致，否则浏览器会拒绝 WSS。

---

## 7. ESP32-C3 刷写 MicroPython

### 7.1 Thonny（推荐）

1. 安装并打开 Thonny
2. 选择解释器 `MicroPython (ESP32)`
3. 烧录 ESP32-C3 固件
4. 上传 `esp32_c3/main.py`

### 7.2 命令行（esptool）

```bash
pip install esptool
esptool.py --chip esp32c3 --port /dev/ttyUSB0 erase_flash
esptool.py --chip esp32c3 --port /dev/ttyUSB0 --baud 460800 write_flash -z 0x0 firmware.bin
```

刷写后用 Thonny 或 mpremote 上传 `esp32_c3/main.py`。

---

## 8. 用户与鉴权

### 8.1 推荐流程

1. 前端调用 `/api/auth/ws-token`
2. 获取短期 token
3. 连接 `wss://.../?token=<token>`
4. 后端验证后放行

### 8.2 权限管理

管理员在面板中可创建用户并设置：

- `can_tx`：语音发射权限
- `can_aprs`：APRS 权限

新增用户后建议重启主服务以加载最新列表。

---

## 9. 验收清单

1. `GET /healthz` 返回 Worker 正常
2. `GET /config.js` 返回注入配置
3. 前端 WS 实际目标为 `WS_URL`（非 Worker）
4. `/api/auth/ws-token` 能返回 token
5. PTT 发话时“当前发话人”正确显示（例如 `BA4SLT`）
6. 松开 PTT 后状态回到待机

---

## 10. 故障排查

### 10.1 前端开了但语音断

- 检查 `WS_URL` 可达性
- 检查证书链完整性
- 检查反代是否透传 WebSocket Upgrade 头

### 10.2 token 获取失败

- 检查 `API_ORIGIN` 配置
- 检查 `client_id/passkey` 是否正确
- 查看 API 日志 `journalctl -u kt8900copilot-api -f`

### 10.3 延迟高

- 确认语音未经过 Worker
- 优先国内就近节点
- 调整 `audio.chunk_size`（建议 160）
