# 部署方案（中国大陆）：前端走 CF，语音直连后端

本文档对应当前代码实现：

- Cloudflare Worker 仅负责：
  - 前端静态站点转发
  - 管理 API 转发（`/api/*`）
  - 运行时配置注入（`/config.js`）
- 语音 WebSocket 不经过 Worker，浏览器直连后端穿透域名。

这样做的原因：

- 管理流量对延迟不敏感，走 Worker 更方便。
- 语音流量对延迟敏感，必须减少跨境绕路。

---

## 1. 最终链路

```text
浏览器
  ├─ HTTPS -> Worker -> API_ORIGIN (管理接口)
  └─ WSS   -> WS_URL (语音直连后端)
```

---

## 2. 你需要准备的地址

- `FRONTEND_ORIGIN`：前端静态站点地址（建议 Cloudflare Pages）
- `API_ORIGIN`：玩客云管理接口地址（例如穿透后的 `https://admin.xxx.com`）
- `WS_URL`：玩客云语音 WS 地址（例如穿透后的 `wss://radio.xxx.com`）

说明：

- `API_ORIGIN` 和 `WS_URL` 可以是不同子域名。
- 若使用自建穿透，务必保证 TLS 证书有效，否则浏览器无法建立 `wss`。

---

## 3. Worker 变量配置

在 Cloudflare Worker 里设置以下环境变量：

```text
FRONTEND_ORIGIN=https://your-frontend.pages.dev
API_ORIGIN=https://admin.your-domain.com
WS_URL=wss://radio.your-domain.com
CLIENT_ID=user01
PASSKEY=user01-password
```

其中：

- `CLIENT_ID` / `PASSKEY` 会注入到 `/config.js`，供前端读取。
- 生产环境必须使用最小权限账号，禁止注入管理员账号。

---

## 4. 前端行为（当前已支持）

`frontend/index.html` 已加载：

- `/config.js`
- `script.js`

`frontend/script.js` 会优先读取：

- `window.APP_CONFIG.WS_URL`
- `window.APP_CONFIG.API_BASE`
- `window.APP_CONFIG.CLIENT_ID`
- `window.APP_CONFIG.PASSKEY`

因此无需重新打包前端即可切换后端地址。

---

## 5. 后端端口建议

建议分离端口：

- `8765`：语音 WebSocket（WS_URL）
- `8080`：管理 API（API_ORIGIN）

穿透映射示例：

```text
radio.your-domain.com -> 127.0.0.1:8765
admin.your-domain.com -> 127.0.0.1:8080
```

---

## 6. 验证步骤

1. 检查 Worker 健康：

```text
GET https://<worker-domain>/healthz
```

2. 检查配置注入：

```text
GET https://<worker-domain>/config.js
```

3. 浏览器打开站点，确认控制台里 WS 连接目标为 `WS_URL`。

4. 检查令牌流程：

```text
POST https://<worker-domain>/api/auth/ws-token
```

前端应先拿到短期令牌，再连接：

```text
wss://radio.your-domain.com/?token=<token>
```

5. 开始通联，观察延迟是否较 Worker 代理方案明显下降。

6. 发话人显示验证：
   - 任意客户端按下 PTT
   - 其他客户端界面应显示“当前发话人=该客户端用户名”
   - 松开 PTT 后应恢复“待机 / 空闲信道”

---

## 7. 常见问题

### 7.1 前端能开但语音连不上

- 检查 `WS_URL` 是否 `wss://`。
- 检查证书是否匹配域名。
- 检查穿透服务是否放行 WS 协议。

### 7.2 管理面可用但音频延迟仍高

- 确认语音未经过 Worker。
- 确认穿透节点是否在国内。
- 确认后端 `chunk_size` 和前端采样率匹配。

### 7.3 Worker 返回 426（Upgrade Required）

这是预期行为：Worker 不再代理 WebSocket。
