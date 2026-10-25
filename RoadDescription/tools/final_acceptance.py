"""Aggregate actual evidence; do not turn external-data gaps into invented approvals."""
import json,re,shutil,sys,subprocess,zipfile
from pathlib import Path
from datetime import datetime
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from road_description.io import read_json,write_json,file_hash

root=Path(__file__).resolve().parents[1];base=root/'outputs/implementation_complete_20261025'
job=read_json(base/'integration/final_service_result.json');out=root/'outputs/report_jobs'/job['job_id']/'output'
q=read_json(out/'quality_review.json');calls=read_json(out/'model_calls.json');delivery=read_json(out/'delivery_manifest.json')
checks=[]
def check(name,ok):checks.append({'check':name,'passed':bool(ok)})
test=subprocess.run([sys.executable,'-m','pytest','tests','-q'],cwd=root,capture_output=True,text=True)
(base/'tests.log').write_text(test.stdout+test.stderr)
match=re.search(r'(\d+) passed',test.stdout);test_count=int(match[1]) if match else 0
check('全部回归测试',test.returncode==0 and test_count>0)
check('真实报告任务完成',job['status']=='completed' and read_json(out/'report_job.json')['stage']=='completed')
check('真实报告全文和逐页审阅',q['status']=='passed' and q['vision_pages_not_reviewed']==0)
check('逐Agent交付检查',delivery['status']=='passed')
check('下载文件内容一致',len(job['downloads'])==6 and all(x['http_status']==200 and x['bytes_match'] for x in job['downloads']))
check('模型实际成功调用且并发不超15',all(x['status']=='completed' for x in calls['calls']) and calls['peak_active']<=15)
for folder,name in [('project_job','工程异步任务整链'),('report_service','报告服务与运行中取消'),('map_edits','增量地图增删改回放')]:
    filename='state.json' if folder=='project_job' else 'checks.json'
    check(name,read_json(base/'integration'/folder/filename)['status']=='passed')
for folder,name in [('acceptance_fixture_20261025','补充资料进入实际Word'),('delta_acceptance_20261025','编辑地图后的真实规划与报告')]:
    p=root/'outputs'/folder
    check(name,read_json(p/'acceptance_checks.json')['status']=='passed')
    check(name+'排版检查',read_json(p/'quality_review.json')['status']=='passed')
check('最终事实与当前代码重算一致',all(x['same_verified_facts'] for x in read_json(base/'integration/final_facts_recheck.json')))
inventory=read_json(root/'outputs/renai_sonnet46_20261025/original_config_inventory.json')
check('原有配置保留',all(file_hash(root/x['file'])==x['sha256'] for x in inventory))
for doc in q['documents']:
    check(doc['id']+'与已审阅版本一致',file_hash(doc['docx'])==doc['docx_sha256'] and file_hash(doc['pdf'])==doc['pdf_sha256'])
configuration=read_json(root/'configs/config.complete.json');settings=configuration['llm']
from road_description.model_runtime import credential
settings['credential_file']=str(root/settings['credential_file']);secret=credential(settings).encode()
check('输出和日志无密钥',bool(secret) and not any(secret in p.read_bytes() for folder in (out,base) for p in folder.rglob('*') if p.is_file()))
result={'status':'passed' if all(c['passed'] for c in checks) else 'needs_fix','checked_at':datetime.now().isoformat(),
        'tests_passed':test_count,'checks':checks,'service_job_id':job['job_id'],'document_count':len(q['documents']),
        'pages':sum(d['pages'] for d in q['documents']),'model_calls':len(calls['calls']),
        'http_attempts':sum(x['attempts'] for x in calls['calls']),'peak_concurrency':calls['peak_active'],
        'documents':q['documents'],'external_pending_count':len(delivery['missing']),
        'scope':'当前真实样例、明确标记的验收资料和接口契约已验证；非正式全线审批或未知输入的无缺陷保证'}
write_json(base/'final_acceptance.json',result)
if result['status']!='passed':
    print(json.dumps([c for c in checks if not c['passed']],ensure_ascii=False));sys.exit(2)
bundle=root/'outputs/delivery_20261025';bundle.mkdir(exist_ok=True)
for doc in q['documents']:
    for key in ('docx','pdf'):shutil.copy2(doc[key],bundle/Path(doc[key]).name)
