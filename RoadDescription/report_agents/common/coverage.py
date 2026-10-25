"""Distinguish missing layers, absent intersections and absent names."""
from shapely.geometry import LineString

THEMES={
    '生态敏感点':('水源','自然保护','生态','公园','湿地','风景'),
    '高速公路':('高速',),'铁路':('铁路',),'普通道路':('国道','省道','县道','乡道','道路'),
    '电力线路':('输电',),'矿区':('矿',),'河流与水域':('河流','水域'),
    '建筑及其他限制地物':('建筑','房屋','基本农田','禁建','禁止')}


def inventory(catalog, facts, radius=1000):
    rows=[]
    for title,words in THEMES.items():
        features=[f for f in catalog.features if any(w in f['category'] for w in words)]
        item={'type':title,'dataset_count':len(features),'schemes':{},'radius_m':radius}
        for fact in facts:
            route=LineString(fact['path'])
            distances=sorted(((route.distance(f['geometry']),f) for f in features),key=lambda x:x[0])
            nearby=[f for distance,f in distances if distance<=radius]
            nearest=distances[0] if distances else None
            item['schemes'][fact['id']]={'nearby_count':len(nearby),'intersecting_features':sum(route.intersects(f['geometry']) for f in nearby),
                'labels':list(dict.fromkeys(f['label']+('（未提供专名）' if not f['name'] else '') for f in nearby)),
                'source_uids':[f['uid'] for f in nearby],
                'nearest':{'label':nearest[1]['label'],'category':nearest[1]['category'],'distance_m':nearest[0],
                           'source_uid':nearest[1]['uid'],'named':bool(nearest[1]['name'])} if nearest else None}
        rows.append(item)
    return rows


def scope_text(item, scheme_id):
    value=item['schemes'][scheme_id]
    if not item['dataset_count']:return '当前数据包未提供该专题图层，不能判定是否存在'
    if value['nearby_count']:
        labels='；'.join(value['labels'])
        return f"路线周边{item['radius_m']:g}m内{value['nearby_count']}个图斑/线段：{labels}；与路线相交{value['intersecting_features']}个要素（非跨越次数）"
    near=value['nearest']
    return f"图层已提供，路线周边{item['radius_m']:g}m内未检出；最近{near['label']}距路线约{near['distance_m']/1000:.2f}km"
