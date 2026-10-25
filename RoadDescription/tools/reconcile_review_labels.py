"""Reconcile internally contradictory text-review labels without changing reports."""
import argparse,sys,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from road_description.io import read_json,write_json,file_hash, config_root
from road_description.model_runtime import prepare_model_config,telemetry
from road_description.quality_review import check_review_consistency

def main():
 started=time.monotonic()
 from datetime import datetime,timezone
 started_at=datetime.now(timezone.utc).isoformat()
 p=argparse.ArgumentParser();p.add_argument('--config',required=True);a=p.parse_args()
 config_path=Path(a.config).resolve();c=read_json(config_path);prepare_model_config(c,config_root(config_path,c))
 out=(config_root(config_path,c)/c['output_dir']).resolve();r=read_json(out/'quality_review.json')
 for d in r['documents']:
  if file_hash(d['docx'])!=d['docx_sha256'] or file_hash(d['pdf'])!=d['pdf_sha256']:
   raise ValueError('报告文件已变化，需完整重审')
 history=out/'quality_review/history';history.mkdir(exist_ok=True)
 write_json(history/('before_label_consistency_'+str(time.time_ns())+'.json'),r)
 for item in r['reviews']:
  if item['id'] not in r['blocking_reviews'] or item['kind']!='text':continue
  value,trace=check_review_consistency(c['llm'],item['result'])
  item.update(result=value,consistency_review=trace)
  write_json(out/'quality_review'/(item['id']+'.json'),item)
  print(item['id'],value['verdict'],flush=True)
 r['blocking_reviews']=[x['id'] for x in r['reviews'] if x['status']=='completed' and any(i['severity']=='blocking' for i in x['result']['issues'])]
 r['status']='passed' if all(x['passed'] for x in r['checks']) and not r['blocking_reviews'] and not r['failed_reviews'] else 'needs_review'
 write_json(out/'quality_review.json',r);write_json(out/'model_calls_consistency.json',telemetry())
 state=read_json(out/'report_job.json');state['quality_review']['status']=r['status'];state['stage']='completed' if r['status']=='passed' else 'review_required';write_json(out/'report_job.json',state)
 write_json(out/'review_consistency_timing.json',{'started_at':started_at,'completed_at':datetime.now(timezone.utc).isoformat(),'elapsed_seconds':time.monotonic()-started,'scope':'补充审阅意见分级复核；未重新生成报告'})
 print(r['status'],r['blocking_reviews'])
 if r['status']!='passed':raise SystemExit(2)

if __name__=='__main__':main()
