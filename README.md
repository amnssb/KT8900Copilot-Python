# KT8900Copilot-Python

基于 KT8900 远程控制场景的 Python 实现版本，面向玩客云/NAT 环境，支持：

- 低延迟语音通联（浏览器直连后端 WSS）
- PTT/COR 控制
- APRS 功能（按权限开放）
- 管理面板（音频/串口/APRS/用户管理）
- Cloudflare Worker 控制面代理

---

## 项目链接

- 当前仓库：`https://github.com/amnssb/KT8900Copilot-Python`
- 原客户端项目：`https://github.com/odorajbotoj/kt8900copilot`
- 原服务端项目：`https://github.com/odorajbotoj/kt8900copilot-server`

---

## 架构说明（推荐生产）

采用“控制面 / 数据面分离”架构：

```text
浏览器
  ├─ HTTPS -> Cloudflare Worker -> 后端 API (管理面)
  └─ WSS   -> 后端 WebSocket      (语音数据面直连)
```

为什么这么做：

- 管理接口对延迟不敏感，走 Worker 方便统一入口。
- 语音链路对延迟敏感，必须避免 Worker 反向代理绕路。

---

## 主要功能

- 实时语音：多客户端同组通话，支持 PTT 发射控制。
- 当前发话人显示：前端实时显示“谁在说话”。
- 客户端权限：按用户控制 `can_tx` / `can_aprs`。
- APRS 集成：可选 Direwolf，支持位置/信标/消息。
- 配置管理：支持 Web 管理面板 + API + CLI。

---

## 目录结构

```text
KT8900Copilot-Python/
├── server/
│   ├── main.py                 # WebSocket 主服务（语音/PTT/COR）
│   ├── api_server.py           # 管理 API 服务
│   ├── config_manager.py       # 配置读写与客户端管理
│   ├── audio_manager.py        # 音频处理
│   ├── serial_controller.py    # 串口/ESP32 控制
│   ├── aprs_engine.py          # APRS 引擎
│   ├── direwolf_integration.py # Direwolf 集成
│   ├── auth_token.py           # WS 短期令牌签发/校验
│   ├── config.json             # 运行配置
│   └── requirements.txt
├── frontend/
│   ├── index.html              # 前端主页面
│   ├── script.js               # 前端逻辑
│   └── style.css
├── cloudflare_workers/
│   └── worker.js               # 控制面 Worker（不代理语音 WS）
├── scripts/
│   ├── install.sh              # 安装 + 初始化脚本
│   ├── bootstrap_config.py     # 生成默认 config.json
│   └── ktctl.py                # CLI 管理工具
├── docs/
│   └── deployment-cn.md        # 中国大陆部署指南
└── experimental/               # 实验性代码（不用于生产）
```

---

## 快速开始

### 方式 A：远程一键安装（推荐新机）

```bash
curl -fsSL https://raw.githubusercontent.com/amnssb/KT8900Copilot-Python/main/scripts/install.sh | \
  sudo KT_GH_REPO=amnssb/KT8900Copilot-Python KT_GH_REF=main bash
```

生产建议固定版本：

```bash
curl -fsSL https://raw.githubusercontent.com/amnssb/KT8900Copilot-Python/v1.1.0/scripts/install.sh | \
  sudo KT_GH_REPO=amnssb/KT8900Copilot-Python KT_GH_REF=v1.1.0 bash
```

安装脚本会交互要求：

- 电台名称（`radio.name`）
- 默认管理员 `client_id`
- 默认管理员显示名
- 默认管理员 `passkey`

并自动生成默认配置文件。

### 方式 B：本地仓库安装

```bash
sudo bash scripts/install.sh
```

---

## 运行服务

建议开两个进程：

```bash
# 1) 语音/WS 主服务
cd server
python3 main.py

# 2) 管理 API（另一个终端）
cd server
python3 api_server.py
```

默认端口：

- WS：`8765`
- API：`8080`

---

## Cloudflare Worker 配置

文件：`cloudflare_workers/worker.js`

Worker 环境变量：

