"""Explicitly synthetic specialist/material acceptance case, separate from real draft."""
import json,shutil,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import pymupdf
from road_description.io import read_json,write_json
root=Path.cwd();source=Path('outputs/implementation_complete_20261025');out=Path('outputs/acceptance_fixture_20261025');out.mkdir(exist_ok=True)
c=read_json('configs/config.complete.json');c.update(project_title='功能验收测试资料样章（非真实调查与设计结论）',output_dir=str(out))
c['agents']['output_dir']=str(out/'agents');c['llm']['enabled']=False;c['vlm']['enabled']=False;c['quality_review']['enabled']=False
for name in ('map.json','map.raw.json.gz','health.json','route_generation.json'):
 shutil.copy2(source/name,out/name)
for sid in ('upper','lower'):
 (out/sid).mkdir(exist_ok=True)
 for name in ('request.json','response.json'):shutil.copy2(source/sid/name,out/sid/name)
(out/'fixture_source.txt').write_text('功能验收专用合成资料：所有数量、专业意见和推荐均非工程事实，只用于测试输入到成稿。\n',encoding='utf-8')
with pymupdf.open() as pdf:
 page=pdf.new_page(width=500,height=260);page.insert_text((25,55),'SYNTHETIC ACCEPTANCE MATERIAL',fontsize=18)
 page.insert_text((25,100),'Not a field photograph or engineering design.',fontsize=12)
 pdf.save(out/'fixture_material.pdf')
facts=read_json(source/'route_facts.json');compliance=read_json(source/'agents/route_compliance/result.json')
def confirmed(**kw):return {'confirmed':True,'source_file':str(out/'fixture_source.txt'),'text':'功能验收测试说明，不是工程结论',**kw}
supplement={'schemes':{}};materials=[]
for fact in facts['schemes']:
 sid=fact['id'];length=fact['metrics']['length_m'];event=compliance['schemes'][sid]['crossings'][0]
 supplement['schemes'][sid]={'route_geometry_hash':fact['geometry_hash'],
   'surveys':{'demolition':confirmed(records=[{'kind':'测试棚','quantity':123,'unit':'m2'}]),
              'forestry':confirmed(forest_length_m=100,records=[{'species':'测试树种','height_m':12,'felling_area_m2':34}])},
   'specialists':{'terrain':confirmed(records=[{'class':'测试地形A','start_m':0,'end_m':length/2},{'class':'测试地形B','start_m':length/2,'end_m':length}]),
                 'traffic':confirmed(text='测试交通意见：用于验证已确认资料接入。'),
                 'military':confirmed(text='测试军事专项意见：非真实调查结论。'),
                 'mining':confirmed(text='测试矿权意见：非真实矿权资料。'),
                 'ecology':confirmed(text='测试生态专项意见：非真实处理措施。',records=[])},
   'crossing_designs':[confirmed(source_uids=event['source_uids'],chainage_m=event['start_m'],
       tower_arrangement='测试塔型排列',span_m=222,tension_length_m=555,design_angle_deg=60,clearance_note='测试净空说明',joint_note='测试接头说明')],
   'outage':confirmed(text='测试停电方案：仅验证成稿，不作运行安排。'),
   'agreements':[confirmed(region='测试行政区',department='测试部门',status='conditional',conditions='测试条件尚未闭合')],
   'required_departments':[{'region':'测试行政区','department':'测试部门'}]}
 materials.append({'id':'fixture_'+sid,'scheme_id':sid,'route_geometry_hash':fact['geometry_hash'],
                   'path':str(out/'fixture_material.pdf'),'caption':'功能验收用素材，非现场照片/设计图','kind':'supplied_design',
                   'approved':True,'targets':['description','comparison','compliance'],'fact_ids':[fact['events'][0]['fact_id']],
                   'event_id':event['event_id']})
supplement['recommendation']=confirmed(scheme_id='upper',route_geometry_hashes={s['id']:s['geometry_hash'] for s in facts['schemes']},
    text='测试推荐意见：只用于验证北方案整册选择，不是工程推荐。',conflict_note='测试条件不消除原有复核待办')
write_json(out/'supplement.json',supplement);c['agents']['supplemental_file']=str(out/'supplement.json');c['materials']=materials
write_json('configs/config.acceptance-fixture.json',c)
print('Prepared explicitly synthetic acceptance case; original draft/config unchanged.')
