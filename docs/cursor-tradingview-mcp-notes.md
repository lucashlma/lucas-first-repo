# Cursor × TradingView MCP · 操作笔记

> 来源灵感：[Bilibili BV16Dgr61EFU](https://www.bilibili.com/video/BV16Dgr61EFU/)（投机实验室）  
> 本仓库目标：**在 Cursor 里**用同一套 TradingView MCP，而不是 Claude Code  
> 上游：[tradesdontlie/tradingview-mcp](https://github.com/tradesdontlie/tradingview-mcp)

**免责声明：** 工具只操作你本机已登录的 TradingView Desktop 图表，**不会自动实盘下单**。需合法 TradingView 订阅。非投资建议。

---

## 本仓库一键复制（Cursor）

```bash
bash scripts/setup-cursor-tradingview.sh
bash scripts/launch-tradingview-debug.sh
```

然后在 Cursor：**Settings → MCP** 启用 `tradingview`（或 Reload Window）。

在 Agent 对话里说：

> Use tv_health_check to verify TradingView is connected

| 文件 | 作用 |
|------|------|
| `.cursor/mcp.json` | Cursor 项目级 MCP（`${workspaceFolder}`，可提交） |
| `~/.cursor/mcp.json` | 可选全局配置（setup 会写入绝对路径） |
| `tools/tradingview-mcp/` | vendored MCP 源码 |
| `scripts/launch-tradingview-debug.sh` | 带 `--remote-debugging-port=9222` 启动 TV |

> 云环境无 TradingView Desktop 时，`tv status` 报 CDP 失败属预期。

---

## 一句话结论

用 **MCP** 把 **Cursor Agent** 接到本机 **TradingView Desktop**（Chrome DevTools Protocol），实现：**看盘、写/编译 Pine、出策略研报、Replay 复盘**。

架构：

```
Cursor Agent  ←→  MCP (stdio)  ←→  CDP :9222  ←→  TradingView Desktop
```

---

## 能力对照（视频 → 工具）

| 能力 | 项目技能 / 工具 |
|------|-----------------|
| 自己看盘 | `chart-analysis`：报价、指标、Pine 线/标签、截图 |
| 写策略 | `pine-develop`：写 → 注入 → 编译 → 修错 |
| 出研报 | `strategy-report`：回测指标 + 成交 + 权益曲线 |
| 远程复盘 | `replay-practice`：逐步走 K、模拟买卖 |
| 蒸馏交易员 | 对齐布局/指标，把步骤写成固定提示词 |

技能目录：`tools/tradingview-mcp/skills/`

---

## 前置条件

- **Cursor**（桌面版，支持 MCP）
- TradingView **Desktop** + 付费订阅
- Node.js **18+**
- 本机打开调试口：`--remote-debugging-port=9222`

---

## 手动配置（不跑脚本时）

项目级 `.cursor/mcp.json`：

```json
{
  "mcpServers": {
    "tradingview": {
      "command": "node",
      "args": ["${workspaceFolder}/tools/tradingview-mcp/src/server.js"]
    }
  }
}
```

先在 `tools/tradingview-mcp` 执行 `npm install`。

---

## 常用说法

| 你在 Cursor 里说 | 大致工具 |
|------------------|----------|
| 我盘上是什么？ | `chart_get_state` / `quote_get` / 指标值 |
| 完整分析 | 报价 + 指标 + Pine 数据 + 截图 |
| 切到 AAPL 日线 | `chart_set_symbol` + `chart_set_timeframe` |
| 写一个 Pine 策略 | `pine_set_source` → `pine_smart_compile` |
| 从某日开始 Replay | `replay_start` → `replay_step` / `replay_trade` |
| 出策略研报 | `data_get_strategy_results` + trades/equity |

CLI 等价：`node tools/tradingview-mcp/src/cli/index.js status`

---

## 参考

- Cursor MCP 文档：https://cursor.com/docs/mcp  
- 上游 SETUP：`tools/tradingview-mcp/SETUP_GUIDE.md`（原文面向 Claude Code，本仓库已改接 Cursor）  
- 原视频：[BV16Dgr61EFU](https://www.bilibili.com/video/BV16Dgr61EFU/)
