from collections import Counter
import csv
import math

from shapely.geometry import LineString

from road_description.figures import generate_figures
from road_description.presentation import reference_style,major_event
from road_description.narrative import compose
from road_description.model_runtime import parallel_map
from . import __doc__ as description
from ..common.gis import scheme_measurements, is_ecology
from ..common.report import heading, prose, table, organise, render_document
from ..common.supplement import survey, agreements
from ..common.specialists import specialist, recommendation
from road_description.materials import approved_materials
from ..common.coverage import inventory, scope_text


def comparable_cost(ctx):
    signatures = []
    for fact in ctx.facts['schemes']:
        response = ctx.responses[fact['id']]
        analysis = ctx.schemes[fact['id']]['analysis']
        version = analysis.get('cost_model_version')
        evaluation = analysis.get('engineering_evaluation', {})
        cost = analysis.get('total_cost')
        if not version or not evaluation.get('version') or not isinstance(cost,(int,float)) or not math.isfinite(cost):
            return False
        params = response.get('params', {})
        signatures.append((version, {k:evaluation.get(k) for k in ('version','scope','cell_size_m','independent_of_search_resolution')},
            {k: params.get(k) for k in ('cost_max_tower_spacing', 'normal_max_tower_spacing',
             'min_tower_spacing', 'forbidden_crossing_max_tower_spacing', 'manual_relax_regions')},
            response.get('dem_loaded')))
    return all(s == signatures[0] for s in signatures[1:])


def quantities(value):
    if value['status'] != 'confirmed_input':
        return '待调查确认'
    if not value['records']:
        return '已确认调查记录为空；范围见来源'
    return '；'.join(f"{r['kind']}：{r['quantity']:g}{r['unit']}" for r in value['records'])


