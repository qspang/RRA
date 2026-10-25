"""Generate two distinct real routes when the planner returns one winner per call."""
from copy import deepcopy
from itertools import combinations
import math
from pathlib import Path

import numpy as np
from shapely.geometry import LineString

from .facts import canonical_path, pair_schemes
from .io import read_json, write_json, archive_map, file_hash, public_data, digest, config_root
from .planner import PlannerClient, select_scheme


def corridor_points(start, end, fractions=(.12, .2), cell=100):
    """Alternate both sides of the same endpoint chord; no hand-coded demo points."""
    dx,dy=end[0]-start[0],end[1]-start[1]
    length=math.hypot(dx,dy)
    if length < cell*4:
        raise ValueError('起终点过近，不足以搜索有实质差异的双走廊')
    nx,ny=-dy/length,dx/length
    if ny < 0 or (abs(ny)<1e-9 and nx<0):nx,ny=-nx,-ny
    seen=set()
    for fraction in fractions:
        if not 0 < fraction <= .5:
            raise ValueError('走廊偏移比例必须在0到0.5之间')
        for side in (1,-1):
            # Try middle first, then two nearby stations if a control point is blocked.
            for along in (.5,.4,.6):
                x=start[0]+along*dx+side*length*fraction*nx
                y=start[1]+along*dy+side*length*fraction*ny
                point=(round(x/cell)*cell,round(y/cell)*cell)
                if point not in seen:
                    seen.add(point)
                    yield {'point':list(point),'side':'upper_side' if side==1 else 'lower_side',
                           'offset_fraction':fraction,'along_fraction':along}


def choose_pair(candidates, minimum=150):
    eligible=[]
    for a,b in combinations(candidates,2):
        la,lb=a['line'],b['line']
        if la.hausdorff_distance(lb) < minimum:
            continue
        # A single distant spike is insufficient: require a substantial distinct stretch.
        distances=[la.interpolate(t,normalized=True).distance(lb) for t in np.linspace(.15,.85,101)]
        if np.mean(np.asarray(distances)>minimum/2)<.2:
            continue
        cost=a['scheme']['analysis'].get('total_cost',float('inf'))+b['scheme']['analysis'].get('total_cost',float('inf'))
        eligible.append((cost,a,b))
    if not eligible:return None
    _,a,b=min(eligible,key=lambda x:x[0])
    return a,b


