"""GIS measurements and rule evidence. No geographic names are inferred by a model."""
import math
import re
from pathlib import Path

import geopandas as gpd
import numpy as np
from pyproj import CRS, Geod, Transformer
from shapely import affinity, make_valid
from shapely.geometry import LineString, Point, shape
from shapely.ops import substring, unary_union, nearest_points

from .io import digest, file_hash, read_json


def clean(value):
    if value is None or str(value).strip().lower() in {'', 'nan', 'none', 'null'}:
        return ''
    return str(value).strip()


def tunnel_mark(value):
    value=clean(value).lower()
    if value in ('t','true','yes','1'):return True
    if value in ('f','false','no','0'):return False
    return None


def official_name(row, overrides=None):
    uid = clean(row.get('attr_src_uid'))
    if overrides and uid in overrides:
        return str(overrides[uid]), 'name_overrides:' + uid
    category = clean(row.get('std_level2'))
    fields = ['attr_name_zh', 'attr_name__1', 'attr_official_n']
    if '生态' in category or '保护' in category or '公园' in category:
        fields += ['attr_ZRBHDMC', 'attr_HXMC']
    fields += ['attr_Name']
    for field in fields:
        val = clean(row.get(field))
        if val and not re.fullmatch(r'[\d.\s]+', val):
            return val.replace(';', '、'), field
    return '', ''


def county_name(row):
    for key in ('attr_XIAN', 'attr_所属区p', '_district_name', 'attr_XZQMC'):
        value = re.sub(r'^\d+', '', clean(row.get(key)))
        if value.endswith(('县', '区')) and len(value) <= 12:
            return value, key
    return '', ''


def village_name(row):
    # ZLDWMC is the parcel's location unit. Do not infer location from QSDWMC (ownership).
    for key in ('attr_XZQMC','attr_ZLDWMC'):
        value=clean(row.get(key))
        if re.fullmatch(r'[\u4e00-\u9fff]{2,12}[村镇]',value):return value,key
    return '',''


def line_parts(geometry):
    if geometry.is_empty:
        return []
    if geometry.geom_type == 'LineString':
        return [geometry]
    if hasattr(geometry, 'geoms'):
        return [part for g in geometry.geoms for part in line_parts(g)]
    return []


def intersection_events(route, geom):
    """Keep separate visits to one object. Point tangencies aren't polygon crossings."""
    intersection = route.intersection(geom)
    polygon = geom.geom_type in ('Polygon', 'MultiPolygon')
    if intersection.is_empty:
        return []
    if hasattr(intersection, 'geoms'):
        parts = list(intersection.geoms)
    else:
        parts = [intersection]
    intervals = []
    for p in parts:
        if p.geom_type == 'Point':
            if not polygon:
                s = route.project(p)
                intervals.append((s, s, 'cross'))
        elif p.geom_type == 'LineString' and p.length > 0.05:
            lo, hi = sorted([route.project(Point(p.coords[0])), route.project(Point(p.coords[-1]))])
            relation = 'traverse' if polygon and geom.contains(p.interpolate(.5, normalized=True)) else 'overlap'
            intervals.append((lo, hi, relation))
    # Coalesce only numerical duplicates, never all occurrences of the same feature.
    result = []
    for lo, hi, kind in sorted(intervals):
        if result and kind == result[-1][2] and lo <= result[-1][1] + .1:
            result[-1] = (result[-1][0], max(hi, result[-1][1]), kind)
        else:
            result.append((lo, hi, kind))
    return result


