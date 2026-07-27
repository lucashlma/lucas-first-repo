# lucas-first-repo

## 文档

- [段永平「保险公司式」期权策略 · 内容笔记](docs/duan-spacex-options-summary.md)
  - 手机阅读：[HTML 版](docs/duan-spacex-options-summary.html)
  - 原视频：[Bilibili BV12F376xErv](https://www.bilibili.com/video/BV12F376xErv/)

- [Cursor × TradingView MCP · 操作笔记](docs/cursor-tradingview-mcp-notes.md)
  - 手机阅读：[HTML 版](docs/cursor-tradingview-mcp-notes.html)
  - 灵感视频：[Bilibili BV16Dgr61EFU](https://www.bilibili.com/video/BV16Dgr61EFU/)
  - 上游：[tradesdontlie/tradingview-mcp](https://github.com/tradesdontlie/tradingview-mcp)

## Cursor × TradingView（已可直接跑）

```bash
bash scripts/setup-cursor-tradingview.sh
bash scripts/install-and-launch-tradingview.sh   # 安装 TV Desktop + CDP :9222
# 若弹出 Welcome：点右上角 X 关闭即可（未登录功能有限）
node tools/tradingview-mcp/src/cli/index.js status
node tools/tradingview-mcp/src/cli/index.js quote
```

Cursor：**Settings → MCP** 启用 `tradingview`（项目配置见 [`.cursor/mcp.json`](.cursor/mcp.json)）。

- 源码：`tools/tradingview-mcp/`
- 云环境已实测：`cdp_connected: true`，可读 AAPL 报价并切换 BTCUSD