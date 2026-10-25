"""Live report service contracts and active planner cancellation."""
import time,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import requests
from road_description.io import write_json,read_json
base='http://127.0.0.1:5010';out=Path('outputs/implementation_complete_20261025/integration/report_service');out.mkdir(parents=True,exist_ok=True)
r={};r['health']=requests.get(base+'/api/health',timeout=10).json()
r['ui_status']=requests.get(base,timeout=10).status_code
r['invalid_input_status']=requests.post(base+'/api/reports',json={'start':['bad',0]},timeout=10).status_code
r['foreign_origin_status']=requests.post(base+'/api/reports',json={},headers={'Origin':'http://other.test'},timeout=10).status_code
response=requests.post(base+'/api/reports',json={'replan':True},timeout=15);response.raise_for_status();jid=response.json()['id'];r['cancel_job_id']=jid;write_json(out/'checks.json',r)
folder=Path('outputs/report_jobs')/jid/'output';deadline=time.monotonic()+100
while time.monotonic()<deadline:
 progress=list(folder.glob('planning_attempts/*/progress.json'))
 if any(read_json(p).get('status')=='active' or read_json(p).get('stage') for p in progress):break
 state=requests.get(base+'/api/reports/'+jid,timeout=10).json()
 if state['status'] in ('failed','completed','review_required'):break
 time.sleep(1)
r['cancel_response']=requests.post(base+'/api/reports/'+jid+'/cancel',json={},timeout=15).json()
for _ in range(20):
 state=requests.get(base+'/api/reports/'+jid,timeout=10).json()
 if state['status']=='cancelled':break
 time.sleep(1)
r['final_status']=state['status']
r['planner_cancel_proof']=[read_json(p) for p in folder.glob('planning_attempts/*/cancellation.json')]
r['download_traversal_status']=requests.get(base+'/api/reports/'+jid+'/files/%2e%2e/config.json',timeout=10).status_code
r['status']='passed' if (r['invalid_input_status']==400 and r['foreign_origin_status']==403 and r['final_status']=='cancelled' and
 any(x.get('response',{}).get('cancelled') is True for x in r['planner_cancel_proof']) and r['download_traversal_status']==403) else 'needs_review'
write_json(out/'checks.json',r);print(r)