def canonical_path(scheme, start=None):
    analysis = scheme['analysis']
    raw = analysis.get('simplified_waypoints') or scheme.get('path')
    pts = [(float(p['x']), float(p['y'])) if isinstance(p, dict) else tuple(map(float, p[:2])) for p in raw]
    pts = [p for i, p in enumerate(pts) if i == 0 or p != pts[i-1]]
    if len(pts) < 2 or not all(math.isfinite(v) for p in pts for v in p):
        raise ValueError('路径坐标无效')
    if start is not None and math.dist(pts[-1], start) < math.dist(pts[0], start):
        pts.reverse()
    route = LineString(pts)
    if route.length == 0 or math.dist(pts[0], pts[-1]) < .01:
        raise ValueError('路径端点重合')
    if not route.is_simple:
        raise ValueError('路径存在自交/回环，需逐段里程处理；当前版本拒绝生成错误事件顺序')
    reported = analysis.get('total_length')
    if reported is not None and abs(route.length - reported) > max(.2, route.length * .00001):
        raise ValueError('最终分析几何与接口长度不一致')
    display = scheme.get('path')
    if display:
        other = LineString([(p['x'], p['y']) if isinstance(p, dict) else p[:2] for p in display])
        if other.hausdorff_distance(route) > 1:
            raise ValueError('方案path与分析几何不一致')
    return route


class Catalog:
    def __init__(self, dataset, map_data, overrides=None, archive_dir=None, supplemental_layers=None):
        self.root = Path(dataset).resolve()
        self.manifest = read_json(self.root / 'manifest.json')
        self.geo = map_data['geo_meta']
        self.crs = self.geo['working_crs']
        if CRS(self.crs) != CRS(self.manifest['working_crs']):
            raise ValueError('地图与底层资料坐标系不匹配')
        map_path = map_data.get('manifest_path')
        if map_path and Path(map_path).exists():
            actual = Path(map_path)
            if actual.is_file():
                actual = actual.parent
            if file_hash(actual / 'manifest.json') != file_hash(self.root / 'manifest.json'):
                raise ValueError('地图版本与报告数据包不匹配')
        self.offset = tuple(self.geo['offset'])
        source = self.root / 'm1/standardized_features.gpkg'
        df = gpd.read_file(source)
        if CRS(df.crs) != CRS(self.crs):
            df = df.to_crs(self.crs)
        df = df[df['_variant'].eq('primary')].copy()
        self.features = []
        self.rules = {int(r['rule_id']): r for r in read_json(self.root / 'm3/rule_config.json')['compiled_rules']}
        self.runtime_rules = map_data.get('feature_types', {})
        for _, row in df.iterrows():
            geom = row.geometry
            if geom is None or geom.is_empty:
                continue
            geom = make_valid(geom)
            name, name_field = official_name(row, overrides)
            county, county_field = county_name(row)
            village, village_field = village_name(row)
            category = clean(row.get('std_level2'))
            rid = clean(row.get('std_rule_id'))
            rule_id = int(float(rid)) if rid else None
            ref = clean(row.get('attr_ref'))
            label = name or category
            voltage=re.search(r'\d+kV',category)
            if name and voltage and voltage.group() not in label:
                label=voltage.group()+' '+label
            if ref and ref not in label:
                label += '（' + ref.replace(';', '/') + '）'
            # A strict attribute allowlist keeps unrelated property records out of model calls.
            self.features.append(dict(uid=clean(row.get('attr_src_uid')),
                src_fid=clean(row.get('attr_src_fid')), category=category,
                level1=clean(row.get('std_level1')), name=name, label=label,
                name_source=name_field, county=county, county_source=county_field,
                village=village,village_source=village_field,
                tunnel=clean(row.get('attr_tunnel')), rule_id=rule_id,
                geometry=affinity.translate(geom, xoff=self.offset[0], yoff=self.offset[1])))
        self.frame = gpd.GeoDataFrame(self.features, geometry='geometry', crs=self.crs)
        self.index = self.frame.sindex
        self.to_lonlat = Transformer.from_crs(self.crs, 4326, always_xy=True)
        self.geod = Geod(ellps='GRS80')
        self.provenance = {'dataset': str(self.root), 'working_crs': self.crs, 'offset': self.offset,
                           'manifest_sha256': file_hash(self.root/'manifest.json'),
                           'features_sha256': file_hash(source),
                           'rules_sha256': file_hash(self.root/'m3/rule_config.json')}
        from .map_snapshot import apply_snapshot
        apply_snapshot(self,map_data,archive_dir or self.root)
        if supplemental_layers:
            from .source_layers import attach_layers
            attach_layers(self, supplemental_layers)

    def nearby(self, geometry, margin=0):
        query = geometry.buffer(margin) if margin else geometry
        return [self.features[int(i)] for i in self.index.query(query, predicate='intersects')]

    def bearing(self, a, b):
        ox, oy = self.offset
        lon1, lat1 = self.to_lonlat.transform(a[0]-ox, a[1]-oy)
        lon2, lat2 = self.to_lonlat.transform(b[0]-ox, b[1]-oy)
        return self.geod.inv(lon1, lat1, lon2, lat2)[0] % 360

    def rule(self, feature):
        if feature.get('supplemental') and feature.get('rule_id') is None:
            return dict(rule_id=None,category=feature['category'],cross_forbidden=False,tower_forbidden=False,
                        cross_cost=0,cross_cost_per_km=0,min_cross_angle=None,parallel_bonus=0,
                        source='报告补充资料，未配置规划规则；布尔值仅用于不触发既有规则，不能作为允许施工结论')
        compiled = self.rules.get(feature['rule_id'], {})
        runtime = feature.get('runtime_rule') or self.runtime_rules.get(feature['category']) or self.runtime_rules.get(compiled.get('level2'), {})
        return dict(rule_id=feature['rule_id'], category=feature['category'],
                    cross_forbidden=runtime.get('cross_rule') == 'forbidden' if runtime else not compiled.get('cross_allow', True),
                    tower_forbidden=runtime.get('tower_rule') in ('forbidden', 'buffer_forbidden') if runtime else not compiled.get('is_landable', True),
                    cross_cost=runtime.get('cross_cost', compiled.get('cross_cost', 0)),
                    cross_cost_per_km=runtime.get('cross_cost_per_km', compiled.get('cross_cost_per_km', 0)),
                    min_cross_angle=runtime.get('min_cross_angle', compiled.get('min_cross_angle_deg')),
                    parallel_bonus=runtime.get('parallel_bonus', compiled.get('parallel_reward')),
                    source='api/map.feature_types + m3/rule_config.json')

    def coverage(self):
        result = {}
        for f in self.features:
            stat = result.setdefault(f['category'], {'count': 0, 'named': 0, 'county_attributed': 0})
            stat['count'] += 1
            stat['named'] += bool(f['name'])
            stat['county_attributed'] += bool(f['county'])
        return result


