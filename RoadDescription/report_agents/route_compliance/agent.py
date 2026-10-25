import csv
from pathlib import Path

from shapely.geometry import LineString

from road_description.figures import draw_map
from ..common.gis import scheme_measurements, overlap_length
from ..common.report import heading, prose, table, organise, render_document
from ..common.supplement import survey, agreements, finite_quantity
from .profiles import crossing_profile
from ..common.specialists import specialist
from road_description.materials import approved_materials
from ..common.coverage import inventory
from road_description.presentation import reference_style,major_event
from .reference_scenes import render_scenes


def crossing_conflict_note(item):
    if item.get('angle_status') != 'conflict':return None
    return (f"需复核的具体冲突：{item['label']}（{item['event_id']}，K{item['start_m']/1000:.3f}）"
            f"的独立GIS交叉角为{item['angle_deg']:.2f}°，低于当前系统规则阈值{item['minimum_angle_deg']:g}°。"
            "该项尚未满足当前规则；需核实源线几何、适用规则与跨越设计，必要时调整路线后重算。"
            "未据规划接口返回可行认定本项通过，也未将系统规则阈值冒充已确认的工程设计或审批结论。")


def confirmed_designs(ctx, facts, crossings):
    result = []
    known = {uid for c in crossings for uid in c['source_uids']}
    for item in ctx.supplied(facts['id']).get('crossing_designs', []):
        ids = item.get('source_uids', [])
        if not ids or not set(ids).issubset(known):
            raise ValueError('跨越设计资料必须关联本路线有效的跨越source_uids')
        matches = [c for c in crossings if set(ids).intersection(c['source_uids'])]
        if item.get('chainage_m') is not None:
            station = finite_quantity(item['chainage_m'])
            matches = [c for c in matches if c['start_m']-1 <= station <= c['end_m']+1]
        if len(matches)!=1:
            raise ValueError('跨越设计须唯一关联事件；同一地物多次跨越时填写chainage_m，容差1m')
        evidence = ctx.evidence(item)
        if evidence['verified']:
            for key in ('span_m', 'tension_length_m', 'design_angle_deg'):
                if key in item:
                    finite_quantity(item[key])
            if item.get('design_angle_deg', 0) > 90:
                raise ValueError('设计交叉锐角须在0～90度之间')
        result.append({'input': item if evidence['verified'] else {'source_uids':ids},
                       'crossing_start_m': matches[0]['start_m'],
                       'status': 'confirmed_input' if evidence['verified'] else 'pending', 'evidence':evidence})
    return result


DESIGN_FIELDS = [('tower_arrangement','跨越方式（塔型排列）',''), ('span_m','跨越档距','m'),
                 ('tension_length_m','耐张段长度','m'), ('design_angle_deg','设计交叉角','°'),
                 ('clearance_note','净空说明',''), ('joint_note','导地线接头要求','')]


def design_missing(design):
    data = design['input'] if design and design['status']=='confirmed_input' else {}
    return [title for key,title,_ in DESIGN_FIELDS if key!='design_angle_deg' and (data.get(key) is None or data.get(key)=='')]


def design_text(design):
    data = design['input'] if design and design['status']=='confirmed_input' else {}
    if not data:return '跨越方式、档距和净空等工程设计资料待补'
    parts = [f'{title}：{data[key]}{unit}' for key,title,unit in DESIGN_FIELDS if data.get(key) is not None and data.get(key)!='']
    missing = design_missing(design)
    if missing:parts.append('、'.join(missing)+'待设计资料确认')
    return '；'.join(parts)


def ecological_measure(record):
    if record['inside_length_m'] > .05:
        if record['rule']['cross_forbidden']:
            return '与当前禁止通行规则存在空间冲突，需核实数据/运行规则并调整路径'
        if record['rule']['tower_forbidden']:
            return '需核实跨越档距、塔位及禁立塔范围；一档跨越可行性待专项设计'
        if record.get('located_tower_count',0):
            return '已有定位塔位落入图示范围，建议优先研究塔位微调避让，核实塔基、便道及牵张场占地；不能避让的部分需结合专题明确措施和办理要求'
        return '现有已定位塔位未落入图示范围，仍需核实逐塔定位是否完整；优先研究减少范围内施工占地，具体措施需专题确认'
    if record['relation'] == '边界接触':
        return '核对边界精度及保护范围，不能按未穿越直接判定已满足全部要求'
    return '现有边界下位于外侧；施工临时占地及保护范围仍待核查'


