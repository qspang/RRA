# 配置目录

根目录不再散放 JSON 配置。所有运行配置统一存放在这里，只有两个无密钥示例和本说明提交 Git，其他实际配置、历史配置和自动产生的 resolved 配置全部忽略。

| 文件 | 用途 |
| --- | --- |
| config.example.json | 三 Agent 完整流程示例 |
| config.description.example.json | 仅路径描述 3.3.1、3.3.2 |
| config.local.json | 自行从示例复制的本地配置，不提交 |
| config.*.resolved.json | 自动双路线生成后保存的配置，不提交 |
| 其他 config.*.json | 本机历史场景/验收配置，不提交 |

在 RoadDescription 根目录执行：

```bash
cp configs/config.example.json configs/config.local.json
cp .env.example .env
python tools/check_setup.py --config configs/config.local.json --deep
python -m road_description --config configs/config.local.json --plan
```

配置的 `project_root: ".."` 指向项目根目录。因此仍写 `roaddata/preprocessed`、`.env`、`outputs/local_run`，不要再加 `../`。只有 project_root 本身相对配置文件位置解析；旧配置不含该字段时仍沿用“相对配置目录”的语义。报告服务会把 project_root 固定为绝对路径，再创建隔离任务配置，避免任务目录改变输入位置。

API 地址、model_id 和开关填写到本地配置的 llm/vlm 中；密钥填项目根目录的 .env 或环境变量，切勿写进两个公开示例。字段与服务依赖见[项目说明](../README.md)。
