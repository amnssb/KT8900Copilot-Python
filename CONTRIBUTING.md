# 贡献指南

欢迎贡献 KT8900Copilot 项目！

## 如何贡献

### 1. 报告问题
- 使用 GitHub Issues 报告 bug
- 描述复现步骤
- 提供相关日志

### 2. 添加功能
- Fork 本仓库
- 创建功能分支 (`git checkout -b feature/amazing-feature`)
- 提交更改 (`git commit -m 'Add amazing feature'`)
- 推送分支 (`git push origin feature/amazing-feature`)
- 创建 Pull Request

### 3. 代码规范
- Python: 遵循 PEP 8
- JavaScript: 遵循 ESLint
- 提交信息清晰明了

## 开发环境设置

```bash
# 克隆项目
git clone https://github.com/your-username/kt8900copilot.git
cd kt8900copilot/KT8900Copilot-Python/server

# 创建虚拟环境
python3 -m venv venv
source venv/bin/activate  # Linux/Mac
# 或 venv\Scripts\activate  # Windows

# 安装依赖
pip install -r requirements.txt

# 运行测试
python main.py
```

## 项目结构

```
KT8900Copilot-Python/
├── server/                 # Python 服务端
│   ├── main.py           # 主程序
│   ├── audio_manager.py  # 音频管理
│   ├── serial_controller.py # 串口控制
│   └── ...
├── frontend/              # 前端页面
├── esp32_c3/             # ESP32-C3 固件
├── cloudflare_workers/   # Cloudflare Worker
└── scripts/              # 辅助脚本
```

## 测试

在提交 PR 之前，请确保：

1. 代码能正常运行
2. 没有语法错误
3. 遵循项目代码风格

## 许可证

通过贡献代码，你同意你的贡献将按照 MIT 许可证发布。