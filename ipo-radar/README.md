# IPO Radar - IPO决策信息系统

IPO Radar 是一个综合性的IPO（首次公开募股）决策信息系统，帮助投资者追踪、分析和评估新上市股票。

## 功能模块

| 模块 | 说明 |
|------|------|
| **radar** | 新股监控 - 追踪即将上市和近期上市的IPO |
| **screener** | 基本面筛选 - 基于财务指标筛选IPO标的 |
| **pattern** | 形态识别 - 识别IPO股票的价格和成交量形态 |
| **lockup** | 禁售期跟踪 - 监控内部人士和机构的禁售期到期日 |
| **sentiment** | 情绪分析 - 分析市场对IPO的情绪倾向 |
| **earnings** | 业绩追踪 - 跟踪IPO公司上市后的财务表现 |
| **scorer** | 综合评分 - 多维度综合评估IPO投资价值 |
| **dashboard** | 仪表盘 - 可视化展示所有分析结果 |

## 快速开始

```bash
# 安装依赖
poetry install

# 配置环境变量
cp .env.example .env
# 编辑 .env 填入你的 API 密钥

# 启动仪表盘
streamlit run src/dashboard/app.py
```

## 技术栈

- **数据获取**: requests, yfinance, sec-api
- **数据处理**: pandas, SQLAlchemy
- **AI/NLP**: langchain, litellm
- **任务调度**: schedule
- **可视化**: Streamlit
