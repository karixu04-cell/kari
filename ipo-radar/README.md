# IPO Radar - IPO决策信息系统

IPO Radar 是一个综合性的 IPO（首次公开募股）决策信息系统，帮助投资者跟踪、分析和评估新上市股票的投资机会。

## 系统架构

```
ipo-radar/
├── pyproject.toml          # Poetry 依赖管理
├── Dockerfile              # 容器镜像定义
├── docker-compose.yml      # 服务编排
├── .env.example            # 环境变量模板
├── Makefile                # 常用命令快捷方式
├── src/
│   ├── radar/              # 新股监控 - 跟踪即将上市和近期 IPO
│   ├── screener/           # 基本面筛选 - 按财务指标筛选 IPO
│   ├── pattern/            # 形态识别 - 识别价格图表形态
│   ├── lockup/             # 禁售期跟踪 - 跟踪内部人禁售期到期
│   ├── sentiment/          # 情绪分析 - 分析市场情绪
│   ├── earnings/           # 业绩追踪 - 跟踪上市后业绩表现
│   ├── scorer/             # 综合评分 - 生成综合投资评分
│   ├── notifier.py         # 飞书通知 - 推送信号到飞书群
│   ├── scheduler.py        # 定时调度 - 自动扫描与通知
│   └── dashboard/          # 仪表盘 - Streamlit 交互式仪表盘
├── data/                   # 本地数据存储
└── tests/                  # 测试
```

## 核心模块

| 模块 | 功能 | 说明 |
|------|------|------|
| **radar** | 新股监控 | 从 SEC EDGAR 抓取 S-1/424B4 上市文件 |
| **screener** | 基本面筛选 | 财务指标评分 (0-100) |
| **pattern** | 形态识别 | IPO 底部形态检测 + 突破信号 |
| **lockup** | 禁售期跟踪 | 180 天禁售期到期倒计时 |
| **sentiment** | 情绪分析 | 新闻情绪评分 (-1.0 ~ +1.0) |
| **earnings** | 业绩追踪 | 首次财报日期跟踪 |
| **scorer** | 综合评分 | 多维度聚合 → STRONG / OPPORTUNITY / WATCH / NO_ACTION |
| **notifier** | 飞书通知 | 触发条件满足时推送飞书卡片消息 |
| **scheduler** | 定时调度 | 每日扫描、盘中突破检测、周度刷新 |
| **dashboard** | 可视化仪表盘 | Streamlit 交互式面板 (端口 8501) |

---

## 部署指南

### 前置要求

- Docker >= 20.10
- Docker Compose >= 2.0 (Docker Desktop 自带)
- (可选) NVIDIA GPU + nvidia-container-toolkit (用于 Ollama GPU 加速)

### 第一步：克隆项目

```bash
git clone <repo-url>
cd ipo-radar
```

### 第二步：配置环境变量

```bash
cp .env.example .env
```

编辑 `.env` 文件，填入必要的配置：

```bash
# 必填 - 飞书机器人 Webhook（用于接收通知）
# 获取方式：飞书群 → 设置 → 群机器人 → 添加自定义机器人 → 复制 Webhook 地址
FEISHU_WEBHOOK_URL=https://open.feishu.cn/open-apis/bot/v2/hook/你的webhook-id

# 可选 - 自定义观察名单（默认：CAVA,ARM,BIRK,CART,KPLT）
WATCHLIST=CAVA,ARM,BIRK,CART,KPLT

# 可选 - 如果启用 Ollama，设置为容器名
OLLAMA_HOST=http://ipo-radar-ollama:11434

# 可选 - Dashboard 端口（默认 8501）
DASHBOARD_PORT=8501
```

### 第三步：构建并启动

#### 方案 A：仅核心服务（推荐，无需 GPU）

```bash
# 构建镜像
make build

# 启动 dashboard + scheduler
make start

# 查看日志
make logs
```

启动后：
- Dashboard：浏览器访问 `http://localhost:8501`
- Scheduler：后台运行，自动执行定时任务并推送飞书通知

#### 方案 B：核心服务 + Ollama（GPU 加速情绪分析）

```bash
# 需要 NVIDIA GPU + nvidia-container-toolkit
make start-gpu

# 拉取模型（首次使用需要）
docker exec ipo-radar-ollama ollama pull qwen3:8b
```

#### 方案 C：核心服务 + Ollama（CPU 模式）

```bash
make start-cpu

# 拉取模型
docker exec ipo-radar-ollama ollama pull qwen3:8b
```

### 第四步：验证部署

```bash
# 查看服务状态
docker compose ps

# 查看日志
make logs

# 手动执行一次完整扫描（在 scheduler 容器内）
docker compose exec scheduler python -m src.scheduler --once

# 手动扫描指定股票
docker compose exec scheduler python -m src.scorer CAVA ARM
```

### 停止服务

```bash
make stop
```

---

## 定时任务说明

Scheduler 启动后自动执行以下任务：

| 时间 (美东) | 任务 | 说明 |
|-------------|------|------|
| 每日 8:30 | 全量扫描 | 扫描观察名单所有股票，有信号时推送飞书 |
| 每 15 分钟 (9:30-16:00) | 突破检测 | 盘中检测突破信号，触发时推送飞书 |
| 每日 16:30 | 形态更新 | 更新技术形态分析数据 |
| 每周日 18:00 | 周度刷新 | 刷新 IPO 日历和禁售期，有预警时推送飞书 |

## 飞书通知触发条件

| 条件 | 卡片颜色 | 说明 |
|------|---------|------|
| STRONG_OPPORTUNITY | 红色 | 强烈买入机会：突破确认 + 基本面 ≥60 + 情绪 ≥0.3 |
| 突破信号 | 红色 | IPO 底部突破确认 |
| 禁售期 ≤3 天 | 橙色 | 禁售期即将到期，注意抛压风险 |
| 首次财报 ≤3 天 | 蓝色 | 首次财报即将发布 |

---

## 本地开发

```bash
# 安装依赖
make setup

# 运行扫描
make scan TICKERS="CAVA ARM BIRK"

# 运行所有定时任务一次
make scan-all

# 启动本地 Dashboard
make dashboard

# 运行测试
make test

# 运行 lint
make lint
```

## 技术栈

- **数据获取**: requests, yfinance, sec-api
- **数据处理**: pandas, SQLAlchemy
- **AI/LLM**: LangChain, LiteLLM, Ollama (Qwen3-8B)
- **可视化**: Streamlit, Plotly
- **调度**: schedule
- **通知**: 飞书 Webhook
- **部署**: Docker, Docker Compose

## License

MIT
