"""Measurements retain dataset scope; absence of a feature is not proof of absence."""
import math
from pathlib import Path

import geopandas as gpd
import numpy as np
from pyproj import Transformer
from shapely import affinity, make_valid
from shapely.geometry import LineString, Point
from shapely.ops import unary_union, nearest_points

from road_description.facts import intersection_events, line_parts, clean, tunnel_mark
from road_description.io import file_hash


def is_ecology(feature):
    return any(s in feature['category'] for s in ('水源', '自然保护', '生态', '公园', '湿地', '风景'))

def is_crossing(feature):
    return any(s in feature['category'] for s in ('公路', '道路', '国道', '省道', '县道', '乡道', '铁路', '输电', '河流'))


def bearing_xy(line, station, window=5):
    a = line.interpolate(max(0, station-window))
    b = line.interpolate(min(line.length, station+window))
    if a.distance(b) < .001:
        return None
    return math.degrees(math.atan2(b.y-a.y, b.x-a.x)) % 180


def crossing_angle(route, reference, station):
    """Planar axial angle, not electrical clearance or a conductor profile."""
    if reference.geom_type not in ('LineString', 'MultiLineString'):
        return None
    point = route.interpolate(station)
    part = min(line_parts(reference), key=lambda g: point.distance(g), default=None)
    if part is None or point.distance(part) > 1:
        return None
    a, b = bearing_xy(route, station), bearing_xy(part, part.project(point))
    if a is None or b is None:
        return None
    delta = abs(a-b)
    return min(delta, 180-delta)


def crosses_at(route, reference, point):
    """Four local rays must alternate; a V-shaped tangency is only contact."""
    def rays(geometry):
        angles = []
        for part in line_parts(geometry):
            coords = list(part.coords)
            for a,b in zip(coords,coords[1:]):
                if LineString([a,b]).distance(point) > .001:
                    continue
                for x,y in (a,b):
                    if math.hypot(x-point.x,y-point.y) <= .001:
                        continue
                    angle = math.atan2(y-point.y,x-point.x) % (2*math.pi)
                    if not any(abs((angle-old+math.pi)%(2*math.pi)-math.pi)<1e-6 for old in angles):
                        angles.append(angle)
        return angles
    a,b = rays(route),rays(reference)
    if len(a)!=2 or len(b)!=2:
        return False
    ordered = sorted([(x,0) for x in a]+[(x,1) for x in b])
    if any(abs((ordered[(i+1)%4][0]-ordered[i][0])%(2*math.pi))<1e-6 for i in range(4)):
        return False
    return all(ordered[i][1]!=ordered[(i+1)%4][1] for i in range(4))


def crossings(route, catalog, include_contacts=False):
    records = []
    # Merge original fragments sharing a real official name, but never join two
    # unnamed objects merely because their category matches. No 30m gap filling.
    grouped = {}
    for f in catalog.nearby(route):
        if is_crossing(f):
            key = (f['category'], f['name'] or f['uid'])
            grouped.setdefault(key, []).append(f)
    for features in grouped.values():
        geometry = unary_union([f['geometry'] for f in features])
        f = features[0]
        for lo, hi, relation in intersection_events(route, geometry):
            if relation == 'cross':
                if not crosses_at(route, geometry, route.interpolate(lo)):
                    relation = 'contact'
            if relation in ('overlap', 'contact') and not include_contacts:
                continue
            point = route.interpolate((lo+hi)/2)
            local = [x for x in features if x['geometry'].distance(point) < 1] or features
            thresholds = [catalog.rule(x).get('min_cross_angle') for x in local]
            thresholds = [float(x) for x in thresholds if x is not None and float(x) > 0]
            threshold = max(thresholds) if thresholds else None
            angle = crossing_angle(route, geometry, (lo+hi)/2)
            state = ('pending' if relation in ('overlap','contact') or angle is None or threshold is None else
                     'pass' if angle+1e-5 >= threshold else 'conflict')
            marks={tunnel_mark(x.get('tunnel')) for x in local}
            tunnel_status='tunnel' if marks=={True} else 'surface' if marks=={False} else 'unconfirmed'
            records.append({'category': f['category'], 'label': f['label'], 'name_source': f['name_source'],
                'source_uids': sorted({x['uid'] for x in features}), 'start_m': lo, 'end_m': hi,
                'intersection_length_m': hi-lo, 'relation': relation, 'angle_deg': angle,
                'minimum_angle_deg': threshold, 'angle_status': state,
                'angle_method': '原始线状地物与路径交点两侧各5m切向的平面锐角；面状水域不推算交叉角',
                'xy': list(point.coords[0]), 'tunnel': [x['tunnel'] for x in local if x['tunnel']], 'tunnel_status':tunnel_status})
    records.sort(key=lambda x: x['start_m'])
    return records


