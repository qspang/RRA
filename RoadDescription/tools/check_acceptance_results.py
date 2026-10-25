import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from docx import Document
from road_description.io import read_json,write_json
p=Path('outputs/acceptance_fixture_20261025');comparison=read_json(p/'agents/route_comparison/result.json');compliance=read_json(p/'agents/route_compliance/result.json')
checks=[]
def check(label,value):checks.append({'check':label,'passed':bool(value)})
check('确认推荐意见进入结果',comparison['recommendation']['recommended_scheme_id']=='upper')
check('按确认推荐只装配北方案',len(read_json(p/'agents/assembly/result.json')['documents'])==1)
for sid in ('upper','lower'):
 special=comparison['specialists'][sid]
 check(sid+'专项资料全部进入',all(x['status']=='confirmed_input' for x in special.values()))
 check(sid+'分类长度比例闭合',special['terrain']['complete'] and abs(sum(t['percent'] for t in special['terrain']['totals'])-100)<.0001)
 r=compliance['schemes'][sid]
 check(sid+'确认拆迁、林木、停电资料进入',all(r[k]['status']=='confirmed_input' for k in ('demolition','forestry','outage')))
 check(sid+'跨越设计参数进入',r['crossings'][0]['design']['input']['span_m']==222)
 check(sid+'附条件协议仍未闭合',r['agreements']['status']=='pending')
 check(sid+'合规素材进入',any(f['kind']=='supplied_design' and f['sha256'] for f in r['figures']))
 check(sid+'比选素材进入',any(f['kind']=='supplied_design' and f['scheme_id']==sid for f in comparison['figures']))
 text='\n'.join(x.text for x in Document(r['document']['docx']).paragraphs)
 check(sid+'实际Word包含设计及停电文字','222m' in text and '测试停电方案' in text)
check('描述素材进入',sum(f['kind']=='supplied_design' for f in read_json(p/'figure_manifest.json'))==2)
r={'status':'passed' if all(x['passed'] for x in checks) else 'failed','scope':'明确标注的合成验收资料，不是实际调查或设计','checks':checks}
write_json(p/'acceptance_checks.json',r);print(r['status'],len(checks),'checks')
assert r['status']=='passed'
