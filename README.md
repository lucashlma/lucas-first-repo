# lucas-first-repo

## 文档

- [段永平「保险公司式」期权策略 · 内容笔记](docs/duan-spacex-options-summary.md)
  - 手机阅读：[HTML 版](docs/duan-spacex-options-summary.html)
  - 原视频：[Bilibili BV12F376xErv](https://www.bilibili.com/video/BV12F376xErv/)

- [Claude × TradingView MCP · 操作笔记](docs/claude-tradingview-mcp-notes.md)
  - 手机阅读：[HTML 版](docs/claude-tradingview-mcp-notes.html)
  - 原视频：[Bilibili BV16Dgr61EFU](https://www.bilibili.com/video/BV16Dgr61EFU/)
  - 上游：[tradesdontlie/tradingview-mcp](https://github.com/tradesdontlie/tradingview-mcp)

## 复制 Claude × TradingView 操作

在本机（需安装 TradingView Desktop + Claude Code + Node 18+）：

```bash
bash scripts/setup-claude-tradingview.sh
bash scripts/launch-tradingview-debug.sh
# 重启 Claude Code，然后说：Use tv_health_check to verify TradingView is connected
```

- 源码：`tools/tradingview-mcp/`
- MCP 模板：`.mcp.json.example`（实际路径由 setup 脚本写入 `.mcp.json`）
