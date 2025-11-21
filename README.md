# AIStockTrade

智能量化交易控制台，集成 LLM 决策、实时 A 股行情、策略执行与可视化运营面板。项目基于 Flask + SQLite 架构，提供 API 提供方管理、模型资金池管理、行情获取、AI 策略执行以及 3D 风格的前端驾驶舱，帮助团队快速落地 AI 驱动的量化实验。

## 功能亮点

- **多模型账户管理**：支持绑定多个 API 提供方/大模型账号，自由创建资金账户并独立回测与执行策略。
- **AI 决策引擎**：AITrader 通过结构化提示词调用 OpenAI 兼容接口，输出包含信号、仓位、风控指令的 JSON 结果，TradingEngine 负责校验并落地下单。
- **自动交易循环**：内置调度线程，根据可配置的时间窗口和频率自动触发行情刷新、AI 决策与仓位调整，支持手动执行单次交易周期。
- **实时行情与指标**：MarketDataFetcher 接入新浪行情（保留聚宽适配），提供价格、涨跌幅、SMA、RSI 等指标并做缓存控制。
- **可观测性控制台**：前端 3D 仪表盘展示账户资产、盈亏、持仓、交易记录与 AI 对话链路，支持模型聚合视图与单模型切换。
- **完整资产记录**：Database 模块管理 API 提供方、模型、持仓、交易、会话、账户净值、股票清单及日线收盘价，便于二次分析。

## 快速开始

### 1. 准备环境
- Python >= 3.9
- Node 仅用于静态资源（仓库已构建，可选）
- （可选）Docker / Docker Compose

### 2. 克隆与安装
```bash
pip install -r requirements.txt
```

### 3. 配置
- 复制 `config.py` 或改写其中参数：
  - `HOST` / `PORT`：服务监听地址
  - `DATABASE_PATH`：SQLite 文件路径
  - `AUTO_TRADING`、`TRADING_INTERVAL`、`TRADE_FEE_RATE`
  - `JQDATA_*`：如需聚宽行情
- 生产环境建议通过环境变量覆盖敏感项（如 `DATABASE_PATH`、API Key）。

### 4. 初始化数据库
```bash
python -c "from database import Database; Database().init_db()"
```

### 5. 启动服务
```bash
python app.py
```
控制台会自动初始化交易引擎、启动自动交易线程（若开启）并在 `http://localhost:5000` 提供 UI 与 API。

## 部署指南

### 方案 A：Docker（推荐）
```bash
docker build -t aistocktrade .
docker run -d --name aistocktrade \
  -p 5000:5000 \
  -v $(pwd)/data:/app/data \
  -e DATABASE_PATH=/app/data/trading_bot.db \
  aistocktrade
```
说明：
1. 镜像基于 `python:3.9-slim`，容器入口即 `python app.py`。
2. 挂载 `data` 目录，持久化 SQLite。
3. 通过 `-e` 注入 API Key、JQDATA 账号等敏感信息。

### 方案 B：Docker Compose
```bash
docker compose up -d
```
Compose 文件默认暴露 5000 端口并挂载 `./data` 目录，修改 `environment` 或 `ports` 即可扩展。

### 方案 C：裸机/虚拟机
1. 创建 Python 虚拟环境并安装依赖。
2. 通过 `systemd`、`supervisor` 或 `pm2` 等方式守护 `python app.py`。
3. 结合 Nginx/Traefik 做反向代理与 TLS。
4. 使用 `cron`/`systemd timer` 监控交易日志，必要时接入集中日志或告警。

### 生产加固建议
- 配置防火墙与反向代理限流。
- 通过 `gunicorn` + `gevent` 等 WSGI 守护进程增强并发能力。
- 开启 HTTPS，并隔离数据库读写权限。
- 结合外部任务编排（如 Celery/APS）实现多节点调度（后续可扩展）。

## 控制台与 API

- 前端采用单页交互，提供模型列表、市场价格、账户曲线、持仓/交易表、AI 对话等模块。
- 后端 REST API 包括：
  - `/api/providers`：API 提供方 CRUD
  - `/api/models`：模型及资金账户管理
  - `/api/stocks`：标的配置
  - `/api/market/prices`：实时行情
  - `/api/models/<id>/execute`：触发单次交易周期
  - `/api/aggregated/portfolio`：聚合统计
  - `/api/settings`：交易频率/费率/时间窗配置
  - `/api/version`：版本号

## 数据存储
- SQLite 默认位于 `trading_bot.db`，包含 providers、models、portfolios、trades、conversations、account_values、settings、stocks、daily_prices 等表。
- 交易执行同时记录手续费、毛/净收益，便于回溯。

## 常见问题
1. **未拉到行情 / 交易暂停**：检查股票配置与自动交易时间窗；超时段 TradingEngine 会直接跳过。
2. **AI 响应非 JSON**：前端会清洗 Markdown 代码块；若解析失败将把原始文本入库以便排查。
3. **可用资金不足**：TradingEngine 会基于风险预算和手续费重新计算下单数量，必要时返回错误提示。

## 贡献与许可
- 贡献指南见 `CONTRIBUTING.md`。
- 许可证（TBD）：请根据实际需求补充，如 MIT / Apache-2.0。
