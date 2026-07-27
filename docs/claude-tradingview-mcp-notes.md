# Claude × TradingView：把 Claude 接进看盘台 · 操作笔记

> 来源：[Bilibili BV16Dgr61EFU](https://www.bilibili.com/video/BV16Dgr61EFU/)（UP：投机实验室，约 6–7 分钟）  
> 同系列短版：[BV1uWgU67Ev7](https://www.bilibili.com/video/BV1uWgU67Ev7/)  
> 对应开源项目：[tradesdontlie/tradingview-mcp](https://github.com/tradesdontlie/tradingview-mcp)（约 5k+ star）

**免责声明：** 工具只操作你本机已登录的 TradingView Desktop 图表，**不会自动实盘下单**。笔记供学习搭建，不构成投资建议。需自备合法 TradingView 订阅。

---

## 一句话结论

用 **MCP** 把 **Claude Code** 接到本机 **TradingView Desktop**（经 Chrome DevTools Protocol），让 AI 能：**看盘、改图表、写/编译 Pine、出策略研报、Replay 复盘**——视频标题里的「蒸馏交易员」= 把顶级交易员的图表/指标/流程变成可复用的 AI 工作流。

---

## 视频在演示什么

| 标题能力 | 项目里对应什么 |
|----------|----------------|
| 自己看盘 | `chart-analysis`：读报价、指标、Pine 线/标签/表，截图分析 |
| 写策略 | `pine-develop`：写 Pine → 注入编辑器 → 编译 → 修错循环 |
| 出研报 | `strategy-report`：回测指标 + 成交明细 + 权益曲线 → 结构化报告 |
| 远程复盘 | `replay-practice`：Replay 逐步走 K、模拟买卖、记盈亏 |
| 蒸馏顶级交易员 | 复制/对齐其布局与指标，让 Claude 按同一套流程反复分析（技能/提示词固化） |

底层能力约 **78 个 MCP tools**，另有等价 CLI：`tv status` / `tv quote` / `tv pine compile` 等。

---

## 前置条件

- TradingView **Desktop**（付费订阅，实时行情）
- Node.js **18+**
- **Claude Code**（支持 MCP）
- macOS / Windows / Linux
- 本机主动打开调试口：`--remote-debugging-port=9222`

> 项目**不**连 TradingView 服务器、**不**绕过付费墙、**不**替你实盘下单；数据走本机 CDP。

---

## 操作步骤（按官方 SETUP）

### 1. 克隆并安装

```bash
git clone https://github.com/tradesdontlie/tradingview-mcp.git ~/tradingview-mcp
cd ~/tradingview-mcp
npm install
```

### 2. 写入 Claude Code MCP 配置

全局：`~/.claude/.mcp.json`，或项目级：`.mcp.json`：

```json
{
  "mcpServers": {
    "tradingview": {
      "command": "node",
      "args": ["/绝对路径/tradingview-mcp/src/server.js"]
    }
  }
}
```

把路径换成你的实际安装目录；若已有其它 MCP，**合并** `tradingview` 条目，不要整文件覆盖。

### 3. 用调试口启动 TradingView

**推荐：** MCP 连上后让 Claude 调 `tv_launch`。

或本机脚本：

| 系统 | 命令 |
|------|------|
| Mac | `./scripts/launch_tv_debug_mac.sh` |
| Windows | `scripts\launch_tv_debug.bat` |
| Linux | `./scripts/launch_tv_debug_linux.sh` |

手动等价：

```bash
/path/to/TradingView --remote-debugging-port=9222
```

### 4. 重启 Claude Code 并验活

对 Claude 说：

> Use `tv_health_check` to verify TradingView is connected

也可用 CLI：`tv status`。

---

## 常用自然语言 → 工具

| 你说 | Claude 大致调用 |
|------|-----------------|
| 我盘上是什么？ | `chart_get_state` → 指标值 / `quote_get` |
| 完整分析一下 | 报价 + 指标 + Pine 线/标签/表 + OHLCV 摘要 + 截图 |
| 切到 AAPL 日线 | `chart_set_symbol` → `chart_set_timeframe` |
| 写一个 Pine 策略 | `pine_set_source` → `pine_smart_compile` → 修错 |
| 从 3 月 1 日开始 Replay | `replay_start` → `replay_step` / `replay_trade` |
| 出一份策略研报 | `data_get_strategy_results` + trades/equity + 截图 |

内置技能目录（项目 `skills/`）：

- `chart-analysis` — 看盘分析  
- `pine-develop` — 写指标/策略  
- `strategy-report` — 回测研报  
- `replay-practice` — 复盘练习  
- `multi-symbol-scan` — 多品种扫描  

一句话安装提示（可直接贴给 Claude Code）：

> Install the TradingView MCP server. Clone https://github.com/tradesdontlie/tradingview-mcp.git, run npm install, add it to my MCP config at ~/.claude/.mcp.json, and launch TradingView with the debug port. Then verify the connection with tv_health_check.

---

## 「蒸馏交易员」怎么理解（实用向）

1. 打开/对齐该交易员常用的品种、周期、指标布局。  
2. 用 Claude 读盘面结构（价位、标签、表格、策略结果）。  
3. 把稳定有效的分析步骤写成固定提示词 / 沿用仓库 `skills/`。  
4. Replay 里反复走历史，让流程可复现，而不是指望 AI「玄学预测」。

评论区常见提醒（值得听）：AI 也可直接读交易数据；加密/闭源指标未必读得有意义；写完 Pine 可直接粘贴编译——MCP 的价值在**图表操控 + 迭代闭环**，不是万能印钞机。

---

## 视频信息速览

| 项 | 值 |
|----|----|
| BV | [BV16Dgr61EFU](https://www.bilibili.com/video/BV16Dgr61EFU/) |
| UP | 投机实验室 |
| 时长 | 约 6:47（407 秒） |
| 公开 | 2026-07-22 |
| 标签 | Claude / ClaudeCode / MCP / TradingView / 自动化 |
| GitHub | [tradesdontlie/tradingview-mcp](https://github.com/tradesdontlie/tradingview-mcp) |

---

## 参考

- 项目 README / SETUP_GUIDE：安装与工具表  
- 同 UP 解说：[Claude入局：AI自动分析TradingView图表](https://www.bilibili.com/video/BV13EgU6DECU)（文案亦指向同一仓库）  

> B 站无可用字幕/AI 总结接口；步骤与能力表按视频主题与开源仓库公开文档整理。
