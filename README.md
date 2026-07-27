# lucas-first-repo

## 文档

- [段永平「保险公司式」期权策略 · 内容笔记](docs/duan-spacex-options-summary.md)
  - 手机阅读：[HTML 版](docs/duan-spacex-options-summary.html)
  - 原视频：[Bilibili BV12F376xErv](https://www.bilibili.com/video/BV12F376xErv/)

- [Cursor × TradingView MCP · 操作笔记](docs/cursor-tradingview-mcp-notes.md)
  - 手机阅读：[HTML 版](docs/cursor-tradingview-mcp-notes.html)
  - 灵感视频：[Bilibili BV16Dgr61EFU](https://www.bilibili.com/video/BV16Dgr61EFU/)
  - 上游：[tradesdontlie/tradingview-mcp](https://github.com/tradesdontlie/tradingview-mcp)

## Cursor × TradingView（复制操作）

本机需：**Cursor** + TradingView Desktop + Node 18+

```bash
bash scripts/setup-cursor-tradingview.sh
bash scripts/launch-tradingview-debug.sh
```

然后在 Cursor：**Settings → MCP** 启用 `tradingview`，在 Agent 中说：

`Use tv_health_check to verify TradingView is connected`

- 项目 MCP：[`.cursor/mcp.json`](.cursor/mcp.json)（`${workspaceFolder}`，可提交）
- 源码：`tools/tradingview-mcp/`
