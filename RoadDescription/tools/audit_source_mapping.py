"""Export source-to-report mappings without private parcel-owner attributes."""
import argparse
import csv
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from report_agents.common.context import load_context
from report_agents.common.coverage import inventory
from road_description.io import write_json


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--config',default='configs/config.source-review.json')
    parser.add_argument('--output',default='outputs/source_review_20261025')
    args=parser.parse_args();ctx=load_context(args.config);out=Path(args.output);out.mkdir(parents=True,exist_ok=True)
    coverage=ctx.catalog.coverage()
    result={'provenance':ctx.catalog.provenance,'categories':coverage,
            'theme_screening':inventory(ctx.catalog,ctx.facts['schemes'],1000),
            'name_examples':[{'uid':f['uid'],'category':f['category'],'label':f['label'],'name_source':f['name_source']}
                for f in ctx.catalog.features if f['name'] and '云嘉' in f['name']],
            'scope':'地物原始矢量和报告补充矢量；没有把NPY分类值当正式名称'}
    write_json(out/'source_mapping.json',result)
    with (out/'地物映射核查.csv').open('w',encoding='utf-8-sig',newline='') as stream:
        writer=csv.writer(stream);writer.writerow(['报告类别','对象数','有名称数','有县区属性数','图层范围'])
        replaced={s['category'] for s in ctx.catalog.provenance.get('supplemental_layers',[])}
        for name,row in sorted(coverage.items()):writer.writerow([name,row['count'],row['named'],row['county_attributed'],
            '原始GDB报告补充图层' if name in replaced else '规划数据包M1 primary'])
    print(json.dumps({'status':'completed','categories':len(coverage),'output':str(out)},ensure_ascii=False))


if __name__=='__main__':main()
