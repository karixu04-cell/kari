# IPO Radar - IPO决策信息系统

IPO Radar 是一个综合性的 IPO（首次公开募股）决策信息系统，帮助投资者跟踪、分析和评估新上市股票的投资机会。

## 系统架构

```
ipo-radar/
├── pyproject.toml          # Poetry 依赖管理
├── .env.example            # API 密钥模板
├── src/
│   ├── radar/              # 新股监控 - 跟踪即将上市和近期 IPO
│   ├── screener/           # 基本面筛选 - 按财务指标筛选 IPO
│   ├── pattern/            # 形态识别 - 识别价格图表形态
│   ├── lockup/             # 禁售期跟踪 - 跟踪内部人禁售期到期
│   ├── sentiment/          # 情绪分析 - 分析市场情绪
│   ├── earnings/           # 业绩追踪 - 跟踪上市后业绩表现
│   ├── scorer/             # 综合评分 - 生成综合投资评分
│   └── dashboard/          # 仪表盘 - Streamlit 交互式仪表盘
├── data/                   # 本地数据存储
├── tests/                  # 测试
└── docs/                   # 文档
```

## 核心模块

| 模块 | 功能 | 关键类 |
|------|------|--------|
| **radar** | 监控即将上市和近期 IPO | `IPORadar`, `IPOEntry` |
| **screener** | 基于财务指标筛选 | `FundamentalScreener`, `FundamentalMetrics` |
| **pattern** | 技术形态识别 | `PatternRecognizer`, `PatternMatch` |
| **lockup** | 禁售期到期跟踪 | `LockupTracker`, `LockupInfo` |
| **sentiment** | 新闻和社交媒体情绪 | `SentimentAnalyzer`, `SentimentResult` |
| **earnings** | 财报跟踪与分析 | `EarningsTracker`, `EarningsReport` |
| **scorer** | 多维度综合评分 | `IPOScorer`, `CompositeScore` |
| **dashboard** | 可视化仪表盘 | `Dashboard` |

## 快速开始

### 安装

```bash
# 克隆项目
git clone <repo-url>
cd ipo-radar

# 使用 Poetry 安装依赖
poetry install

# 配置环境变量
cp .env.example .env
# 编辑 .env 填入你的 API 密钥
```

### 运行

```bash
# 启动仪表盘
poetry run streamlit run src/dashboard/app.py
```

## 技术栈

- **数据获取**: requests, yfinance, sec-api
- **数据处理**: pandas, SQLAlchemy
- **AI/LLM**: LangChain, LiteLLM
- **可视化**: Streamlit
- **调度**: schedule

## License

MIT
