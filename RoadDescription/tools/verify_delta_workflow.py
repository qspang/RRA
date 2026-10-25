"""Real planner calls with one explicit test road added to a private session."""
import sys,shutil
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from shapely.geometry import LineString
from road_description.planner import PlannerClient,select_scheme
from road_description.io import read_json,write_json,archive_map
out=Path('outputs/delta_acceptance_20261025');out.mkdir(exist_ok=True)
c=read_json('configs/config.complete.json');c.update(project_title='编辑地图接口验收（含明确新增的测试道路）',output_dir=str(out))
c['agents']['output_dir']=str(out/'agents');c['agents']['assembly']['enabled']=False
c['llm']['enabled']=False;c['vlm']['enabled']=False;c['quality_review']['enabled']=False
facts=read_json('outputs/chapter_audit_20261025/route_facts.json');line=LineString(facts['schemes'][0]['path'])
p=line.interpolate(2600);a=line.interpolate(2595);b=line.interpolate(2605);dx,dy=b.x-a.x,b.y-a.y;norm=(dx*dx+dy*dy)**.5
feature={'id':'rd_acceptance_added_road','name':'乡道','category':'交通敏感点','shape_type':'line',
 'geometry':[[p.x-dy/norm*150,p.y+dx/norm*150],[p.x+dy/norm*150,p.y-dx/norm*150]],
 'cross_rule':'allowed','tower_rule':'allowed','cross_cost':0,'min_cross_angle':0,'buffer_range':0,'parallel_bonus':0,'parallel_range':0}
c['request']['feature_adjustments']={'deleted_ids':[],'modified_features':[],'added_features':[feature]}
write_json('configs/config.delta-acceptance.json',c)
client=PlannerClient(c['planner_url']);health,map_data=client.initialize();archive_map(out,map_data);write_json(out/'health.json',health)
state={'status':'running','synthetic_feature':feature,'real_planner_calls':[]};write_json(out/'integration.json',state)
try:
 for sid in ('upper','lower'):
  payload=read_json('outputs/chapter_audit_20261025/'+sid+'/request.json');payload.pop('plan_run_id',None)
  payload['feature_adjustments']=c['request']['feature_adjustments']
  response=client.plan(payload,out/sid,poll_seconds=3,max_seconds=360);scheme=select_scheme(response)
  state['real_planner_calls'].append({'scheme_id':sid,'plan_run_id':response['plan_run_id'],'length_m':scheme['analysis']['total_length']})
  write_json(out/'integration.json',state)
 state['status']='planning_passed'
except Exception as exc:
 state.update(status='failed',error=str(exc)[:1000]);raise
finally:write_json(out/'integration.json',state)
