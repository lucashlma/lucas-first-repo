# Blender MCP 冒烟测试

把下面整段指令发给 Cursor Agent。它只会新建一个独立集合，不应删除或覆盖当前场景。

```text
使用 Blender MCP 完成以下冒烟测试：

1. 调用 get_addon_status，报告 Blender 版本、插件版本、端口和已启用资产源。
2. 调用 get_scene_info，记录修改前的对象数量与活动场景。
3. 新建 Collection：MCP_Pipeline_Smoke_Test。
4. 在该 Collection 内创建：
   - 一个尺寸为 2m × 2m × 0.1m 的地台，命名 SmokeTest_Platform；
   - 一个位于地台上的 1m 立方体，命名 SmokeTest_Cube；
   - 一个 UV Sphere，命名 SmokeTest_Sphere，位于立方体右侧且不穿模；
   - 立方体使用暖灰哑光材质，球体使用蓝色金属材质。
5. 用 look 获取 camera/angles 的 solid 和 material 两套视图，检查：
   - 两个物体都落在地台上；
   - 彼此没有穿模；
   - 材质分配正确；
   - 构图中三个对象完整可见。
6. 如检查失败，只修改失败对象后重新 look；最多重试 2 次。
7. 不覆盖当前文件。另存为：
   blender_workroom/output/mcp_pipeline_smoke_test.blend
8. 最后输出：
   - 修改后的对象数量；
   - 新建对象和材质名称；
   - 保存路径；
   - 两张视觉检查图；
   - PASS 或 FAIL（附失败原因）。
```

## 通过标准

- Cursor Settings → MCP 中 `blender` 为绿色；
- Agent 能列出 `get_addon_status`、`execute_blender_code`、`look`、`get_scene_info` 等工具；
- Blender 视口出现 `MCP_Pipeline_Smoke_Test` 集合；
- Agent 能看回执行结果并自主纠正一次；
- `.blend` 文件成功另存，不影响原场景。

## AI 3D 生成附加测试（可选，会消耗额度）

基础测试通过后，在 Blender 的 MCP for Blender 侧栏中开启 Tripo，再发送：

```text
先调用 get_addon_status，确认 Tripo 已启用。不要立刻生成。
先给我展示用于“现代人体工学办公椅，黑色皮革，五爪滚轮，写实 PBR”的最终提示词、
预计生成数量（只能是 1 个）及导入后的修整计划，等待我确认。
```

只有在用户确认后，才允许调用 `generate_3d`。