shutil.copy2(out/'本轮资料缺口.txt',bundle/'本轮资料缺口.txt')
shutil.copy2(base/'final_acceptance.json',bundle/'验收结果.json')
intro=f'''三个Agent代码完善与当前验收结果
验收时间：{result['checked_at']}
当前结论：{result['status']}。{test_count}项回归测试、{len(checks)}项交付验收通过。
真实LLM/VLM调用{result['model_calls']}次，HTTP请求{result['http_attempts']}次，并发峰值{result['peak_concurrency']}。
最终6份Word/PDF，共{result['pages']}页：4份独立稿，2份含目录的候选整册。
尚未指定正式推荐方案，因此两个候选方案分别编册，不擅自选择北方案。

已补齐的代码
1. 山谷相交事实、里程、长度、正文与图件。现有北方案2处，南方案0处。
2. 地形分类分段/比例、交通、军事、矿权专题输入；验证来源和路线版本。
3. 逐生态对象的确认处理措施和专业推荐意见；保留冲突与缺项。
4. 图片/PDF素材统一供描述、比选、合规使用，按事实或跨越事件绑定，记录源文件哈希。
5. 基础地图与canonical增量合成，运行规则和约束同步核查；支持完整快照和懒加载地物补全。
6. 三Agent独立运行、整册装配、实际目录页码核对、逐页检查和资料缺口清单。
7. 本地报告工作台和异步任务接口：提交、状态、日志、取消、下载；每任务独立目录。
8. 工程模式建工程、导入地图、建方案、提交任务和取结果的适配及真实联调。
9. 阶段日志、运行ID、耗时、错误类型、模型请求留痕、文件哈希和交付检查。
10. 修复重复跨越近距离合并、接触误算跨越、部分设计参数掩盖缺项等边界。

实际验收与迭代
- 新建私有测试工程，完整执行异步任务，得到8464.2m的可行路线。
- 真实规划过程中从报告服务发出取消，规划服务回执cancelled=true；报告任务结束为cancelled。
- 新增明确的测试道路后，真实调用两次规划，北方案新增地物进入描述和合规；该测试输出与正常稿隔离。
- 使用明确标记的合成专项资料，19项成稿检查通过；此类测试数量/意见没有混入正常交付。
- 地图回放曾发现上游M1几何移动未实际生效的差异，现已加拦截，不生成虚假的移动后位置。规则修改/删除/新增回放验收通过。
- 上游M1编辑按现有契约是规则编辑；移动原始几何应先在规划系统中完成受支持的对象重建或重处理，再生成报告。南北方案必须使用同一地图修订。
- 缺页/空白页、字段来源、版本不匹配、错误参数、下载越界和实际下载内容均有检查。

直接使用
工作台：http://127.0.0.1:5010（当前已启动，仅监听本机）。
启动：taskset -c 16-19 .venv/bin/python -m road_description.service --config configs/config.complete.json --port 5010
完整CLI复跑：taskset -c 16-19 .venv/bin/python -m road_description --config configs/config.complete.json
按起终点重新规划：上述CLI命令末尾加 --plan，或在工作台勾选重新规划。
按本次最终任务目录复跑：--config configs/config.delivery-final.json
独立插件：.venv/bin/python -m report_agents --config configs/config.complete.json --agents route_description
其他插件ID：route_comparison、route_compliance。
资料格式：report_agents/补充资料与素材接口_v0.4.txt、supplemental.example.json、materials.example.json。

HTTP接口
POST /api/reports，JSON={{"start":[14000,6000],"end":[6673.647261974464,2681.2622931214955],"replan":false}}
GET /api/reports/<id>：任务状态、阶段及成果列表。
GET /api/reports/<id>/log：最近日志。
POST /api/reports/<id>/cancel：取消该任务及正在执行的同步规划。
GET /api/reports/<id>/files/<文件相对路径>：下载成果，禁止越出任务输出目录。
报告任务串行执行，每任务内模型并发上限15；避免多个报告任务叠加超过要求。

日志与证据
最终任务目录：{out}
run_events.jsonl：主流程阶段和耗时；agents/run_events.jsonl：三个Agent和整册阶段。
workflow.log：实际运行输出/异常堆栈；model_calls.json：真实模型调用、重试、用量和并发。
delivery_manifest.json：文件哈希、图层覆盖、缺项；quality_review.json：全部成稿审阅。
集成测试目录：{base/'integration'}
tests.log、final_acceptance.json：回归与总验收。

业务资料边界
当前正常报告仍是约8km真实测试区段，不代表参考PDF正式44/47km全线。
现场照片、完整行政区划、逐塔/跨越设计、停电、拆迁/林业调查、专题成果和复函，按实际输入保留待补。
仍需确认测试起点站址及终端塔前提；统计塔数量和DEM剖面不能代替逐塔/弧垂/净空设计。
Word指定宋体/Times New Roman；当前预览使用可用字体，正式字体环境仍需复核。
整册目录是按实际渲染页码生成的可编辑内容；手工改稿后需重跑装配或手工校对页码。
本次未将测试资料当实际调查，也未把技术检查通过写成正式合规批准。
'''
(root/'三Agent代码完善与验收_20261025.txt').write_text(intro,encoding='utf-8')
(bundle/'使用与验收说明.txt').write_text(intro,encoding='utf-8')
with zipfile.ZipFile(root/'outputs/三个Agent成果与验收_20261025.zip','w',zipfile.ZIP_DEFLATED) as archive:
    for p in sorted(bundle.iterdir()):
        if p.is_file():archive.write(p,p.name)
print(result['status'],test_count,'tests',len(checks),'acceptance checks',result['pages'],'pages')
