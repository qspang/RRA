# RoadDescription：输电线路报告生成

读取路径规划结果和底层 GIS 地物，生成路径描述、路径方案比选及合规分析 Word/PDF。三个 Agent 独立放在 `report_agents/` 的子目录中，通过注册表装配；`road_description/` 提供规划接口、地图取证、事实提取、模型调用和文档生成能力。

**当前个人负责的章节仅为 3.3.1、3.3.2。** 比选、合规插件保留为可选能力，不扩大个人交付范围。

| Agent | 独立目录 | 章节与职责 |
| --- | --- | --- |
| 路径描述 `route_description` | [说明](report_agents/route_description/README.md) | 3.3.1 北方案、3.3.2 南方案；长度、走向、经过区域与主要跨越 |
| 方案比选 `route_comparison` | [说明](report_agents/route_comparison/README.md) | 3.3 总体方案、复用方案描述、3.3.3 对比；独立扩展插件 |
| 路径合规 `route_compliance` | [说明](report_agents/route_compliance/README.md) | 3.4.8—3.4.11、3.5；地物关系、专项资料及停电相关分析 |

`report_agents/assembly.py` 负责合成完整章节，不是第四个 Agent。当前是确定的工具流程结合 LLM 叙述与 VLM 审阅；模型不自行替代 GIS 测量、工程审批或任意决定工具调用顺序。

## 查看结果

[最新完整 PDF](outputs/latest/完整报告_参照大埔精简版.pdf) · [Word](outputs/latest/完整报告_参照大埔精简版.docx) · [样例及用量说明](outputs/latest/README.md)

仓库仅保留这一套 20 页合成样例。普通乡道的细碎事件不逐项铺满正文；`report_style: "reference"` 按参考章节选取主要对象和代表性截图，完整事件留在运行产生的 JSON/CSV 中。

## 开发和交接入口

- [各文件职责、三个 Agent 分工及依赖关系](docs/DEVELOPMENT.md)
- [roaddata 数据放置说明](roaddata/README.md)
- [尚需提供的资料与外部依赖](docs/REQUIRED_INPUTS.md)

## 完整运行需要哪些东西

**本仓库只有报告生成端，不包含路径规划系统。首次从起终点生成报告，必须另外取得并启动兼容的路径规划系统（当前对接 `opt_v56`）。只 clone 本仓库、填写 API 或放好地物数据，都不能替代路径规划后端。**

| 必需项 | 从哪里取得/如何准备 | 本仓库是否提供 |
| --- | --- | --- |
| 路径规划系统 | 向系统维护方取得完整 `opt_v56` 源码/匹配部署包及其接口文档；包含 `serve.py`、`algorithm/`、`tools/run_local.sh`、运行配置和依赖文件 | 不提供，需单独交接；本仓库没有拉取或自动安装该系统 |
| 规划运行环境 | 按后端 `environment.yml` 或对应部署包安装；源码启动使用 Python 3.11、Flask/Waitress及GIS/数值计算依赖 | 不提供，不能拿报告端 requirements 代替后端环境 |
| 同版本预处理数据 | 取得完整的预处理输出，包括 manifest、地物、规则、工作区和约束；供后端与报告端读取同一版本 | 不提供，放置方法见 roaddata 说明 |
| 报告补充数据与参考原稿 | DEM、补充GDB、参考PDF；正式资料另含照片/行政边界/专项调查等 | 仅提供说明与格式示例，不提供私有源数据 |
| 报告运行环境 | 下文安装本仓库 requirements；模型调用需要网络与额度 | 提供依赖清单，不提供已安装环境 |
| Word转PDF环境 | LibreOffice、目标中文/西文字体 | 提供可选准备脚本，不提供 Office 安装目录或商业字体 |
| LLM/VLM接入 | 自行提供兼容接口地址、模型ID和密钥；VLM需支持图像 | 不提供真实账户和密钥 |
| 卫星底图（使用时） | 后端地图授权、联网条件、Playwright Chromium及系统浏览器依赖 | 不提供第三方授权；不用卫星时可设 use_satellite=false 使用矢量图 |

首次运行不能直接执行独立 Agent 命令：它们需要已经归档的地图和两条路线响应。本仓库的 `outputs/latest/` 只有展示报告，**不是路线重放数据包**。新机器先按下面顺序执行一次 `--plan`，或者由维护方另行交接完整且版本匹配的历史响应与地图包。

建议放置为两个独立工程：

```text
workspace/
├── opt_v56/                     单独取得的路径规划系统，不属于本次仓库
└── RRA/
    └── RoadDescription/        本仓库报告端
        ├── configs/
        ├── roaddata/           单独取得的数据包
        └── ...
```

