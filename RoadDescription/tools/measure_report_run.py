"""Summarize one pipeline run: wall time and provider-reported usage, without pricing guesses."""
import argparse,json,sys
from pathlib import Path
from collections import defaultdict
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from road_description.io import read_json,write_json, config_root


def usage_summary(calls):
    totals=defaultdict(int);phases={}
    for call in calls:
        phase=call.get('purpose','unclassified_legacy');row=phases.setdefault(phase,defaultdict(int))
        row['logical_calls']+=1;row['http_attempts']+=call.get('attempts',1)
        usage=call.get('usage_attempts')
        if usage is None:usage=[call['usage']] if call.get('usage') else []
        row['attempts_with_usage']+=len(usage)
        row['attempts_without_usage']+=max(0,call.get('attempts',1)-len(usage))
        for item in usage:
            for key in ('prompt_tokens','completion_tokens','total_tokens'):
                row[key]+=item.get(key,0) or 0
            details=item.get('prompt_tokens_details') or {}
            row['cached_prompt_tokens']+=details.get('cached_tokens',0) or 0
            row['cache_creation_tokens']+=details.get('cache_creation_tokens',0) or 0
    for row in phases.values():
        for k,v in row.items():totals[k]+=v
    return {'totals':dict(totals),'by_purpose':{k:dict(v) for k,v in phases.items()}}


def measure(config_path):
    p=Path(config_path).resolve();c=read_json(p);out=(config_root(p,c)/c['output_dir']).resolve()
    events=[json.loads(line) for line in (out/'run_events.jsonl').read_text().splitlines() if line.strip()]
    job=read_json(out/'report_job.json');events=[e for e in events if e['run_id']==job['run_id']]
    models=read_json(out/'model_calls.json');value=usage_summary(models['calls'])
    last=events[-1];review=next((x for x in events if x['stage']=='reviewing_reports'),None)
    wall=last['elapsed_s'];generation=review['elapsed_s'] if review else wall
    value.update(run_id=job['run_id'],pipeline_status=job['stage'],last_logged_stage=last['stage'],
        started_at=events[0]['time'],last_logged_at=last['time'],wall_seconds=wall,
        generation_seconds=generation,quality_review_seconds=max(0,wall-generation),
        concurrency_limit=models['concurrency_limit'],peak_active=models['peak_active'],
        scope='单次完整流水线；复用已归档规划响应及瓦片缓存，包括三Agent、Word/PDF和所有输出文档审阅。前期开发、额外重跑与重新路径规划不计入。',
        token_scope='API返回的usage；包括记录到usage的失败/重试请求；缓存命中已包含在输入token中，不重复叠加。不提供usage的请求无法精确计量。',
        money='未给出接入平台结算单价，不将官方模型价格套用到中转平台，也不虚报人民币费用。')
    if (out/'model_calls_consistency.json').exists() and (out/'review_consistency_timing.json').exists():
        timing=read_json(out/'review_consistency_timing.json')
        extra=usage_summary(read_json(out/'model_calls_consistency.json')['calls'])
        value['followup_review']={**extra,**timing}
        value['combined_usage']=usage_summary(models['calls']+read_json(out/'model_calls_consistency.json')['calls'])
        value['combined_processing_seconds']=wall+timing['elapsed_seconds']
        value['combined_scope']='首次流水线加补充审阅分级复核的处理时长之和，未计两次运行间的开发排查间隔；不是整段对话的墙钟时间。'
    quality=read_json(out/'quality_review.json')
    value['documents']=[{'id':d['id'],'pages':d['pages']} for d in quality['documents']]
    value['reviewed_pages']=quality['vision_pages_reviewed']
    write_json(out.parent/'单次运行用量与耗时.json',value)
    t=value['totals'];lines=['单次完整运行实测',value['scope'],'',f"状态：{job['stage']}；运行ID：{job['run_id']}",
        f'生成报告：{generation:.1f}秒（{generation/60:.2f}分钟）',
        f'全文/逐页审阅：{wall-generation:.1f}秒（{(wall-generation)/60:.2f}分钟）',
        f'合计墙钟时间：{wall:.1f}秒（{wall/60:.2f}分钟）',
        f"输入token：{t.get('prompt_tokens',0):,}；输出token：{t.get('completion_tokens',0):,}；总token：{t.get('total_tokens',0):,}",
        f"模型调用：{t.get('logical_calls',0)}；HTTP尝试：{t.get('http_attempts',0)}；实际峰值并发：{models['peak_active']}",
        f"无usage的HTTP尝试：{t.get('attempts_without_usage',0)}",'',value['token_scope'],'',value['money'],'','分阶段：']
    lines.extend(f"{k}：{v['logical_calls']}次；输入{v.get('prompt_tokens',0):,}、输出{v.get('completion_tokens',0):,}、总token {v.get('total_tokens',0):,}" for k,v in value['by_purpose'].items())
    if 'followup_review' in value:
        extra=value['followup_review'];total=value['combined_usage']['totals']
        lines.extend(['',f"补充审阅分级复核：{extra['elapsed_seconds']:.1f}秒，{extra['totals'].get('total_tokens',0):,} token",
            f"累计处理用时：{value['combined_processing_seconds']:.1f}秒；累计token：{total.get('total_tokens',0):,}",value['combined_scope']])
    (out.parent/'单次运行用量与耗时.txt').write_text('\n'.join(lines)+'\n')
    return value

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--config',required=True);a=p.parse_args()
    print(json.dumps(measure(a.config),ensure_ascii=False,indent=2))
