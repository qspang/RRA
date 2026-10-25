# 路径方案比选 Agent

章节范围：3.3 总体方案及 3.3.3 比选，独立可选能力。实现位于本目录 `agent.py`，通过 `report_agents/registry.py` 注册，公共地物与资料处理位于 `report_agents/common/`。

在项目根目录运行：

```bash
python -m report_agents --config configs/config.local.resolved.json --agents route_comparison
```

配置名以首次规划产生的 resolved 文件为准。独立执行前必须备齐同一起终点的两个方案响应及地图快照，并配置对应预处理地物目录。输出为插件结果 JSON 和 Word/PDF；事实和证据沿用公共上下文，不凭模型补造缺失资料。

可通过 `agents.enabled` 选择插件。仅当比选与合规插件都运行且 `agents.assembly.enabled` 开启时生成合成报告。路径描述独立运行不会连带运行另两个插件。

安装、数据准备、模型配置、完整流程及个人交付边界参见[项目 README](../../README.md)。

开发分工及共享模块修改边界见[开发说明](../../docs/DEVELOPMENT.md)。地物统一从项目配置指定的 `roaddata/` 读取，插件内不要硬编码机器路径或各自复制凭据；资料结构见[数据目录说明](../../roaddata/README.md)。
