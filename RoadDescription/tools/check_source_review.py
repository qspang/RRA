"""Check the source-review deliverable against the user's concrete questions."""
import json
import re
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from road_description.io import read_json,write_json,file_hash

root=Path(__file__).resolve().parents[1]
base=root/'outputs/source_review_20261025';out=base/'report'
comparison=read_json(out/'agents/route_comparison/result.json')
compliance=read_json(out/'agents/route_compliance/result.json')
review=read_json(out/'quality_review.json')
coverage={r['type']:r for r in comparison['coverage']}
checks=[]
def check(name,value):checks.append({'check':name,'passed':bool(value)})
check('回归测试61项通过','61 passed' in (base/'tests.log').read_text())
check('完整运行结束',read_json(out/'report_job.json')['stage']=='completed')
check('全文及逐页质量审阅通过',review['status']=='passed')
check('交付完整性通过',read_json(out/'delivery_manifest.json')['status']=='passed')
check('原始生态GDB覆盖463要素',coverage['生态敏感点']['dataset_count']==463)
check('矿区缺图层和未穿越分别表达',coverage['矿区']['dataset_count']==0 and coverage['高速公路']['dataset_count']>0)
for sid in ['upper','lower']:
    eco=coverage['生态敏感点']['schemes'][sid]['nearest']
    check(sid+'最近生态对象来自完整GDB','莲花山' in eco['label'] and abs(eco['distance_m']-3359.428964)<.01)
    check(sid+'高速无相交且有最近距离',coverage['高速公路']['schemes'][sid]['intersecting_features']==0 and abs(coverage['高速公路']['schemes'][sid]['nearest']['distance_m']-2597.285388)<.01)
    data=compliance['schemes'][sid]
    check(sid+'补充道路进入合规分析',any(any(u.startswith('supp:') for u in e['source_uids']) for e in data['crossings']))
    a=next(i for i,b in enumerate(data['blocks']) if b.get('text','').startswith('3.4.8.1'))
    b=next(i for i,b in enumerate(data['blocks']) if b.get('text','').startswith('3.4.8.2'))
    section=json.dumps(data['blocks'][a:b],ensure_ascii=False)
    check(sid+'跨越正文不以算法规则或角度占位为主体','系统阈值' not in section and '几何交叉角/规则' not in section and '设计交叉角' not in section)
    check(sid+'一般道路集中索引图',any(x['type']=='figure_grid' for x in data['blocks'][a:b]))
    c=next(i for i,x in enumerate(data['blocks']) if x.get('text','').startswith('3.4.9'))
    outage=json.dumps(data['blocks'][b:c],ensure_ascii=False)
    check(sid+'停电协调对象与结构完整',all(t in outage for t in ['云嘉甲乙线','待调度确认','停电方案及影响分析','实施顺序与保障措施']))
    check(sid+'跨越图全部为真实卫星底图',all(f['kind']=='satellite_map' for f in data['figures'] if f.get('event_id')))
    original=root/'outputs/report_jobs/6f7fefac37464d2196ea09fd3337c76a/output'/sid/'response.json'
    check(sid+'归档规划响应未被补充数据改写',file_hash(original)==file_hash(out/sid/'response.json'))
capture=read_json(base/'ui_capture.json')
check('规划界面实际截图成功',capture['loaded']>0 and capture['failed']==0 and (base/'规划系统可视化截图.png').is_file())
check('两份Markdown已生成',all((root/p).is_file() for p in ['甲方待补资料与本轮数据核查_20261025.md','发甲方_路径报告待补资料清单.md']))
assembly=read_json(out/'agents/assembly/result.json')['documents']
all_doc=next(d for d in assembly if d['scheme_id']=='all')
check('完整报告包括要求的章节',all(any(h.startswith(s+' ') for h in all_doc['contents']) for s in ['3.3','3.3.1','3.3.2','3.4.8','3.4.9','3.4.10','3.4.11','3.5']))
result={'status':'passed' if all(c['passed'] for c in checks) else 'failed','checks':checks,
        'full_report':all_doc,'pdf_sha256':file_hash(all_doc['pdf']['path']),
        'scope':'当前测试路线、补充源数据、章节正文与影像输出；正式设计/调度/审批资料仍待补充'}
write_json(base/'acceptance.json',result)
print(json.dumps({'status':result['status'],'checks':len(checks),'pages':all_doc['pdf']['pages'],
                  'failed':[c for c in checks if not c['passed']]},ensure_ascii=False))
if result['status']!='passed':raise SystemExit(1)
