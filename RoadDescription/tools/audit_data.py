"""Human-readable audit of actual local names, regions, and compiled rules."""
import sys
import argparse
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from road_description.facts import Catalog
from road_description.io import read_json, config_root

root=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--config',default=str(root/'configs/config.demo.json'))
args=parser.parse_args()
config_path=Path(args.config).resolve();root=config_root(config_path)
config=read_json(config_path);out=root/config['output_dir']
catalog=Catalog(root/config['dataset'],read_json(out/'map.json'),config.get('name_overrides'))
lines=['现有系统的地物名称、区域与规则核查','',
       '一、HTML展示的数据来源',
       'templates/index.html约991行：悬浮框显示feature.name；该字段来自地物类别。',
       '约692行：图层分为primary原始地物、protection保护范围和reward奖励走廊，另有密集通道。',
       '约2575行：风冰区是风速/覆冰分区，不等于县区行政边界。',
       '约668/2486行：影像img_w与中文注记cia_w来自天地图。瓦片中的文字不是自动关联的GIS名称字段。',
       '', '二、本次实际可提取的名称覆盖（primary要素）',
       '列：类别 | 要素数 | 有专名数 | 有可识别县区属性数']
for category,stats in sorted(catalog.coverage().items()):
    lines.append(f"{category} | {stats['count']} | {stats['named']} | {stats['county_attributed']}")
lines+=['','三、可直接使用的正式名称样例（来自现有数据，不由模型猜测）']
for category in ['高速公路','国道','输电线路220kV','输电线路500kV','生态保护红线一般区域']:
    labels=[]
    for f in catalog.features:
        if f['category']==category and f['name'] and f['label'] not in labels:labels.append(f['label'])
    lines.append(category+'：'+'；'.join(labels[:12]))
lines+=['','四、规则核实样例']
for category in ['自然保护区缓冲区','一级水源保护区','生态保护红线一般区域','高速公路','输电线路220kV']:
    feature=next((f for f in catalog.features if f['category']==category),None)
    if feature:
        rule=catalog.rule(feature)
        lines.append(f"{category}：禁止通行={rule['cross_forbidden']}；禁立塔/保护带禁立塔={rule['tower_forbidden']}；跨越基础费={rule['cross_cost']}万元；最小交叉角={rule['min_cross_angle']}度。")
lines+=['','五、目前的实际边界',
       '相交地物的属地区县/村名可以提取，已用于报告；但尚无完整行政界线时，不宣称覆盖全线路，也不编造全线经过县区总数。',
       '河流原始SHP中未提供正式河名字段；水源地部分Name为空，descriptio字段已在原始SHP中截断。可以接受后续src_uid名称覆盖表补齐。',
       '部分名称位于生态红线的ZRBHDMC/HXMC中，已纳入名称解析；不能把一个红线片区的名字无条件挪给旁边另一个独立保护区。',
       '规则已进入报告。禁行、禁立塔、高跨越代价是不同含义；空间关系与规则共同支持报告语句，不能互相代替。']
(out/'地物名称与规则核查.txt').write_text('\n'.join(lines)+'\n',encoding='utf-8')
print(out/'地物名称与规则核查.txt')