def compass(bearing):
    return ['北', '东北', '东', '东南', '南', '西南', '西', '西北'][int((bearing + 22.5) // 45) % 8]


def route_segments(route, catalog, target=6000):
    # Group actual consecutive headings; do not manufacture equal-length route sections.
    def section(lo,hi):
        a,b=route.interpolate(lo),route.interpolate(hi)
        bearing=catalog.bearing(a.coords[0],b.coords[0])
        return {'start_m':lo,'end_m':hi,'length_m':hi-lo,
                'bearing_true_deg':bearing,'direction':compass(bearing)}
    result=[];distance=0.
    for a,b in zip(route.coords,list(route.coords)[1:]):
        length=math.dist(a,b);item=section(distance,distance+length);distance+=length
        if result and ((result[-1]['direction']==item['direction'] and result[-1]['length_m']<target)
                       or result[-1]['length_m']<400):
            result[-1]=section(result[-1]['start_m'],item['end_m'])
        else:result.append(item)
    if len(result)>1 and result[-1]['length_m']<400:
        result[-2:]=[section(result[-2]['start_m'],result[-1]['end_m'])]
    while len(result)>8:
        def score(i):
            a,b=result[i:i+2];delta=abs(a['bearing_true_deg']-b['bearing_true_deg'])
            return min(delta,360-delta)*100+min(a['length_m'],b['length_m'])
        index=min(range(len(result)-1),key=score)
        result[index:index+2]=[section(result[index]['start_m'],result[index+1]['end_m'])]
    return result


def parallel_sections(route, catalog, max_distance=300, max_angle=15, step=100):
    """Sampled physical-line proximity, separate from the planner's reward accounting."""
    found=[]
    references=[f for f in catalog.nearby(route,max_distance) if '输电' in f['category']
                and f['geometry'].geom_type in ('LineString','MultiLineString')]
    for feature in references:
        for reference in line_parts(feature['geometry']):
            runs=[];current=[]
            for lo in np.arange(0,route.length,step):
                hi=min(lo+step,route.length);mid=(lo+hi)/2
                point=route.interpolate(mid)
                position=reference.project(point)
                ra=reference.interpolate(max(0,position-50));rb=reference.interpolate(min(reference.length,position+50))
                a=route.interpolate(max(0,mid-50));b=route.interpolate(min(route.length,mid+50))
                u=(b.x-a.x,b.y-a.y);v=(rb.x-ra.x,rb.y-ra.y)
                denominator=math.hypot(*u)*math.hypot(*v)
                angle=math.degrees(math.acos(min(1,max(-1,abs(u[0]*v[0]+u[1]*v[1])/denominator)))) if denominator else 90
                if point.distance(reference)<=max_distance and angle<=max_angle:
                    current.append((float(lo),float(hi)))
                elif current:
                    runs.append(current);current=[]
            if current:runs.append(current)
            for run in runs:
                length=run[-1][1]-run[0][0]
                if length>=500:
                    found.append({'feature_uid':feature['uid'],'label':feature['label'],'has_official_name':bool(feature.get('name')),
                                  'name_source':feature['name_source'],'start_m':run[0][0],
                                  'end_m':run[-1][1],'length_m':length,'step_m':step,
                                  'distance_limit_m':max_distance,'angle_limit_deg':max_angle,
                                  'rule':catalog.rule(feature)})
    # Same named line can be fragmented; do not add overlapping intervals twice.
    found.sort(key=lambda r:(r['label'],r['start_m']))
    merged=[]
    for item in found:
        if (merged and item['label']==merged[-1]['label'] and item['start_m']<=merged[-1]['end_m']
                and (item['feature_uid']==merged[-1]['feature_uid'] or (item['has_official_name'] and merged[-1]['has_official_name']))):
            merged[-1]['end_m']=max(merged[-1]['end_m'],item['end_m'])
            merged[-1]['length_m']=merged[-1]['end_m']-merged[-1]['start_m']
            merged[-1]['source_uids'].append(item['feature_uid'])
        else:
            item['source_uids']=[item['feature_uid']];merged.append(item)
    return sorted(merged,key=lambda r:r['start_m'])


def pair_schemes(items, tolerance=50):
    if len(items) != 2:
        raise ValueError('每个项目必须提供两个有效方案；不复制一条路径凑成两条')
    a, b = items
    for endpoint in (0, -1):
        if math.dist(a['path'][endpoint], b['path'][endpoint]) > 1:
            raise ValueError('两方案起终点不一致')
    la, lb = LineString(a['path']), LineString(b['path'])
    if la.hausdorff_distance(lb) <= tolerance:
        raise ValueError('两候选差异不足，无法作为南北两个方案')
    # Weighted by route distance, independent of vertex sampling density.
    for item in items:
        line = LineString(item['path'])
        item['northing_score'] = float(np.mean([line.interpolate(t, normalized=True).y for t in np.linspace(.2, .8, 101)]))
    items.sort(key=lambda v: v['northing_score'], reverse=True)
    for i, item in enumerate(items):
        item['name'] = '北方案' if i == 0 else '南方案'
        item['section_index'] = i + 1
    shared = []
    for route, other in ((la, lb), (lb, la)):
        start = 0.
        for s in np.arange(0, route.length+25, 25):
            s = min(s, route.length)
            if route.interpolate(s).distance(other) > tolerance:
                break
            start = s
        end = 0.
        for s in np.arange(0, route.length+25, 25):
            s = min(s, route.length)
            if route.interpolate(route.length-s).distance(other) > tolerance:
                break
            end = s
        shared.append({'start_m': start, 'end_m': end})
    # Match mapping after north/south sorting by id.
    mapped = {a['id']: shared[0], b['id']: shared[1]}
    for item in items:
        item['shared_ends'] = mapped[item['id']]
    return {'method': '中间20%～80%里程等距采样的平均地图Y坐标，较大者为北方案',
            'shared_tolerance_m': tolerance, 'shared_sampling_m': 25,
            'hausdorff_distance_m': la.hausdorff_distance(lb),
            'note': '上下位置为整体相对关系；局部可交叉，共用段为几何近似共用。'}


def extract_facts(scheme, catalog, config, scheme_id):
    route = canonical_path(scheme, config.get('start'))
    analysis = scheme['analysis']
    events, constraints, counties, villages, terrain = [], [], {}, {}, []
    important = ('河流', '高速', '公路', '道路', '国道', '省道', '县道', '乡道', '铁路', '输电', '保护', '公园', '矿', '禁止')
    for feature in catalog.nearby(route, config.get('nearby_m', 300)):
        geom = feature['geometry']
        intersections = intersection_events(route, geom)
        distance = route.distance(geom)
        if feature['category']=='山谷':
            for lo,hi,kind in intersections:
                if kind in ('traverse','cross'):
                    terrain.append({'fact_id':f'{scheme_id}_T{len(terrain)+1:03d}',
                        'label':'山谷','category':'山谷','start_m':lo,'end_m':hi,'relation':kind,
                        'length_m':hi-lo,'source_uids':[feature['uid']],
                        'xy':list(route.interpolate((lo+hi)/2).coords[0])})
        if intersections and feature['county']:
            first=min(x[0] for x in intersections)
            item = counties.setdefault(feature['county'], {'name': feature['county'], 'source_uids': [], 'evidence': '相交地物属地属性','first_chainage_m':first})
            item['first_chainage_m']=min(first,item['first_chainage_m'])
            item['source_uids'].append(feature['uid'])
        if intersections and feature['village']:
            villages.setdefault(feature['village'], {'source_uid':feature['uid'],'source_field':feature.get('village_source','')})
        if not any(k in feature['category'] for k in important):
            continue
        rule = catalog.rule(feature)
        for lo, hi, kind in intersections:
            if kind == 'overlap':
                continue
            if kind=='cross':
                from report_agents.common.gis import crosses_at
                if not crosses_at(route,geom,route.interpolate(lo)):kind='contact'
            middle = (lo+hi)/2
            events.append(dict(feature_uid=feature['uid'], category=feature['category'],
                name=feature['name'], label=feature['label'], name_source=feature['name_source'],
                relation=kind, start_m=lo, end_m=hi, length_m=hi-lo,
                xy=list(route.interpolate(middle).coords[0]), tunnel=feature['tunnel'], rule=rule))
        if not intersections and distance > .1 and rule['cross_forbidden']:
            nearest = nearest_points(route,geom)[0]
            s = route.project(nearest)
            constraints.append(dict(feature_uid=feature['uid'], label=feature['label'],
                relation='outside_forbidden', distance_m=distance, chainage_m=s,
                rule=rule, explanation=f"{feature['label']}按系统规则禁止通行，线路从该范围外侧通过"))
    # Merge numerical adjacency only; separate visits and polygon holes stay separate.
    events.sort(key=lambda e: e['start_m'])
    merged = []
    for event in events:
        previous = next((p for p in reversed(merged) if p['category'] == event['category']
                         and p['label'] == event['label'] and event['name']
                         and p['relation'] == event['relation']
                         and 0 <= event['start_m'] - p['end_m'] <= .1), None)
        if previous:
            previous['end_m'] = max(previous['end_m'], event['end_m'])
            previous['length_m'] = previous['end_m']-previous['start_m']
            previous['source_uids'].append(event['feature_uid'])
        else:
            event['source_uids'] = [event['feature_uid']]
            merged.append(event)
    events = merged
    for i, event in enumerate(events):
        event['fact_id'] = f'{scheme_id}_E{i+1:03d}'
    constraints.sort(key=lambda x: x['distance_m'])
    for i, item in enumerate(constraints):
        item['fact_id'] = f'{scheme_id}_C{i+1:03d}'
    for i, segment in enumerate(route_segments(route, catalog)):
        segment['fact_id'] = f'{scheme_id}_S{i+1:02d}'
        segment['event_ids'] = [e['fact_id'] for e in events if segment['start_m'] <= e['start_m'] < segment['end_m']]
        if i == 0:
            segments = []
        segments.append(segment)
    # Optional authoritative polygons supersede partial parcel attribution.
    admin_complete = False
    if config.get('admin_boundary'):
        admin = gpd.read_file(config['admin_boundary']).to_crs(catalog.crs)
        entries, covered = [], []
        for _, row in admin.iterrows():
            geom = affinity.translate(row.geometry, xoff=catalog.offset[0], yoff=catalog.offset[1])
            cut = route.intersection(geom)
            if cut.length > .1:
                entries.append({'name': str(row[config.get('admin_name_field', 'name')]),
                                'length_m': cut.length, 'evidence': '行政区划图层相交',
                                'first_chainage_m':min((x[0] for x in intersection_events(route,geom)),default=0)})
                covered.append(cut)
        counties = {e['name']: e for e in entries}
        admin_complete = bool(covered) and route.difference(unary_union(covered).buffer(.05)).length < 1
    wind = []
    for z in analysis.get('wind_ice_allocation', []):
        wind.append({k:v for k,v in z.items() if k in ('wind_zone','ice_zone','wind_ms','ice_mm','length_m')})
    physical_parallel=parallel_sections(route,catalog)
    for i,run in enumerate(physical_parallel):run['fact_id']=f'{scheme_id}_P{i+1:03d}'
    result = dict(id=scheme_id, path=[list(p) for p in route.coords], geometry_hash=digest(list(route.coords)),
        metrics={'length_m':route.length, 'api_length_m':analysis.get('total_length'),
                 'straight_distance_m':math.dist(route.coords[0],route.coords[-1]),
                 'tortuosity':route.length/math.dist(route.coords[0],route.coords[-1])},
        segments=segments, events=events, constraints=constraints, physical_parallel=physical_parallel, terrain=sorted(terrain,key=lambda x:x['start_m']),
        counties=sorted(counties.values(),key=lambda c:c['first_chainage_m']), admin_complete=admin_complete,
        villages=[{'name':k,**v} for k,v in villages.items()],
        parallel_runs=[{k:v for k,v in r.items() if k in ('feature_id','feature_name','length_m','start_xy','end_xy')}
                       for r in analysis.get('parallel_bonus_runs', [])],
        wind_ice=wind, feasibility={'feasible':True, 'cost_model_version':analysis.get('cost_model_version'),
        'tower_placement':analysis.get('tower_placement'), 'warnings':scheme.get('warnings',[])})
    result['missing'] = []
    if not admin_complete:
        result['missing'].append('完整行政区划缺失；仅报告相交地物可证明的属地区县，不据此宣称全线县区数量')
    unnamed = sum(not e['name'] for e in events)
    if unnamed:
        result['missing'].append(f'{unnamed}个重要地物事件尚无专名，使用类别名称和里程区分')
    return result