目录不必固定相邻；二者通过 HTTP 通信，报告端不 import 外部规划工程。报告端同时需要可读取的本地GIS数据。若规划服务已由团队部署到其他机器，可不在本机再启动一份，但必须配置可访问地址并取得与该服务匹配的数据包；`127.0.0.1` 只指当前所在主机/容器。

## 安装报告端与放置数据

以下命令均在 `RoadDescription` 目录执行。建议 Python 3.11；`requirements-lock.txt` 记录已验证环境，`requirements.txt` 提供兼容范围。

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium
python -m report_agents --list
cp configs/config.example.json configs/config.local.json
cp .env.example .env
```

生成 PDF 需要 LibreOffice（可执行文件 `soffice` 或 `libreoffice`）；亦可参看 `tools/prepare_office.py` 和 `tools/soffice_local.sh` 的 Linux 本地安装方案。安装所需中文字体和 Times New Roman；字体缺失时替代字体会影响版式。`templates/` 与 `assets/` 是生成文档需要的模板和参考页眉素材，应一起保留；正式交付前按项目替换页眉单位信息。

编辑 `configs/config.local.json`：

- `planner_url`：独立部署的 `opt_v56` 服务地址，默认本机 5000。该服务不包含在本目录内。
- `dataset`：与规划响应匹配的预处理目录，包含 `m1/standardized_features.gpkg`、规则及配套地图数据。统一放在 `roaddata/preprocessed/`。源 GDB、DEM 和预处理数据不随仓库发布，具体结构见 [数据放置说明](roaddata/README.md)。
- `start` / `end`：规划系统的局部平面坐标，必须落在当前工程范围；示例值只是测试坐标，不是通用经纬度。
- `reference_pdf`：自行放置有权使用的参考章节 PDF；原始甲方 PDF 不发布；统一放在 `roaddata/reference/大埔章节3.pdf`。
- `agents.dem_path`、`supplemental_layers`、`admin_boundary`：按当前工程配置 DEM、补充地物和行政边界；不能用空值推断实际不存在地物。
- `llm` / `vlm`：填写 `api_base`、`model_id` 并开启 `enabled`；密钥填 `.env` 中对应变量，配置通过 `credential_file` 读取。也可直接设置环境变量。并发上限示例为 15。
- `output_dir`、`agents.output_dir`：本地输出目录；不要指向发布样例 `outputs/latest`。

示例默认关闭模型，便于先检查配置；关闭或调用失败时可能走模板回退，不代表已完成真实 LLM/VLM 验收。配置统一放在 `configs/`；通过 `project_root: ".."` 指定项目根目录，数据、模板、凭据及输出均相对项目根目录解析。

## API在哪里配置

真实 API 地址、模型配置和密钥均不提交。`configs/config.example.json` / `configs/config.description.example.json` 的 `api_base`、`model_id` 留空；复制为忽略的 `configs/config.local.json` 后填写：

| 服务 | 配置位置 | 凭据位置 |
| --- | --- | --- |
| 路径规划 | `configs/config.local.json` 的 `planner_url` | 环境变量 `ROAD_PLANNER_TOKEN`（若后端启用鉴权） |
| LLM | 同一文件 `llm.api_base`、`llm.model_id`、`llm.enabled` | `.env` 的 `ROAD_LLM_API_KEY` 或同名环境变量 |
| VLM | 同一文件 `vlm.api_base`、`vlm.model_id`、`vlm.enabled` | `.env` 的 `ROAD_VLM_API_KEY` 或同名环境变量 |

当前模型适配调用 OpenAI兼容的 `/chat/completions` 接口；VLM需要支持图像输入，配置URL不能随意填写成另一种协议。模型设置 `credential_file: ".env"` 才会读取该文件，系统不会自动载入所有 .env 变量。规划 token 只读取进程环境，填写 .env 后仍需自行导出。不要把密钥写在 Python、README、示例或命令行参数里。底图授权在外部规划系统中配置。

先完成 [数据目录](roaddata/README.md) 的放置，再预检：

```bash
python tools/check_setup.py --config configs/config.local.json --deep
```

`error` 需修复，`warning` 表示能力缺失或主动关闭；预检不访问模型、不产生模型费用，也不替代真实接口联调。

## 先启动路径规划系统（终端 A）

以下命令在**另行取得的 opt_v56 目录**执行，不是在 RoadDescription 中执行。先按[数据目录说明](roaddata/README.md)放好完整数据。首次源码安装可依据该后端的 environment.yml 创建环境；如果维护方已提供可用环境/容器包，则使用对应部署说明，不重复覆盖已有环境：

```bash
cd /path/to/workspace/opt_v56
# 首次安装；environment.yml 来自 opt_v56，不是本仓库
conda env create -f environment.yml
conda activate route_opt
```

本机已有 `route_opt` 时只需激活。规划端与报告端建议分别使用自己的环境，避免 GIS 库版本冲突。后端环境包含 Flask、Waitress、NumPy、SciPy、Shapely、GeoPandas、Rasterio、Pyogrio 等；原生加速组件是否具备及兼容性由后端部署包决定，`run_local.sh` 会检查环境并尝试可选内核构建，不能承诺仅安装报告端依赖就有相同性能。容器/离线部署按后端随包的 `deploy/README_CURRENT.md` 或对应版本部署说明执行。

激活规划端环境后启动。把 `/path/to/workspace` 替换为实际位置；`PREPROCESS_MANIFEST` 指向**含 manifest.json 的目录**，不要指向 JSON 文件，也不要留用脚本内旧机器的默认数据目录：

```bash
export PREPROCESS_MANIFEST="/path/to/workspace/RRA/RoadDescription/roaddata/preprocessed"
export APP_HOST=127.0.0.1
export APP_PORT=5000
export ROUTE_LOCAL_CPU_AFFINITY=inherit
mkdir -p logs
bash tools/run_local.sh > logs/route_planner.log 2>&1
```

这是前台服务，终端需要保持运行；Ctrl+C 会停止。启动时加载地图/预热可能需要时间，可在另一终端 `tail -f /path/to/workspace/opt_v56/logs/route_planner.log` 查看日志。后端也可以读取自己的预处理目录，但其数据必须与报告端 `dataset` 内容一致，不能仅因为文件名相同就当作同版本。

如需沿用 CPU 绑定形式，可把最后一行改为 `taskset -c <本机可用CPU列表> bash tools/run_local.sh > logs/route_planner.log 2>&1`。先用 `taskset -pc $$` 查看当前允许的CPU；不要把其他机器的 `2,4,12,14` 原样照搬。`ROUTE_LOCAL_CPU_AFFINITY=inherit` 表示保留外层绑定，避免后端本地 `.route-local-cpu-affinity` 覆盖它。

不要使用 `run_local.sh --sample` 来验收本报告：报告适配要求真实预处理地图及坐标元数据，人工示例地图无法替代工程地物。后端需有运行缓存、工作区和日志目录的写权限；数据加载、并发规划所需内存/CPU随工程变化，本仓库尚未给出跨机器的最低硬件指标。

## 检查规划接口，再运行报告端（终端 B）

终端 A 的后端持续运行，在终端 B 检查：

```bash
curl -fsS http://127.0.0.1:5000/api/health
curl -fsS http://127.0.0.1:5000/api/map/meta
```

健康接口正常不等于数据已匹配；还需确认地图元数据属于本次工程。报告适配器使用 `GET /api/map`（懒加载时继续请求 `/api/map/features`）、`POST /api/plan`、`GET /api/plan/progress` 和取消接口 `/api/plan/cancel`，自动控制点检查还用到 `/api/validate_constraint_point`。旧版/不同系统接口不兼容时，需维护方提供对应版本或修改 `road_description/planner.py`，不能只改URL。详细接口文档应与后端的 `接口文档集/` 一起交接。

若后端启用鉴权，上述 curl 需按后端要求添加鉴权头，报告进程设置 `ROAD_PLANNER_TOKEN`；此变量不由报告的 `.env` 自动导入。不要将真实token提交到仓库。底图授权在 **opt_v56 自己的 .env/部署配置** 中设置（当前后端支持 `TIANDITU_TK`）；它与报告端 LLM/VLM 的凭据文件不是同一个用途。

随后进入报告端并激活其环境：

```bash
cd /path/to/workspace/RRA/RoadDescription
source .venv/bin/activate
python tools/check_setup.py --config configs/config.local.json --deep
python -m road_description --config configs/config.local.json --plan
```

这里的 `.venv` 和 `configs/config.local.json` 应已按前文创建，并填写模型和数据配置。规划后端5000与报告服务5010是**两个不同服务**：命令行生成只需要规划后端，不必启动5010；要使用报告网页/API时，再启动下文的5010服务。5010服务不会替你启动5000。

## 运行三个 Agent

完成上述规划服务启动与数据检查后，完整命令行入口为：

```bash
python -m road_description --config configs/config.local.json --plan
```

示例启用自动生成两条候选路线：对同一起终点采用不同控制点多次调用规划接口，再校验差异和可行性。规划系统单次返回一路径，并不保证自动获得两个可接受方案；失败不能靠复制路线凑数。正式南北方案仍需业务确认。

首次成功运行后，复用该次输出目录的地图和路线响应，可使用自动生成的 resolved 配置重跑；具体配置路径见运行日志。也可以在配置中显式填写已归档方案 ID。插件独立调用依赖已经存在且匹配的地图、两条路线响应：

```bash
python -m report_agents --config configs/config.local.resolved.json --agents route_description
python -m report_agents --config configs/config.local.resolved.json --agents route_comparison
python -m report_agents --config configs/config.local.resolved.json --agents route_compliance
```

上面的 resolved 文件名以实际日志为准。仅做个人负责章节时，用 `configs/config.description.example.json` 创建configs/ 本地配置，再运行完整入口；它只启用路径描述插件、关闭合成，输出 3.3.1、3.3.2。

## 接口、资料与校验

```bash
python -m road_description.service --config configs/config.local.json --port 5010
```

启动后访问 `http://127.0.0.1:5010/`；其健康接口可用 `curl -fsS http://127.0.0.1:5010/api/health` 检查。首次网页/API提交必须请求重新规划（`replan: true`），或配置已有有效归档响应。仅5010健康正常不能证明5000或模型服务可用。