```text
FRONTEND_ORIGIN=https://your-frontend.pages.dev
API_ORIGIN=https://admin.your-domain.com
WS_URL=wss://radio.your-domain.com
CLIENT_ID=user01
PASSKEY=user01-password
```

注意：

- Worker 不代理 WebSocket 语音流。
- Worker 会注入 `/config.js` 给前端。
- 默认禁止把 `CLIENT_ID=admin` 暴露到前端配置。

---

## 鉴权流程

### 推荐流程（生产）

1. 前端调用：`POST /api/auth/ws-token`
2. API 校验 `client_id/passkey` 并返回短期 token
3. 前端连接：`wss://.../?token=<token>`
4. 后端校验 token 后放行

### 兼容流程（保留）

仍支持 challenge-response：

- 后端下发随机挑战
- 客户端计算摘要 `SHA256(client_id + random_hex + passkey)` 前 16 字节
- 后端验证通过后上线

---

## 用户与权限管理

### 默认管理员

安装脚本会创建默认管理员（`client_type=3`），用于后续用户管理。

### 在管理面板新增用户

管理员可新增用户并配置：

- `can_tx`：允许语音发射
- `can_aprs`：允许 APRS

### 生效说明

当前 `main.py` 启动时加载客户端列表。新增用户后建议重启 `main.py` 以确保主服务读取最新配置。

---

## 当前发话人显示

后端在 `ptt_status` 广播中附带身份信息：

```json
{"type":"ptt_status","active":true,"from":"BG4QBF","from_id":"user01","from_type":2}
```

前端会显示：

- 发话人名称
- 发话人类型（电台设备/普通用户/管理员）

---

## 配置文件说明

主配置：`server/config.json`

关键字段：

- `websocket.host/port`：WS 服务监听
- `audio.sample_rate/chunk_size/preset`：音频参数
- `serial.port/baudrate`：串口控制
- `clients[]`：客户端账号与权限
- `aprs`：APRS 参数
- `api.host/port`：管理 API 监听
- `radio.name`：电台站点名称（安装时可配置）

---

## CLI 管理工具

脚本：`scripts/ktctl.py`

示例：

```bash
python3 scripts/ktctl.py status
python3 scripts/ktctl.py audio list
python3 scripts/ktctl.py audio set wideband
python3 scripts/ktctl.py client list
python3 scripts/ktctl.py client add user02 -n "User 02" -t 2 --no-tx
```

---

## API 关键接口

管理 API（默认 `:8080`）：

- `POST /api/auth/ws-token`：签发 WS 短期令牌
- `GET /api/config` / `PUT /api/config`
- `GET /api/clients` / `POST /api/clients` / `PUT /api/clients/{id}` / `DELETE /api/clients/{id}`
- `GET /api/audio/info` / `POST /api/audio/preset`
- `GET /api/aprs` / `PUT /api/aprs`

---

## 中国大陆部署建议

请优先参考：`docs/deployment-cn.md`

核心原则：

- 语音 WSS 直连后端（低延迟）
- 管理 API 走 Worker（统一入口）

---

## 常见问题

### 1) 前端能打开但语音连不上

- 检查 `WS_URL` 是否可直连（浏览器网络面板）
- 检查证书和域名匹配（必须 `wss://`）
- 检查穿透节点是否支持 WebSocket

### 2) 验证失败

- 检查 `client_id/passkey` 是否与 `config.json` 一致
- 检查 Worker 注入的 `/config.js` 内容
- 检查 `/api/auth/ws-token` 是否成功返回 token

### 3) 延迟高

- 确认语音没有经过 Worker
- 优先使用国内/近距离穿透节点
- 调整 `audio.chunk_size`（建议 160 起步）

---

## 许可证

MIT

---

## AIGC 声明

本项目完全为 AI 生成，使用了以下模型与工具：

- gpt5.3codex
- kimik20905
- kimik2.5
- glm5
- glm4.7
- minimaxm2.5
- deepseek3.2v
- gemini3.1pro

并使用 OpenCode 编辑器生成。