def layer_checks(ctx, route, analysis):
    result = {}
    for name in ('forbidden_polygons', 'no_tower_polygons'):
        key = 'layer_'+name
        path = ctx.catalog.root/'m2'/f'{name}.gpkg'
        effective=getattr(ctx.catalog,'constraint_frames',{}).get(name)
        if effective is None and not path.exists():
            result[name] = {'status': 'pending', 'reason': '缺少'+str(path)}
            continue
        if effective is not None:
            ctx.cache[key]=effective
        if key not in ctx.cache:
            frame = gpd.read_file(path).to_crs(ctx.catalog.crs)
            frame.geometry = frame.geometry.map(lambda g: affinity.translate(make_valid(g),
                            xoff=ctx.catalog.offset[0], yoff=ctx.catalog.offset[1]))
            ctx.cache[key] = frame
        frame = ctx.cache[key]
        hits = []
        if name == 'forbidden_polygons':
            for idx in frame.sindex.query(route, predicate='intersects'):
                row = frame.iloc[int(idx)]
                parts = intersection_events(route, row.geometry)
                length = sum(hi-lo for lo,hi,kind in parts if kind=='traverse')
                if length > .05:
                    hits.append({'feature_row': int(idx), 'category': clean(row.get('level2')),
                                 'inside_length_m': length})
                elif route.intersects(row.geometry):
                    hits.append({'feature_row': int(idx), 'category': clean(row.get('level2')),
                                 'inside_length_m': 0, 'boundary_contact': True})
            complete = True
        else:
            towers = analysis.get('towers', [])
            for tower in towers:
                point = Point(tower['x'], tower['y'])
                for idx in frame.sindex.query(point, predicate='intersects'):
                    row = frame.iloc[int(idx)]
                    hits.append({'tower_id': tower.get('id'), 'tower_type': tower.get('type'),
                                 'feature_row': int(idx), 'category': clean(row.get('level2'))})
            complete = bool(analysis.get('tower_placement', {}).get('straight_placement_checked'))
        terminal_only = name == 'no_tower_polygons' and hits and all(h['tower_type']=='terminal' for h in hits)
        result[name] = {'status': 'review' if terminal_only else 'conflict' if hits else ('pass' if complete else 'partial'),
                        'hits': hits, 'complete': complete, 'source': ctx.catalog.provenance['constraint_source'] if effective is not None else str(path),
                        'sha256': ctx.catalog.provenance['adjustments_sha256'] if effective is not None else file_hash(path), 'effective_snapshot':effective is not None, 'scope': '预处理约束图层的独立空间核查，冲突需与当前运行规则复核'}
        if terminal_only:
            result[name]['terminal_note'] = '空间命中仅涉及固定终端塔；需核对站址/接入点业务前提及端点豁免，不直接判为中间塔硬违规'
            backend = ctx.options.get('planner_source')
            if backend:
                source = ctx.root/backend/'algorithm/tower_placer.py'
                if source.exists():
                    import ast
                    tree = ast.parse(source.read_text(encoding='utf-8'))
                    for node in ast.walk(tree):
                        if isinstance(node, ast.FunctionDef) and node.name=='validate_tower_positions':
                            defaults = dict(zip([a.arg for a in node.args.args][-len(node.args.defaults):], node.args.defaults))
                            default = defaults.get('exempt_terminal')
                            if isinstance(default, ast.Constant) and default.value is True:
                                result[name]['terminal_policy_source'] = {'path':str(source),'sha256':file_hash(source),
                                    'function':'validate_tower_positions','default_exempt_terminal':True,
                                    'note':'当前本地实现的默认口径；不能代替该次请求的正式站址确认'}
    return result


def ecology_relations(route, catalog, radius, towers=None, tower_complete=False):
    records = []
    for f in catalog.nearby(route, radius):
        if not is_ecology(f):
            continue
        events = intersection_events(route, f['geometry'])
        length = sum(hi-lo for lo,hi,kind in events if kind=='traverse')
        distance = route.distance(f['geometry'])
        relation = '穿越图示范围' if length > .05 else '边界接触' if distance < .01 else '范围外侧'
        rule = catalog.rule(f)
        intervals=[{'start_m':lo,'end_m':hi} for lo,hi,kind in events if kind=='traverse']
        station=(intervals[0]['start_m']+intervals[0]['end_m'])/2 if intervals else route.project(nearest_points(route,f['geometry'])[0])
        located=[t.get('id',str(i)) for i,t in enumerate(towers or []) if f['geometry'].covers(Point(t['x'],t['y']))]
        conflict=(length>.05 and rule['cross_forbidden']) or (bool(located) and rule['tower_forbidden'])
        records.append({'source_uid': f['uid'], 'label': f['label'], 'category': f['category'],
                        'relation': relation, 'distance_m': distance, 'inside_length_m': length,
                        'rule': rule, 'geometry_status': 'conflict' if conflict else 'review',
                        'located_tower_ids':located,'located_tower_count':len(located),'tower_coverage_complete':tower_complete,
                        'intervals':intervals,'station_m':station,'xy':list(route.interpolate(station).coords[0])})
    return sorted(records, key=lambda r: r['station_m'])