报告服务提供 `GET /api/health`、`POST /api/reports`（`start`、`end`、`replan`）、`GET /api/reports/<id>`，以及任务 `/log`、`/files/<path>` 下载和 `POST /api/reports/<id>/cancel`。服务调用外部规划接口；完整报告还需要本地 GIS 数据，只有起终点不足以凭空生成地物事实。

补充资料格式见 [supplemental.example.json](report_agents/supplemental.example.json) 和 [materials.example.json](report_agents/materials.example.json)。调查、协议、专业结论须绑定当前路线和实际来源文件；程序检查来源及版本，不能替代人工签认。

运行目录保留 `route_facts.json`、跨越事件 CSV、方案响应、文档、运行日志、模型用量与审阅结果。技术执行成功不等同于工程合规获批；缺失资料须继续补充。模型调用可能产生费用，完整文档逐页审阅也会消耗较多 token。

```bash
python -m pytest -q
python tools/measure_report_run.py --config configs/config.local.resolved.json
```

第二条命令读取既有运行日志并写出用量统计 JSON/TXT，不会重新调用模型；需先完成一次报告生成及审阅。`tools/` 还保留数据审计和历史场景验收脚本；部分使用本机历史配置/输出，不能视为下载后即可运行的离线单测。

## 启动失败时先检查什么