def generate_two_routes(config_path, force=False):
    config_path=Path(config_path).resolve();root=config_root(config_path)
    config=read_json(config_path);settings=config.get('route_generation',{})
    out=(root/config['output_dir']).resolve();out.mkdir(parents=True,exist_ok=True)
    resolved=config_path.with_name(config_path.stem+'.resolved.json')
    fingerprint=digest({k:config.get(k) for k in ('start','end','request','dataset','route_generation')})
    prior_path=out/'route_generation.json'
    if not force and prior_path.exists() and resolved.exists():
        prior=read_json(prior_path)
        if prior.get('status')=='completed' and prior.get('input_sha256')==fingerprint:
            for item in prior['selected']:
                response_path=out/item['id']/'response.json'
                if file_hash(response_path)!=item['response_sha256']:
                    raise ValueError('已选方案归档发生变化，请重新生成')
                select_scheme(read_json(response_path))
            config['schemes']=read_json(resolved)['schemes']
            config['route_generation']['resolved']=True
            write_json(resolved,config)
            print('自动双方案已完成，复用本次真实结果',flush=True)
            return resolved
    client=PlannerClient(config['planner_url'])
    health,map_data=client.initialize()
    write_json(out/'health.json',health);archive_map(out,map_data)
    start,end=config['start'],config['end']
    direct=math.dist(start,end)
    cell=config.get('request',{}).get('fine_cell_size',100)
    for point in (start,end):
        if not client.validate(point,cell).get('valid'):
            raise ValueError('固定起终点未通过规划接口验证；程序不会悄悄移动它们')
    shared=settings.get('shared_control_points',[])
    if not isinstance(shared,list) or any(not isinstance(p,list) or len(p)!=2 or not all(isinstance(v,(int,float)) and math.isfinite(v) for v in p) for p in shared):
        raise ValueError('shared_control_points须为有限坐标二元数组')
    for point in shared:
        if not client.validate(point,cell).get('valid'):raise ValueError('共同场景控制点未通过规划接口验证')
    state={'status':'running','input_sha256':fingerprint,'method':'固定起终点的双侧走廊控制点自动搜索；每次由真实规划器求解并终检',
           'backend_note':'当前后端只返回一个胜出方案，多个候选通过多次独立约束请求取得',
           'attempts':[],'control_point_checks':[],'selected':[],'shared_control_points':shared}
    write_json(prior_path,state)
    candidates=[]
    schedule=list(corridor_points(start,end,settings.get('offset_fractions',[.12,.2]),cell))
    maximum=int(settings.get('max_attempts',5))
    used_bands=set()
    # One successful request per side/fraction before moving to a wider corridor.
    for candidate in schedule:
        band=(candidate['offset_fraction'],candidate['side'])
        if band in used_bands:continue
        validation=client.validate(candidate['point'],cell)
        state['control_point_checks'].append({**candidate,'valid':bool(validation.get('valid'))})
        if not validation.get('valid'):continue
        if len(state['attempts'])>=maximum:break
        index=len(state['attempts'])+1;folder=out/'planning_attempts'/f'{index:02d}'
        request=dict(config.get('request',{}),start_x=start[0],start_y=start[1],end_x=end[0],end_y=end[1],
                     scheme_count=1,must_pass_points=[{'id':f'auto_{index}','x':candidate['point'][0],
                       'y':candidate['point'][1],'tolerance_m':cell,'label':'自动走廊控制点'}])
        request['solver_options']={**request.get('solver_options',{}),'pause_after_coarse_review':False}
        request['must_pass_points'].extend({'id':f'shared_{j+1}','x':p[0],'y':p[1],
            'tolerance_m':cell,'label':'共同场景验收控制点'} for j,p in enumerate(shared))
        attempt={**candidate,'index':index,'folder':str(folder),'status':'running'}
        state['attempts'].append(attempt);write_json(prior_path,state)
        print(f"自动候选 {index}: {candidate['side']} {candidate['point']}",flush=True)
        try:
            if not force and (folder/'response.json').exists() and (folder/'request.json').exists():
                saved=read_json(folder/'request.json')
                if all(saved.get(k)==v for k,v in request.items()):
                    response=read_json(folder/'response.json')
                else:raise ValueError('候选缓存参数不一致，需指定重新规划')
            else:
                response=client.plan(request,folder,max_seconds=float(settings.get('attempt_timeout_s',360)))
            scheme=select_scheme(response);line=canonical_path(scheme,start)
            if line.length>direct*float(settings.get('maximum_length_ratio',1.8)):
                raise ValueError('候选绕行长度超过本次搜索阈值')
            if line.distance(__import__('shapely').geometry.Point(candidate['point']))>cell+1:
                raise ValueError('返回路线未满足走廊控制点')
            if any(line.distance(__import__('shapely').geometry.Point(p))>cell+1 for p in shared):
                raise ValueError('返回路线未满足共同场景控制点')
            attempt.update(status='feasible',length_m=line.length,model_cost=scheme['analysis'].get('total_cost'))
            candidates.append({'line':line,'scheme':scheme,'response':response,'folder':folder,'candidate':candidate,'attempt_index':index})
            used_bands.add(band)
        except Exception as exc:
            attempt.update(status='rejected',error_type=type(exc).__name__,error=str(exc)[:800])
        write_json(prior_path,state)
        pair=choose_pair(candidates,float(settings.get('min_separation_m',150)))
        if pair:
            descriptors=[{'id':str(c['attempt_index']),'path':list(c['line'].coords),'candidate':c} for c in pair]
            comparison=pair_schemes(descriptors,tolerance=float(settings.get('min_separation_m',150)))
            definitions=[]
            for descriptor,sid in zip(descriptors,('upper','lower')):
                selected=descriptor['candidate'];destination=out/sid
                response=deepcopy(selected['response']);response['schemes']=[selected['scheme']]
                response['report_selection']={'source_response':str(selected['folder']/'response.json'),
                    'source_sha256':file_hash(selected['folder']/'response.json'),'selected_scheme_id':selected['scheme'].get('id')}
                write_json(destination/'response.json',public_data(response))
                write_json(destination/'request.json',read_json(selected['folder']/'request.json'))
                definitions.append({'id':sid,'waypoint':selected['candidate']['point']})
                state['selected'].append({'id':sid,'name':descriptor['name'],'attempt_index':selected['attempt_index'],
                    'length_m':selected['line'].length,'response_sha256':file_hash(destination/'response.json')})
            config['schemes']=definitions
            config['route_generation']['resolved']=True
            write_json(resolved,config)
            state.update(status='completed',comparison=comparison,resolved_config=str(resolved))
            write_json(prior_path,state)
            return resolved
    state.update(status='needs_corridor_input',reason='在本次搜索范围和时限内未取得两条有足够差异的最终可行路线；未复制单路线充数')
    write_json(prior_path,state)
    raise RuntimeError(state['reason'])
