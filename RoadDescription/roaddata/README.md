# 本地工程数据放置约定

此目录只提交本说明，**数据本身全部被 Git 忽略**。clone 后从项目负责人取得与规划服务相匹配的数据包，解压成下面的结构；不需要在代码中修改原作者的磁盘路径。

```text
roaddata/
├── preprocessed/             同一次规划预处理的完整输出目录
│   ├── manifest.json
│   ├── m0/                   归一化矢量、读入与坐标诊断记录
│   ├── m1/standardized_features.gpkg
│   ├── m2/                   禁跨区、禁塔区、风冰区等
│   └── m3/rule_config.json
├── dem/terrain.tif           DEM，需有正确坐标系和有效高程
├── source/
│   ├── side_roads.gdb/       完整 FileGDB 文件夹，不能只复制其中一个文件
│   ├── ecology.gdb/          完整生态/敏感区 FileGDB
│   └── 大埔候选路径/         北方案.kml、南方案.kml、梅州村界.*
├── reference/大埔章节3.pdf   当前参考原稿
├── admin/guangdong_adm.gdb/  广东案例启用，内含各级区划面
├── materials/               可选，照片、协议、专项调查与补充资料
└── planner_evidence/         可选，规则实现快照，仅作规则来源佐证
    └── algorithm/tower_placer.py
```

不要多嵌套一层 `preprocessed/run_xxx/`；若采用其他文件名，修改被忽略的 `configs/config.local.json`，不用改 Python。配置统一放在 `configs/`，通过 `project_root: ".."` 指向 `RoadDescription/`；配置中的数据、凭据与输出路径均相对该项目根目录。

| 数据 | 配置项 | 用途与缺少时的影响 |
| --- | --- | --- |
| 预处理包 | `dataset: roaddata/preprocessed` | 必需。地物专名、几何、规则、约束与风冰；不是只靠 DEM 或 NPY 就能替代 |
| DEM | `agents.dem_path` | 沿线高程和地形指标；不含调查断面和人工核定地形比例 |
| 补充道路 GDB | `supplemental_layers[0]` | 当前样例图层为 `乡道_补充`；道路等级缺失仍标待核 |
| 生态 GDB | 其余 `supplemental_layers` | 当前用 `生态保护红线一般区域`、`一级水源保护区`、`自然保护区缓冲区`；覆盖被裁剪的报告类别，仅补充报告核查，不修改规划规则 |
| 参考 PDF | `reference_pdf` | 页眉提取、章节样式和模型对照审阅；当前流水线需要文件 |
| 行政边界 | `admin_boundary` / `admin_name_field` | 广东 GDB 使用 admin_profile=guangdong_gdb；分别量取县、镇、村里程 |
| 照片与补充资料 | `photos`、`materials`、`agents.supplemental_file` | 需匹配路线版本、明确来源和确认状态，不以地图截图冒充现场照片 |
| 规则实现快照 | `agents.planner_source` | 可选、按配置读取；只读取函数默认参数作佐证，不导入执行，不等于该次请求采用了该规则 |

最初迁移的地物及 DEM 包合计 388 个文件、约 2.83 GiB（其中 DEM 占大部分）。保留原数据未修改，复制前后逐文件 SHA256 一致。本地 `migration_manifest.local.json` 记录来源、目标和哈希，含机器路径，因此不提交。其他项目应提供自己的同版本数据，不能混用本样例 DEM/GDB 与另一项目规划结果。

地物包还不足以启动路径规划服务：规划系统需独立部署并自行配置它的原始输入和缓存。本目录是报告侧读取的数据包，不是规划后端的完整部署包。

检查 KML 工作台数据（若走起终点规划流程，配置名换成 config.local.json）：

```bash
python tools/check_setup.py --config configs/config.dapu-kml.json --deep
```