| 现象 | 检查方向 |
| --- | --- |
| Connection refused / 请求5000失败 | opt_v56是否启动、是否在正确环境、端口是否一致；不是去启动5010替代 |
| Missing manifest | PREPROCESS_MANIFEST应为实际存在的预处理目录；不要带manifest.json文件名 |
| 提示需要真实预处理地图 | 后端是否误用了 --sample，是否载入正确工程 |
| 地图版本/坐标/事实哈希不匹配 | 两端须同版本数据；换数据后用新输出目录重跑，不能关闭校验硬拼旧事实 |
| 单独运行Agent提示缺map.json/response.json | 新机器没有归档，先运行完整入口 --plan；outputs/latest不能当运行输入 |
| 缺dem/GDB/参考PDF | 按roaddata说明领取并放置，配置中的图层名也须匹配 |
| 模型缺凭据/回退到模板 | 检查本地配置的enabled、api_base、model_id、credential_file与环境变量；代码运行成功不等于模型调用成功 |
| Word有了但PDF缺失 | 安装LibreOffice并检查soffice；补齐字体后复核分页 |
| 卫星图不可用 | 检查规划端底图授权、网络、Chromium和系统依赖；矢量图可跑流程但不能宣称卫星截图已验收 |
| taskset报无效参数 | 改成本机允许的CPU或取消外层绑定，检查后端本地亲和性设置 |

全部运行依赖与尚缺业务资料另见[交接清单](docs/REQUIRED_INPUTS.md)。报告侧数据包当前约2.83 GiB，此外还需后端代码/环境、报告环境、运行缓存和输出磁盘空间，不能把2.83 GiB当作完整系统的空间需求。

## 发布范围

参见 [待推送审阅清单](docs/PUBLISH_REVIEW.md) 和 [逐文件清单](docs/PUBLISH_FILES.txt)。仅准备 `RoadDescription/` 子目录内容；不包含 `opt_v56`、道路施工系统或原始 GIS。发布只更新此子目录，实际提交与推送状态以 Git 历史为准。

本地旧说明、过程记录、表格及不再被脚本引用的配置已移入忽略的 `local_archive/`，迁移哈希记录见该目录的 `整理记录.json`。运行配置和历史工具引用的配置已统一移入 `configs/` 并忽略，代码与命令已同步；旧输出保留原路径，避免破坏证据引用。不得把本地归档整体加入 Git。