def overlap_length(route, features):
    cuts = [route.intersection(f['geometry']) for f in features]
    return unary_union(cuts).length if cuts else 0.


def building_screen(route, catalog, width):
    corridor = route.buffer(width/2, cap_style=2)
    items = [f for f in catalog.nearby(corridor) if '建筑' in f['category'] or '房屋' in f['category']]
    polys = [f['geometry'].intersection(corridor) for f in items
             if f['geometry'].geom_type in ('Polygon', 'MultiPolygon')]
    return {'screen_width_m': width, 'feature_count': len({f['uid'] for f in items}),
            'polygon_overlap_m2': unary_union(polys).area if polys else 0.,
            'source_uids': sorted({f['uid'] for f in items}),
            'meaning': '自定义筛查带与现有建筑图斑相交；不是拆迁红线或已确认拆迁面积'}


def elevation(ctx, route):
    configured = ctx.options.get('dem_path')
    if not configured:
        return {'status': 'pending', 'reason': '未配置DEM；不凭海拔推定丘陵/山地类别'}
    path = (ctx.root/configured).resolve()
    if not path.exists():
        return {'status': 'pending', 'reason': 'DEM路径不存在'}
    import rasterio
    step = float(ctx.options.get('elevation_step_m', 25))
    if step <= 0:
        raise ValueError('elevation_step_m须大于0')
    stations = np.linspace(0, route.length, max(2, int(math.ceil(route.length/step))+1))
    with rasterio.open(path) as ds:
        transform = Transformer.from_crs(ctx.catalog.crs, ds.crs, always_xy=True)
        xy = [route.interpolate(float(s)).coords[0] for s in stations]
        points = [transform.transform(x-ctx.catalog.offset[0], y-ctx.catalog.offset[1]) for x,y in xy]
        values, profile = [], []
        for point, value in zip(points, ds.sample(points, masked=True)):
            x,y=point
            height = None
            if ds.bounds.left <= x < ds.bounds.right and ds.bounds.bottom < y <= ds.bounds.top:
                if not np.ma.is_masked(value[0]) and math.isfinite(float(value[0])):
                    height = float(value[0]); values.append(height)
            profile.append({'chainage_m':float(stations[len(profile)]), 'height_m':height})
    key = 'dem_hash:'+str(path)
    if key not in ctx.cache:
        ctx.cache[key] = file_hash(path)
    return {'status': 'measured' if len(values)==len(stations) else 'partial',
            'min_m': min(values) if values else None, 'max_m': max(values) if values else None,
            'valid_samples': len(values), 'samples': len(stations), 'sampling_step_max_m': step,
            'profile': profile,
            'source': str(path), 'sha256': ctx.cache[key], 'vertical_datum': '未独立核定，按所用DEM高程值',
            'meaning': '沿线采样高程范围；不代替勘测断面或地形分类'}


def scheme_measurements(ctx, facts):
    key = 'measurements:'+facts['id']
    if key in ctx.cache:
        return ctx.cache[key]
    route = LineString(facts['path'])
    all_features = ctx.catalog.nearby(route)
    radius = float(ctx.options.get('ecology_nearby_m', 300))
    width = float(ctx.options.get('building_screen_width_m', 60))
    if radius < 0 or width <= 0:
        raise ValueError('生态邻近范围不能为负，建筑筛查宽度必须为正')
    events = crossings(route, ctx.catalog, include_contacts=True)
    result = {'crossings': [e for e in events if e['relation'] in ('cross','traverse')],
              'contacts': [e for e in events if e['relation'] in ('contact','overlap')],
              'ecology': ecology_relations(route, ctx.catalog, radius,ctx.schemes[facts['id']]['analysis'].get('towers',[]),
                    bool(ctx.schemes[facts['id']]['analysis'].get('tower_placement',{}).get('straight_placement_checked'))),
              'ecology_nearby_m': radius,
              'ecological_redline_length_m': overlap_length(route, [f for f in all_features if '生态保护红线' in f['category']]),
              'farmland_length_m': overlap_length(route, [f for f in all_features if '基本农田' in f['category']]),
              'mining': [dict(uid=f['uid'],label=f['label']) for f in all_features if '矿' in f['category']],
              'mining_layer_present': any('矿' in f['category'] for f in ctx.catalog.features),
              'building_screen': building_screen(route, ctx.catalog, width),
              'elevation': elevation(ctx, route),
              'rule_checks': layer_checks(ctx, route, ctx.schemes[facts['id']]['analysis'])}
    from .environment import weather_zones,relief
    result['weather_zones']=weather_zones(ctx,facts)
    result['relief']=relief(result['elevation'])
    ctx.cache[key] = result
    return result
