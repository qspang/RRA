"""Live project/revision/job integration in a newly owned test project."""
import sys,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from road_description.planner import PlannerClient,select_scheme
from road_description.io import read_json,write_json
out=Path('outputs/implementation_complete_20261025/integration/project_job');out.mkdir(parents=True,exist_ok=True)
c=PlannerClient('http://127.0.0.1:5000')
state={'status':'running'}
try:
 p=c.create_project('RoadDescription接口验收_'+str(int(time.time())));state['project_id']=p['id'];write_json(out/'state.json',state)
 m=c.import_map(p['id']);state['map_id']=m['id'];write_json(out/'state.json',state)
 payload=read_json('outputs/chapter_audit_20261025/upper/request.json');payload.pop('plan_run_id',None)
 s=c.create_scenario(p['id'],m['id'],'北方案真实短线接口验收',payload);state['revision_id']=s['head'];write_json(out/'state.json',state)
 j=c.submit_job(p['id'],s['head'],'road-description-live-'+str(int(time.time())));state['job_id']=j['id'];write_json(out/'state.json',state)
 result=c.wait_job(j['id'],out,max_seconds=360,poll_seconds=3);selected=select_scheme(result)
 state.update(status='passed',length_m=selected['analysis']['total_length'],feasible=selected['feasible'])
except Exception as exc:
 state.update(status='failed',error_type=type(exc).__name__,error=str(exc)[:1200]);raise
finally:write_json(out/'state.json',state)
print(state)