class RouteComparisonAgent:
    manifest = {'id': 'route_comparison', 'version': '0.2.0', 'name': '路径方案比选Agent',
                'sections': ['3.3', '3.3.1', '3.3.2', '3.3.3'],
                'description': description, 'depends_on': [],
                'inputs': ['两方案最终响应', '原始地物与系统规则', '可选DEM/调查与协议资料'],
                'outputs': ['综合比较JSON/CSV', 'Word', 'PDF', '待补项']}

    def run(self, ctx):
        out = ctx.output/'route_comparison'
        out.mkdir(parents=True, exist_ok=True)
        facts = ctx.facts['schemes']
        measured = {f['id']: scheme_measurements(ctx, f) for f in facts}
        demolition = {f['id']: survey(ctx, f['id'], 'demolition') for f in facts}
        letters = {f['id']: agreements(ctx, f['id']) for f in facts}
        analysis = {f['id']: ctx.schemes[f['id']]['analysis'] for f in facts}
        specials = {f['id']:{key:specialist(ctx,f['id'],key) for key in ('terrain','traffic','military','mining')} for f in facts}
        compact=reference_style(ctx.config)
        columns = ['项目']+[f['name'] for f in facts]+['依据与限制']
        matrix = []
        def add(label, values, note):
            matrix.append([label, *values, note])
        add('线路长度/km', [f"{f['metrics']['length_m']/1000:.3f}" for f in facts], '最终路径二维中心线几何；与API长度核对')
        elevations = []
        for f in facts:
            e = measured[f['id']]['elevation']
            elevations.append(f"{e['min_m']:.1f}～{e['max_m']:.1f}m（{e['valid_samples']}/{e['samples']}有效样点）" if e.get('min_m') is not None else '待补DEM')
        add('海拔分布', elevations, 'DEM沿线采样；不是完整地形断面，高程基准待核')
        add('沿线高程起伏（辅助）', [f"累计上升{measured[f['id']]['relief']['ascent_m']:.0f}m、下降{measured[f['id']]['relief']['descent_m']:.0f}m；最大采样纵坡{measured[f['id']]['relief']['max_sample_grade_percent']:.1f}%" if measured[f['id']]['relief']['status']=='measured' else '无有效DEM采样' for f in facts], '相邻有效高程点计算，不能代替正式地形分类及比例')
        add('风冰区资料', ['；'.join(f"风速{r['wind_ms']:g}m/s、覆冰{r['ice_mm']:g}mm：{r['length_m']/1000:.3f}km" if r['wind_ms'] is not None and r['ice_mm'] is not None else '风/冰字段不完整' for r in measured[f['id']]['weather_zones']['records']) or '现有风冰图层未覆盖' for f in facts], '按五十年一遇原始风冰区图层；覆盖缺口见JSON，不用默认值填齐')
        add('曲折系数', [f"{f['metrics']['tortuosity']:.3f}" for f in facts], '路径长度/共同起终点平面直线距离')
        add('地形划分及比例', ['；'.join(f"{r['class']}：{r['length_m']/1000:.3f}km（{r['percent']:.1f}%）" for r in specials[f['id']]['terrain'].get('totals',[]))+('；分类未覆盖全线' if not specials[f['id']]['terrain'].get('complete') else '') if specials[f['id']]['terrain']['status']=='confirmed_input' else '待补地形分类资料' for f in facts], '采用有来源的人工分类分段；比例分母为全线长度')
        add('山谷图示范围相交', [str(len(f.get('terrain',[])))+'个事件' for f in facts], '原始山谷几何；不能代替丘陵/山地/高山分类')
        add('沿线矿产情况', [specials[f['id']]['mining']['text'] if specials[f['id']]['mining']['status']=='confirmed_input' else '；'.join(x['label'] for x in measured[f['id']]['mining']) or
            ('现有矿区图层未检出相交' if measured[f['id']]['mining_layer_present'] else '缺专项矿区图层，待核') for f in facts], '仅按明确矿区类别核查，其他禁建区不直接视为矿区')
        crossing_counts = {}
        for f in facts:
            crossing_counts[f['id']] = dict(Counter(x['category'] for x in measured[f['id']]['crossings'] if not compact or major_event(x)))
        add('重要交叉跨越', ['；'.join(f'{k}：{v}次' for k,v in crossing_counts[f['id']].items()) or '现有图层未检出' for f in facts], '按原始地物几何事件统计；重复跨越分开计，同名碎片合并；不直接数费用条目')
        add('房屋拆迁面积/数量', [quantities(demolition[f['id']]) for f in facts], '只采用有来源且人工确认的调查；未调查不填0')
        add('建筑图斑筛查（辅助）', [f"{measured[f['id']]['building_screen']['feature_count']}个要素；相交面积{measured[f['id']]['building_screen']['polygon_overlap_m2']:.1f}m²" for f in facts], f"{ctx.options.get('building_screen_width_m',60):g}m总宽筛查带，不等于拆迁范围")
        add('穿越生态敏感区', ['；'.join(dict.fromkeys(x['label'] for x in measured[f['id']]['ecology'] if x['inside_length_m'] > .05)) or '现有图层未检出穿越' for f in facts], '原始敏感区边界相交；无交集不等于专题调查已完成')
        add('穿越生态保护红线/km', [f"{measured[f['id']]['ecological_redline_length_m']/1000:.3f}" for f in facts], '相交线段取并集，避免多个面重复累计')
        add('交通条件', [specials[f['id']]['traffic']['text'] if specials[f['id']]['traffic']['status']=='confirmed_input' else
            '现有地图识别到沿线道路；道路等级、路宽、承载和施工接入条件待调查' for f in facts], '道路存在或临近不直接推定运输条件好坏')
        add('军事设施', [specials[f['id']]['military']['text'] for f in facts], '当前分类数据不能证明“无军事设施”')
        add('有关单位意见', ['；'.join(f"{x['region']}{x['department']}：{x['status_label']}" for x in letters[f['id']]['records']) or '未提供复函资料' for f in facts], '不复制参考PDF中的政府意见')
        cost_ok = comparable_cost(ctx)
        add('模型总成本/万元', [f"{analysis[f['id']]['total_cost']:.2f}" if analysis[f['id']].get('total_cost') is not None else '缺失' for f in facts], '当前统计塔模型计价，非工程概算；'+('同口径可比' if cost_ok else '口径未统一，不自动排序'))
        add('杆塔数量/个', [str(analysis[f['id']].get('total_tower_count', '缺失')) for f in facts], 'API统计数量，直线塔未必逐塔定位')
        check_names={'forbidden_polygons':'禁行范围','no_tower_polygons':'已定位塔位'}
        check_status={'pass':'未检出冲突','partial':'资料不完整','review':'终端塔位置待核实','conflict':'存在需复核冲突','pending':'待核查'}
        add('现有图层约束核查', ['；'.join(check_names[k]+'：'+check_status[v['status']] for k,v in measured[f['id']]['rule_checks'].items()) for f in facts], '仅限已提供图层与塔位；不等于正式合规批准')

        if compact:
            extra={'沿线高程起伏（辅助）','风冰区资料','山谷图示范围相交','建筑图斑筛查（辅助）','模型总成本/万元','杆塔数量/个','现有图层约束核查'}
            matrix=[row for row in matrix if row[0] not in extra]
        better_length = min(facts, key=lambda f: f['metrics']['length_m'])
        other = next(f for f in facts if f['id'] != better_length['id'])
        delta = other['metrics']['length_m']-better_length['metrics']['length_m']
        observations = [f"路径长度方面，{better_length['name']}较{other['name']}短约{delta/1000:.3f}km，在长度指标上更优。" if delta>.1 else '两方案长度差异不足0.1m，该指标视为接近。']
        economic = None
        if cost_ok:
            ordered = sorted(facts, key=lambda f: analysis[f['id']]['total_cost'])
            cost_delta = analysis[ordered[1]['id']]['total_cost']-analysis[ordered[0]['id']]['total_cost']
            if cost_delta > .01:
                economic = ordered[0]['id']
                observations.append(f"按当前同口径模型计价，{ordered[0]['name']}比{ordered[1]['name']}低{cost_delta:.2f}万元；该差额包含系统成本及奖励规则，不作为已核定的工程投资节省额。")
            else:
                observations.append('两方案模型总成本接近，不以成本指标区分优劣。')
        else:
            observations.append('两方案成本口径资料不足或不一致，当前不按成本作优劣排序。')
        for f in facts:
            m = measured[f['id']]
            observations.append(f"{f['name']}在现有图层中识别主要交叉跨越{sum(not compact or major_event(e) for e in m['crossings'])}个几何事件，穿越生态保护红线图示范围约{m['ecological_redline_length_m']/1000:.3f}km；数量仅限已提供的数据。")
        conflicts = [f['id'] for f in facts if any(v['status']=='conflict' for v in measured[f['id']]['rule_checks'].values()) or any(c['angle_status']=='conflict' for c in measured[f['id']]['crossings']) or letters[f['id']]['status']=='rejected']
        conflicts=sorted(set(conflicts+[f['id'] for f in facts if any(e['geometry_status']=='conflict' for e in measured[f['id']]['ecology'])]))
        decision = recommendation(ctx, conflicts)
        if decision['recommended_scheme_id']:
            observations.append('根据已确认专业意见：'+decision['text']+'。'+decision.get('conflict_note',''))
        else:
            observations.append('本次仅给出指标层面的优劣分析。综合推荐仍需结合各专题资料完整性及专业审查，当前保留待定。')
        if conflicts:
            observations.append('独立GIS核查发现需复核的约束冲突，不因规划接口返回可行而忽略该差异。')
        if compact:observations=[x for x in observations if not any(w in x for w in ('成本','计价','投资'))]
        narrative, mode = organise(ctx, 'route_comparison', observations)

        radius = float(ctx.options.get('factor_nearby_m', 1000))
        if radius <= 0:
            raise ValueError('factor_nearby_m必须为正')
        grouped = {'生态敏感点': {}, '道路与铁路': {}, '电力线路': {}, '矿区': {}, '河流与水域': {}, '建筑及其他限制地物': {}}
        for f in facts:
            for obj in ctx.catalog.nearby(LineString(f['path']), radius):
                category = obj['category']
                group = '生态敏感点' if is_ecology(obj) else '电力线路' if '输电' in category else '矿区' if '矿' in category else '道路与铁路' if any(k in category for k in ('高速','公路','道路','国道','省道','县道','乡道','铁路')) else '河流与水域' if any(k in category for k in ('河流','水域')) else '建筑及其他限制地物' if any(k in category for k in ('建筑','房屋','基本农田','禁建','禁止')) else None
                if group:
                    label = obj['label'] if obj['name'] else category+'（缺专名）'
                    grouped[group].setdefault(label,set()).add(obj['uid'])
        factors = [{'type': k, 'labels': list(v), 'source_uids': sorted({uid for ids in v.values() for uid in ids})} for k,v in grouped.items()]
        blocks = [heading('3.3 路径方案比选'), prose(ctx.config['project_title']),
            prose(f"本次比较同一起终点的南、北两个路径方案。影响因素从两条候选路线周边{radius:g}m的现有GIS地物筛选，未代替现场踏勘和完整航空直线走廊收资。")]
        if any(ctx.responses[f['id']].get('dem_loaded') is False for f in facts):
            blocks.append(prose('归档规划响应包含DEM未加载的记录；本报告另行读取DEM采样高程，不能据此声称原规划已经执行全部地形相关校核。'))
        coverage=inventory(ctx.catalog,facts,radius)
        for item in ([] if compact else coverage):
            blocks.append(prose(item['type']+'：当前数据包含'+str(item['dataset_count'])+'个要素。'+
                '；'.join(f['name']+'：'+scope_text(item,f['id']) for f in facts)+'。'))
        blocks.append(prose('本次为通过不同必经控制点生成的两条测试路线，不是已审定的正式南北大方案。图层距离和范围均对应这组测试路线。'))
        if ctx.catalog.provenance.get('supplemental_layers'):
            blocks.append(prose('报告同时读取补充道路及完整原始生态GDB。生态范围采用未裁剪原图层，避免遗漏规划裁剪框以外的邻近对象；补充道路等级与通行条件待核。上述补充仅用于报告核查，未改变归档规划的规则、成本或可行性结果。'))
        from road_description.io import write_json
        write_json(out/'图层覆盖与距离.json',coverage)
        if compact:
            names=list(dict.fromkeys(e['label'] for f in facts for e in measured[f['id']]['ecology']))
            blocks=[heading('3.3 路径方案比选'),
                prose(f"本线路起于{ctx.config['start_name']}，止于{ctx.config['end_name']}，比较同一起终点的南、北两个路径方案。"),
                prose('沿线主要影响因素包括高速公路、铁路、输电线路及河流'+('，生态敏感范围包括'+'、'.join(names) if names else '')+'，具体位置见下图。'),
                prose('本次采用真实规划测试路线；正式站址、推荐方案及专题意见尚待确认。')]
        # Reuse the same drawing and description tools, without relying on the
        # description agent having previously rendered a Word document.
        figures = generate_figures(ctx.catalog, ctx.facts, out/'figures')
        materials=approved_materials(ctx.config,ctx.root,ctx.facts,out,'comparison')
        figures.extend(materials)
        for fact in facts:
            fact['figure_ids'].extend(m['id'] for m in materials if m['scheme_id']==fact['id'])
        by_id = {f['id']: f for f in figures}
        blocks.append({'type':'figure', 'path': figures[0]['path'], 'caption':'图3.3-1 南、北方案路径示意图'})
        descriptions = {}
        description_config = dict(ctx.config, llm=ctx.options.get('route_comparison', {}).get('llm', ctx.config.get('llm', {})))
        drafts=parallel_map(lambda f:compose(f,description_config),facts,description_config.get('llm',{}).get('max_concurrency',15))
        for i, (f,value) in enumerate(zip(facts,drafts)):
            descriptions[f['id']] = value
            blocks.append(heading(f"3.3.{i+1} {f['name']}路径"))
            blocks.extend(prose(p['text'], p['fact_ids']) for p in value['paragraphs'])
            blocks.append({'type':'figure_grid', 'images':[by_id[x] for x in f['figure_ids']],
                           'caption':f"图3.3-{i+2} {f['name']}沿线情况（图源见各图及素材清单）"})
        blocks += [heading('3.3.3 综合技术经济比较'),
                   table('表3.3.3-1 路径方案综合比较表', columns[:3] if compact else columns, [r[:3] for r in matrix] if compact else matrix, [4,6,6] if compact else [3,3.7,3.7,5.6]), *narrative,
                   prose('比较依据：各方案response.json、原始地物与规则哈希、DEM及人工确认资料的引用详见本Agent的result.json。')]
        document = render_document(ctx, out/'路径方案比选.docx', blocks, '路径方案比选', 17)
        with (out/'综合比较表.csv').open('w', encoding='utf-8-sig', newline='') as stream:
            writer = csv.writer(stream); writer.writerow(columns); writer.writerows(matrix)
        gaps = []
        for f in facts:
            for key,label in [('terrain','正式地形分类及比例'),('traffic','施工交通调查'),('military','军事设施专项核查'),('mining','矿权专题资料')]:
                value=specials[f['id']][key]
                if value['status']!='confirmed_input' or (key=='terrain' and not value.get('complete')):
                    gaps.append(f['name']+'：'+label)
        if not decision['recommended_scheme_id']:gaps.append('综合推荐的专业审查意见')
        if any(v['status']!='confirmed_input' for v in demolition.values()):
            gaps.append('实际拆迁调查')
        if any(v['status']!='recorded_closed' for v in letters.values()):
            gaps.append('完整协议清单与部门意见')
        (out/'待补资料.txt').write_text('\n'.join(gaps)+'\n', encoding='utf-8')
        return {'status':'draft_pending_evidence', 'documents':[document], 'factors':factors,'coverage':coverage,
                'matrix':{'columns':columns,'rows':matrix}, 'measurements':measured, 'agreements':letters,
                'demolition':demolition, 'model':mode, 'descriptions':descriptions,
                'specialists':specials, 'recommendation':{**decision,
                    'preferred_by_length':better_length['id'] if delta>.1 else None,
                    'preferred_by_model_cost':economic, 'cost_comparable':cost_ok, 'conflict_scheme_ids':conflicts},
                'missing':gaps, 'blocks':blocks, 'figures':figures}