class RouteComplianceAgent:
    manifest = {'id':'route_compliance', 'version':'0.2.0', 'name':'路径合规性分析Agent',
                'sections':['3.4.8','3.4.9','3.4.10','3.4.11','3.5'], 'depends_on':[],
                'inputs':['最终路径/已定位塔位','GIS原始及约束图层','可选调查、跨越设计、停电和协议资料'],
                'outputs':['逐项核查JSON/CSV','各方案Word/PDF','资料缺口清单'],
                'scope':'按现有工程数据和系统规则进行证据核查，不把规划可行性等同于法定审批完成'}

    def run(self, ctx):
        out = ctx.output/'route_compliance'
        out.mkdir(parents=True, exist_ok=True)
        selected = ctx.options.get('route_compliance', {}).get('scheme_id')
        facts = ctx.facts['schemes']
        if selected:
            facts = [f for f in facts if f['id']==selected]
            if not facts:
                raise ValueError('指定合规核查方案不存在')
        results, documents = {}, []
        for fact in facts:
            result = self.run_scheme(ctx, fact, out/fact['id'])
            results[fact['id']] = result
            documents.append(result['document'])
        return {'status':'draft_pending_evidence', 'documents':documents, 'schemes':results,
                'selection':selected or '未指定推荐方案，分别核查两方案；不自动采用成本最小方案作为正式推荐方案'}

    def run_scheme(self, ctx, fact, out):
        out.mkdir(parents=True, exist_ok=True)
        sid = fact['id']; route = LineString(fact['path'])
        m = scheme_measurements(ctx, fact)
        analysis = ctx.schemes[sid]['analysis']
        supplied = ctx.supplied(sid)
        designs = confirmed_designs(ctx, fact, m['crossings'])
        demolition = survey(ctx, sid, 'demolition')
        forestry = survey(ctx, sid, 'forestry')
        letters = agreements(ctx, sid)
        ecology_opinion = specialist(ctx,sid,'ecology')
        outage = supplied.get('outage', {})
        outage_source = ctx.evidence(outage)
        issues = []
        checks = []
        blocks = [heading(f"{fact['name']}路径合规性分析"), prose(ctx.config['project_title']),
            prose('本稿按参考章节组织跨越与停电、拆迁、林木砍伐、生态影响和协议资料。系统可行性、GIS空间核查、设计调查和部门复函分别记录，未取得资料的项目不填为“无”或“已通过”。')]
        for key, label in [('forbidden_polygons','禁行图层核查'),('no_tower_polygons','禁立塔图层核查')]:
            item = m['rule_checks'][key]
            count = len(item.get('hits', []))
            text = f'{label}：'+ ('发现'+str(count)+'项空间命中，需复核' if count else '已检查对象未检出冲突')
            if not item.get('complete'):
                text += '；现有塔位/图层资料不能覆盖全部检查对象'
            checks.append({'topic':label, **item})
            blocks.append(prose(text+'。'))
            if item.get('terminal_note'):
                blocks.append(prose(item['terminal_note']+'。'+('现有系统默认豁免固定终端塔检查，本次测试起点仍需作为独立站址问题核实。' if item.get('terminal_policy_source') else '')))
            if item['status'] != 'pass':
                issues.append(label+'：'+item['status'])
        blocks.append(prose('当前塔位模式为'+str(analysis.get('tower_placement',{}).get('mode','未知'))+'；统计塔数量不能替代全线逐塔定位、弧垂和净空校核。'))
        if ctx.responses[sid].get('dem_loaded') is False:
            blocks.append(prose('归档规划响应记载未加载高程数据；本报告额外读取的高程数据仅用于分析展示，地形相关规划校核的执行范围需要另行确认。'))
            issues.append('规划响应未加载DEM，地形相关校核范围待确认')
        compact=reference_style(ctx.config)
        technical_blocks=blocks[3:]
        blocks=blocks[:3]
        blocks += [heading('3.4.8 主要交叉跨越及停电方案'), heading('3.4.8.1 主要交叉跨越概况')]
        rows, crossing_records = [], []
        for index, crossing in enumerate(m['crossings'], 1):
            design = next((d for d in designs if d['status']=='confirmed_input' and
                           abs(d['crossing_start_m']-crossing['start_m'])<.01 and
                           set(d['input']['source_uids']).intersection(crossing['source_uids'])), None)
            item = dict(crossing, event_id=f'{sid}_CROSS_{index:03d}', design=design)
            item['presentation_included']=not compact or major_event(item)
            crossing_records.append(item)
            angle = f"{crossing['angle_deg']:.1f}°" if crossing['angle_deg'] is not None else '未计算（面状/资料不足）'
            required = f"系统阈值{crossing['minimum_angle_deg']:g}°" if crossing['minimum_angle_deg'] is not None else '缺明确系统阈值'
            state = {'pass':'几何角满足当前阈值','conflict':'角度需复核','pending':'待专项核查'}[crossing['angle_status']]
            rows.append([str(index),crossing['category'],crossing['label']+('（隧道段图示）' if crossing.get('tunnel_status')=='tunnel' else ''),
                         f"K{crossing['start_m']/1000:.3f}",'1处'])
            checks.append({'topic':item['event_id']+'交叉角','status':crossing['angle_status'],
                           'angle_deg':crossing['angle_deg'],'minimum_angle_deg':crossing['minimum_angle_deg'],
                           'source_uids':crossing['source_uids']})
            if design_missing(design):
                issues.append(item['event_id']+'：待补'+ '、'.join(design_missing(design)))
        if not rows:
            rows = [['—','现有图层未检出主要交叉跨越','—','—','仍需核查数据覆盖']]
        if compact:
            grouped={}
            for item in crossing_records:
                if item['presentation_included']:grouped.setdefault(item['category'],[]).append(item)
            main_rows=[[category,'、'.join(dict.fromkeys(e['label']+('（隧道段投影）' if e.get('tunnel_status')=='tunnel' else '') for e in values)),str(len(values))] for category,values in grouped.items()]
            blocks.append(prose('本方案主要交叉跨越如下。数量为几何事件，双幅道路等需结合工程设计归并。'))
            blocks.append(table('表3.4.8-1 主要交叉跨越一览表',['类别','被跨越物名称','图示事件数'],main_rows or [['—','现有图层未检出','—']],[3,11,2]))
        else:
            blocks.append(prose(f"本方案根据现有地物资料识别{len(crossing_records)}个几何交叉事件，具体对象与位置如下。补充道路单列注明等级待核；双幅道路或匝道可能产生多个交点，工程跨越处数应结合档距和施工设计归并。图示交点不能代替最终跨越档距、塔位与施工设计。"))
            blocks.append(table('表3.4.8-1 主要交叉跨越一览表',
                                ['序号','类别','被跨越物','路径里程','事件数'], rows, [1,3.5,6,3,2]))
        for item in crossing_records:
            note=crossing_conflict_note(item)
            if note:blocks.append(prose(note,item['source_uids']))
        if m['contacts']:
            blocks.append(prose(f"另检出{len(m['contacts'])}项端点接触/沿线重叠，未混入跨越次数，详见result.json；需人工确认实际工程关系。"))
            issues.append('线状地物接触/重叠关系待复核')
        materials=approved_materials(ctx.config,ctx.root,ctx.facts,out,'compliance',crossing_records,scheme_id=sid)
        figures = [];minor_figures=[]
        configured_limit = ctx.options.get('route_compliance', {}).get('max_crossing_figures')
        max_figures = len(crossing_records) if configured_limit is None else int(configured_limit)
        if max_figures < 0:
            raise ValueError('max_crossing_figures不能为负')
        if compact:
            scene_blocks,figures=render_scenes(ctx,fact,crossing_records,out)
            blocks.extend(scene_blocks)
            for material in materials:
                figures.append(material)
                blocks.append({'type':'figure','path':material['path'],'caption':material['title']+'（已确认资料）'})
        else:
            for index, item in enumerate(crossing_records, 1):
                minor=any(k in item['category'] for k in ('乡道','道路（补充')) and not item['design']
                if not minor:
                    blocks.append(prose(f"（{index}）{item['label']}：交点位于路径K{item['start_m']/1000:.3f}附近。"+design_text(item['design'])+'。', item['source_uids']))
                    if item.get('tunnel_status')=='tunnel':
                        blocks.append(prose('源地物的隧道标记为真，本处为路线与隧道段平面投影相交，不直接等同露天道路的架空跨越；需核对洞口、埋深及塔基与施工位置。',item['source_uids']))
                if index <= max_figures:
                    x,y=item['xy']; radius=800
                    figure=draw_map(ctx.catalog,[fact],out/'figures'/f'crossing_{index:03d}.png',
                                    item['label']+'跨越位置',bounds=[x-radius,y-radius,x+radius,y+radius],focus=item,
                                    overview=True,show_local_roads=True)
                    figure.update(event_id=item['event_id'], source_uids=item['source_uids'])
                    figures.append(figure)
                    if minor:
                        minor_figures.append(dict(figure,title=f"{item['label']}（K{item['start_m']/1000:.3f}）"))
                    else:blocks.append({'type':'figure','path':figure['path'],
                                   'caption':f"图3.4.8-{index}a {item['label']}跨越位置（"+('天地图影像叠加路线' if figure['kind']=='satellite_map' else 'GIS平面示意')+'）'})
                    profile=crossing_profile(m['elevation'], item, out/'figures'/f'profile_{index:03d}.png') if ctx.options.get('route_compliance',{}).get('include_dem_profiles',False) else None
                    if profile:
                        figures.append(profile)
                        blocks.append({'type':'figure','path':profile['path'],
                                       'caption':f"图3.4.8-{index}b {item['label']}附近地形剖面（DEM采样，非设计断面）"})
                for material in materials:
                    if material['event_id']==item['event_id']:
                        figures.append(material)
                        blocks.append({'type':'figure','path':material['path'],
                                       'caption':f"图3.4.8-{index}资料 {material['title']}（已确认提供资料）"})
            if minor_figures:
                blocks += [prose('一般道路及补充小路交叉位置集中列示如下，里程与上表对应。道路等级、通行与施工条件仍需核实。'),
                           {'type':'figure_grid','images':minor_figures,'caption':'图3.4.8-道路索引 一般道路及补充小路交叉位置（影像/矢量图源见各图）'}]
            if len(crossing_records)>max_figures:
                blocks.append(prose(f'共{len(crossing_records)}个跨越事件，正文绘制前{max_figures}处；其余事件均保留在跨越表及JSON中。'))
                issues.append('3.4.8.1：配置限制导致部分跨越图未绘制，完整交付应取消max_crossing_figures限制')
        issues.append('3.4.8.1：跨越工程断面待补（杆塔、导地线弧垂、被跨物标高及净空）；DEM地形剖面不能替代')
        blocks.append(heading('3.4.8.2 停电方案'))
        if outage_source['verified'] and outage.get('text'):
            blocks.append(prose(outage['text']))
            blocks.append(prose('依据已人工确认资料：'+Path(outage_source['source_file']).name+'。'))
        else:
            electrical={}
            for item in crossing_records:
                if '输电' in item['category']:
                    electrical.setdefault(item['label'],[]).append(f"K{item['start_m']/1000:.3f}")
            blocks.append(prose('（1）停电范围及施工时序'))
            if electrical:
                blocks.append(prose('根据本方案交叉跨越识别结果，以下电力线路应纳入施工停电或不停电跨越方案的协调核查。是否需要停电及具体时长尚待设计、运行和调度部门确定。'))
                blocks.append(table('表3.4.8-2 施工停电协调对象及待定安排',
                    ['实施项目','拟协调线路及位置','停电时间','施工时序/备注'],
                    [[ctx.config['project_title'],name+'；'+ '、'.join(stations),'待调度确认','跨越施工；停电必要性、方式及同停组合待确认'] for name,stations in electrical.items()],
                    [3.5,5.5,2,5]))
            else:
                blocks.append(prose('现有地物资料未识别电力线路跨越；进出线接入、迁改和未覆盖线路仍需结合施工范围核查，不能据此认定无需停电。'))
            blocks += [prose('（2）停电方案及影响分析'),
                prose('待取得一次接线图、线路与变电站拓扑、运行方式、负荷和转供能力后，逐组分析停电范围、替代供电路径、失电风险及保障措施。当前地图不包含完整电网运行信息，不能推定“无失电风险”或具体风险等级。'),
                prose('（3）实施顺序与保障措施'),
                prose('迁改先后顺序、保供线路、同停组合、停电窗口及复电条件由运行调度与施工方案共同确认。参考资料中的30天/10天安排和荷嘉甲乙线迁改顺序属于参考工程，未套用到本测试路线。')]
            issues.append('3.4.8.2：停电方案与调度依据待补')

        blocks.append(heading('3.4.9 沿线拆迁情况'))
        screen=m['building_screen']
        blocks.append(prose(f"按总宽{screen['screen_width_m']:g}m的辅助筛查带，现有建筑图层检出相交要素{screen['feature_count']}个，图斑相交并集面积约{screen['polygon_overlap_m2']:.1f}m²。该数值只是几何筛查结果，不作为确认拆迁面积，也不能证明未覆盖区域不存在建筑。"))
        if demolition['status']=='confirmed_input':
            demolition_rows=[[str(i),r['kind'],f"{r['quantity']:g}",r['unit']] for i,r in enumerate(demolition['records'],1)]
            if not demolition_rows:
                demolition_rows=[['—','人工确认记录为空','—','范围见调查来源']]
            blocks.append(prose('下表按已人工确认的调查资料填写，来源：'+Path(demolition['evidence']['source_file']).name+'。'))
        else:
            demolition_rows=[[str(i),kind,'待调查',unit] for i,(kind,unit) in enumerate([('砖瓦屋/楼房','m²'),('棚','m²'),('坟墓','个'),('通信塔','座')],1)]
            issues.append('3.4.9：分类拆迁调查、建筑层数/用途及确认范围待补')
        blocks.append(table('表3.4.9-1 沿线拆迁调查表',['序号','拆迁物名称','已确认数量','单位'],demolition_rows,[1.5,6,5,3.5]))

        blocks.append(heading('3.4.10 林木砍伐情况'))
        forests=[f for f in ctx.catalog.features if any(k in f['category'] for k in ('林地','林木','树种'))]
        forest_length=overlap_length(route,forests) if forests else None
        if forest_length is None:
            blocks.append(prose('现有分类图层未提供可用于统计树种、树高和林区长度的林业专项数据；自然公园或生态红线范围不直接作为林木分布或砍伐面积。'))
        else:
            blocks.append(prose(f'按现有林业图层测得路线相交长度约{forest_length/1000:.3f}km；该值不等于需要砍伐的通道长度。'))
        if forestry['status']=='confirmed_input':
            forestry_rows=[[str(i),r['species'],f"{r['height_m']:g}",f"{r['felling_area_m2']:g}"] for i,r in enumerate(forestry['records'],1)] or [['—','调查记录为空','—','—']]
            if forestry.get('forest_length_m') is not None:
                blocks.append(prose(f"按已确认调查资料，所经林区长度约{forestry['forest_length_m']/1000:.3f}km。"))
            blocks.append(prose('林木统计来源：'+Path(forestry['evidence']['source_file']).name+'。'))
        else:
            forestry_rows=[['—','待调查','待调查','待专项设计确认']]
            issues.append('3.4.10：林业图层、树种树高、跨越净空及砍伐设计量待补')
        blocks.append(table('表3.4.10-1 林木砍伐调查表',['序号','林木种类','自然生长高度/m','确认砍伐面积/m²'],forestry_rows,[1.5,4.5,5,5]))
        blocks.append(prose('高跨或开辟通道的选择、是否需要砍伐及通道宽度，需结合林木调查、导线弧垂净空和经确认的设计依据。未将参考PDF中的树高、面积或固定倍数套用到本路线。'))

        blocks.append(heading('3.4.11 对生态敏感点的影响及处理措施'))
        ecology_rows=[];ecology_context=[]
        for index,item in enumerate(m['ecology'],1):
            position=f"{item['relation']}；最近距离{item['distance_m']:.1f}m"
            if item.get('intervals'):
                position+='；'+ '、'.join(f"K{p['start_m']/1000:.3f}—K{p['end_m']/1000:.3f}" for p in item['intervals'])
            effect=f"图示范围内长度{item['inside_length_m']:.1f}m；已有定位塔{item['located_tower_count']}处"+('；逐塔定位尚未完整，施工影响待核' if not item['tower_coverage_complete'] else '；施工影响待核')
            checks.append({'topic':'生态对象空间核查：'+item['label'],'status':item['geometry_status'],'source_uid':item['source_uid'],
                           'inside_length_m':item['inside_length_m'],'located_tower_ids':item['located_tower_ids']})
            if item['geometry_status']=='conflict':issues.append('生态对象与现有同类禁行/禁塔规则存在冲突：'+item['label'])
            confirmed=[r['measure'] for r in ecology_opinion['records'] if item['source_uid'] in r['source_uids']]
            if not confirmed:issues.append('3.4.11：'+item['label']+'缺逐对象确认处理措施')
            ecology_rows.append([str(index),item['label'],position,effect,('确认资料：'+'；'.join(confirmed)+'；' if confirmed else '')+ecological_measure(item)])
        if not ecology_rows:
            ecological=[f for f in ctx.catalog.features if any(k in f['category'] for k in ('水源','自然保护','生态','公园','湿地'))]
            categories=sorted({f['category'] for f in ecological})
            for category in categories:
                nearest=min((f for f in ecological if f['category']==category),key=lambda f:route.distance(f['geometry']))
                distance=route.distance(nearest['geometry'])
                ecology_context.append({'source_uid':nearest['uid'],'label':nearest['label'],'category':category,
                                        'distance_m':distance,'relation':'范围外侧，最近对象，仅作区域参照'})
                ecology_rows.append([str(len(ecology_rows)+1),nearest['label'],f'路线外侧；最近约{distance/1000:.2f}km',
                    '未穿越；本对象位于周边筛查范围外，列作区域参照','结合塔基、施工便道和临时占地进一步核查；正式保护要求待专题确认'])
            if not ecology_rows:ecology_rows=[['—','未提供生态专题图层','—','无法完成空间核查','补齐保护范围及专题资料']]
            blocks.append(prose(f"现有生态图层已读取，路线及周边{m['ecology_nearby_m']:g}m内未检出敏感区。下表补列各类最近对象，说明已核查的数据及距离，不表示路线穿越这些区域。"))
        blocks.append(table('表3.4.11-1 线路对生态敏感点的影响及处理措施',
                            ['序号','生态敏感区','相对位置及距离','线路影响','处理措施/待核事项'],ecology_rows,[1,3.2,3.2,4,4.6]))
        for index,item in enumerate((x for x in m['ecology'] if not compact and x['inside_length_m']>.05),1):
            x,y=item['xy'];radius=max(900,min(2500,item['inside_length_m']))
            figure=draw_map(ctx.catalog,[fact],out/'figures'/f'ecology_{index:03d}.png',
                            item['label']+'相交位置',bounds=[x-radius,y-radius,x+radius,y+radius],focus=item,overview=True)
            figure.update(source_uids=[item['source_uid']],ecology_source_uid=item['source_uid'])
            figures.append(figure)
            blocks.append({'type':'figure','path':figure['path'],'caption':f"图3.4.11-{index} {item['label']}与本方案的空间关系（非施工占地范围）"})
        if not compact:blocks.append(prose(f"另按现有基本农田图层测得线路相交长度约{m['farmland_length_m']:.1f}m。线路投影经过与塔基/临时用地占用是不同口径，需要塔位、施工占地及对应部门意见进一步核对。"))
        if ecology_opinion['status']=='confirmed_input':
            blocks.append(prose('已确认生态专题意见：'+ecology_opinion['text']))
        else:
            issues.append('3.4.11：施工临时占地、保护范围完整性及正式措施/专题意见待核')
        blocks += [heading('3.5 协议情况'),prose('仅汇总当前方案已人工确认且有来源文件的意见。参考PDF中的部门名单和“同意/无意见”结论未作为本项目已取得的协议。')]
        agreement_rows=[[r['region'],str(i),r['department'],r['status_label'],r['conditions'] or r['reference'] or '—'] for i,r in enumerate(letters['records'],1)]
        if not agreement_rows:
            agreement_rows=[['待确认','—','应办协议部门清单待补','未提供复函','尚无法统计办理完成率']]
        blocks.append(table('表3.5-1 路径协议情况汇总表',['行政区域','编号','部门','协议办理情况','条件/文号'],agreement_rows,[2.3,1,3.8,3.7,5.2]))
        if letters['status']!='recorded_closed':
            issues.append('3.5：协议清单/复函尚未闭合（附条件意见不自动转为全部通过）')

        status='conflict_requires_review' if any(c['status']=='conflict' for c in checks) or letters['status']=='rejected' else 'pending_evidence'
        summary=[f"{fact['name']}的当前核查状态为“{'存在需复核冲突' if status=='conflict_requires_review' else '资料待补充'}”。规划接口通过的是当前算法模型校核，不能替代本章涉及的逐塔设计、调查与协议证据。",
                 f"已识别{sum(e['presentation_included'] for e in crossing_records)}个主要跨越事件；资料和核查待办共{len(issues)}项，详见随附待补资料清单和机器可读结果。"]
        paragraphs,model=organise(ctx,'route_compliance',summary)
        if compact:
            blocks += [heading('本方案核查结论'),*paragraphs]
        else:
            blocks += [heading('本方案核查结论与待办'),*paragraphs,
                       heading('附：技术核查记录（供复核）'),*technical_blocks,
                       prose('交叉角及算法规则阈值保留在跨越核查.csv和result.json中，用于内部复核，不作为正文工程设计参数或审批结论。'),
                       table('资料与复核待办',['序号','事项'],[[str(i),text] for i,text in enumerate(issues,1)],[1.5,14.5])]
        document=render_document(ctx,out/f"{fact['name']}_路径合规性分析.docx",blocks,f"{fact['name']}路径合规性分析",30)
        with (out/'跨越核查.csv').open('w',encoding='utf-8-sig',newline='') as stream:
            writer=csv.writer(stream);writer.writerow(['事件ID','地物','里程m','角度deg','系统阈值deg','角度状态','原始ID'])
            for item in crossing_records:
                writer.writerow([item['event_id'],item['label'],item['start_m'],item['angle_deg'],item['minimum_angle_deg'],item['angle_status'],';'.join(item['source_uids'])])
        (out/'待补资料.txt').write_text('\n'.join(issues)+'\n',encoding='utf-8')
        return {'status':status,'scheme_id':sid,'name':fact['name'],'document':document,'checks':checks,
                'crossings':crossing_records,'contacts':m['contacts'],'demolition':demolition,'forestry':forestry,
                'outage':{'status':'confirmed_input' if outage_source['verified'] and outage.get('text') else 'pending','evidence':outage_source},
                'ecology':m['ecology'],'ecology_context':ecology_context,'ecology_opinion':ecology_opinion,'building_screen':screen,'farmland_length_m':m['farmland_length_m'],
                'agreements':letters,'missing':issues,'model':model,'blocks':blocks,'figures':figures}