此命令检查文件、GDB 图层、DEM 元信息、PDF 渲染器和启用模型的凭据是否存在，不调用收费模型。运行真实流水线后，仍须核查地图版本、路线坐标、地物交集及报告中的资料缺口。改数据路径后应生成到新的输出目录，不能直接拼接旧事实与新来源路径。

预处理 manifest 中可能保留生产该数据时的原始来源路径，它们属于版本证据，未为迁移改写；当前报告读取路径由本地配置决定。保留 manifest 原始内容，才能继续用其 SHA256 校验与规划结果的版本匹配。

## 广东行政区边界

把 guangdong_adm.gdb.7z 解压到 `roaddata/admin/guangdong_adm.gdb/`。此包内部直接是数据库成员文件，解压后 `a*.gdbtable` 应在该目录的第一层。三个公开模板均配置 `admin_boundary` 指向此目录，`admin_profile` 为 `guangdong_gdb`。使用旧单层边界时移除 profile，沿用 admin_name_field；无边界的工程可将 admin_boundary 设为 null。

数据为 EPSG:3857，共省1、市21、县级124、乡镇1761、村级26245条。报告分别使用 dist、town、village 面图层，并从父级属性取得省市名称。区划来源单位、采集年份、行政调整生效时间及法定效力需资料提供方确认。接入只影响报告叠加分析，报告保留各层独立的里程、重入、空隙和重叠情况。数据包留本地。原有容量统计仅指加入本包前的基线。

切换到新边界的首次生成，请从地图和两条响应重新提取 `route_facts.json`，再运行独立插件。已有工程保留原报告目录另建新输出目录，复用 `map.json`、`map.raw.json.gz`、两方案各自的 `request.json` 与 `response.json`；归档模式执行完整入口时省略 `--plan`。新工程按主 README 的命令执行 `--plan`。本次本机可用配置为 `configs/config.guangdong-admin.json`（模型模式）与 `configs/config.guangdong-admin-local.json`（本地生成）；外部使用者可从 configs/ 下对应的公开模板创建本地配置。

## 收到数据包后如何核对

1. **预处理包**整目录复制。除标准地物外，`m2/forbidden_polygons.gpkg`、`no_tower_polygons.gpkg`、`wind_ice_zones.gpkg` 等用于约束与风冰区核查；`m3/rule_config.json` 是编译后的规则，`m3/workspace.json` 和 `solver_params.json` 随该版本保存。目录不能只放预处理日志或几张显示图片。
2. **广东行政界**使用 `guangdong_adm_dist`、`guangdong_adm_town`、`guangdong_adm_village` 三个图层。切勿将压缩包重命名为 `.gdb`。解压后若出现两层同名目录，请将配置指向实际包含数据库文件的一层。
3. **候选线与村界**来自本机的 `GIS相关数据_藏东南(1).zip`。分别取压缩包中「候选路径」下的两份 KML、「梅州村界」下的整套文件，本机集中放在 `source/大埔候选路径/`。保留同名的 `.shp`、`.shx`、`.dbf`、`.prj`、`.cpg` 等成员。网页导入只选择两份 KML；额外村界用于复核，公共流水线按 `admin_boundary` 选择量算图层。
4. **地图快照**从同一工程的规划或报告归档复制 `map.json`、`map.raw.json.gz` 到 KML 配置的 `output_dir`（公开模板为 `outputs/kml_seed/`）。同版 `tiles/` 为可选缓存。已有本机大埔案例配置指向 `outputs/大埔南北候选线_20261124/`，可以直接复用。上传新 KML 时由服务生成两条路线各自的来源记录。
5. **复现发布案例**时，先对照 [KML SHA256 与样例文件](../outputs/latest/run_summary.json)。除上述输入外，若需重现原初设对照段落和图件，还须向维护方取得原案例配置对应的 `agents.assembly.section_notes`、其引用的素材，以及种子目录中南北方案的原始来源记录。通用 KML 模板默认按本次导入线位重新产出报告。
