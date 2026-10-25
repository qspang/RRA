"""Apply planner-canonical deltas to the exact archived map; never guess IDs."""
import gzip
from pathlib import Path
import math
import geopandas as gpd
from shapely.geometry import shape, Polygon, LineString, Point
from .io import read_json,digest,file_hash


def normalise(changes):
    changes=changes or {}
    result={}
    for key,alias in [('deleted_ids','deleted'),('modified_features','modified'),('added_features','added')]:
        value=changes.get(key,changes.get(alias,[])) or []
        if not isinstance(value,list):raise ValueError('地图增量'+key+'须为数组')
        result[key]=value
    if any(k not in ('deleted_ids','deleted','modified_features','modified','added_features','added') for k,v in changes.items() if v):
        raise ValueError('地图增量存在不支持字段，须提供规划响应中的canonical feature_adjustments')
    return result


def geometry(item):
    if item.get('geometry_full'):
        value=shape(item['geometry_full'])
    elif isinstance(item.get('geometry'),dict):value=shape(item['geometry'])
    else:
        points=item.get('geometry',[])
        kind=item.get('shape_type','polygon')
        value=Polygon(points) if kind=='polygon' else LineString(points) if kind in ('line','polyline') else Point(points[0])
    if value.is_empty or not value.is_valid or not all(math.isfinite(v) for v in value.bounds):
        raise ValueError('增量地物几何无效：'+str(item.get('id')))
    return value


def bind_snapshot(map_data,responses):
    snapshots=[normalise(r.get('map_auxiliary',{}).get('feature_adjustments')) for r in responses]
    fingerprints=[digest(s) for s in snapshots]
    if len(set(fingerprints))>1:raise ValueError('南北方案地图增量版本不一致，须基于同一地图修订比较')
    active=snapshots[0] if snapshots else normalise(None)
    return dict(map_data,report_adjustments=active)


def apply_snapshot(catalog,map_data,archive_dir):
    changes=normalise(map_data.get('report_adjustments',map_data.get('feature_adjustments')))
    if not any(changes.values()):return
    archive=Path(archive_dir)/map_data.get('raw_map_file','map.raw.json.gz')
    if not archive.is_file():raise ValueError('编辑地图需要完整原始map.raw.json.gz快照')
    with gzip.open(archive,'rt',encoding='utf-8') as stream:raw=__import__('json').load(stream)
    if raw.get('features_lazy'):raise ValueError('地图为懒加载快照，须先归档完整tol=0地物')
    initial={str(f['id']):dict(f) for f in raw['features']}
    already=normalise(raw.get('feature_adjustments'))
    if any(already.values()) and digest(already)!=digest(changes):
        raise ValueError('归档地图已含不同增量，无法可靠倒推出基础版本，请重新归档基础地图')
    if not any(already.values()):
        touched=set()
        for identifier in changes['deleted_ids']:
            identifier=str(identifier)
            if identifier not in initial or identifier in touched:raise ValueError('删除地物ID无效或重复：'+identifier)
            initial.pop(identifier);touched.add(identifier)
        for operation in ('modified_features','added_features'):
            for feature in changes[operation]:
                identifier=str(feature.get('id',''))
                if not identifier or identifier in touched:raise ValueError('增量ID缺失或重复')
                if (operation=='modified_features')!=(identifier in initial):raise ValueError('修改/新增地物ID与基础快照不匹配：'+identifier)
                # The canonical response carries a complete feature, never a guessed patch.
                if not feature.get('name') or not feature.get('geometry'):raise ValueError('增量地物缺完整名称或几何')
                value={**catalog.runtime_rules.get(feature['name'],{}),**feature}
                if operation=='modified_features' and (initial[identifier].get('layer_kind') or initial[identifier].get('variant'))=='primary':
                    legacy=dict(initial[identifier]);legacy.pop('geometry_full',None)
                    if geometry(value).hausdorff_distance(geometry(legacy))>.001:
                        raise ValueError('规划器M1编辑仅更新规则，几何移动未可靠生效；请重新预处理或用受支持的对象重建：'+identifier)
                    # M1 rule editing must retain the original complete polygon, including holes.
                    if initial[identifier].get('geometry_full'):value['geometry_full']=initial[identifier]['geometry_full']
                geometry(value);initial[identifier]=value;touched.add(identifier)
    else:
        # /api/map can retain old display geometry for native solver objects.
        # Canonical native edits take precedence; primary M1 edits remain rule-only.
        for feature in changes['modified_features']:
            identifier=str(feature['id'])
            if identifier not in initial:raise ValueError('已编辑快照缺少修改对象：'+identifier)
            previous=initial[identifier]
            if (previous.get('layer_kind') or previous.get('variant'))=='primary':
                legacy=dict(previous);legacy.pop('geometry_full',None)
                if geometry(feature).hausdorff_distance(geometry(legacy))>.001:
                    raise ValueError('规划器M1编辑仅更新规则，几何移动未可靠生效：'+identifier)
            else:initial[identifier]={**catalog.runtime_rules.get(feature['name'],{}),**feature}
    previous={f['uid']:f for f in catalog.features};features=[];constraints={'forbidden_polygons':[],'no_tower_polygons':[]}
    for identifier,item in initial.items():
        geom=geometry(item)
        category=item.get('name','');kind=item.get('layer_kind') or item.get('variant') or 'primary'
        rule={**catalog.runtime_rules.get(category,{}),**item}
        if kind=='primary':
            uid=str(item.get('src_uid') or 'edit:'+identifier)
            old=previous.get(uid,{})
            features.append({**old,'uid':uid,'src_fid':str(item.get('src_fid','')),'category':category,
                'level1':item.get('category',''),'name':old.get('name',''),'label':old.get('name') or category,
                'name_source':old.get('name_source',''),'county':old.get('county',''),'county_source':old.get('county_source',''),
                'village':old.get('village',''),'tunnel':old.get('tunnel',''),'rule_id':item.get('rule_id'),
                'geometry':geom,'runtime_rule':rule,'map_feature_id':identifier})
        for name,test in [('forbidden_polygons',rule.get('cross_rule')=='forbidden'),
                          ('no_tower_polygons',rule.get('tower_rule') in ('forbidden','buffer_forbidden'))]:
            if test:
                distance=float(rule.get('buffer_range') or 0)
                if distance<0 or not math.isfinite(distance):raise ValueError('无效保护距离')
                area=geom.buffer(distance) if distance else geom
                constraints[name].append({'level2':category,'geometry':area,'map_feature_id':identifier})
    catalog.features=features
    catalog.frame=gpd.GeoDataFrame(features,geometry='geometry',crs=catalog.crs);catalog.index=catalog.frame.sindex
    catalog.constraint_frames={k:gpd.GeoDataFrame(v or {'level2':[],'geometry':[]},geometry='geometry',crs=catalog.crs) for k,v in constraints.items()}
    catalog.provenance.update(map_snapshot_sha256=file_hash(archive),adjustments_sha256=digest(changes),
        constraint_source='归档API完整地物+规划响应canonical增量；采用每个地物实际运行规则')
