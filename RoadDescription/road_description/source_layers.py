"""Read-only report overlays; never alter planner masks or infer missing rules."""
from pathlib import Path
import re
import geopandas as gpd
from shapely import affinity, make_valid, force_2d
from .facts import clean
from .io import digest, file_hash


def attach_layers(catalog, specifications):
    evidence=[]
    for spec in specifications:
        path=Path(spec['path']).resolve()
        if not path.exists():raise ValueError('补充图层不存在：'+str(path))
        # Hash all GDB members so a layer update cannot silently reuse old evidence.
        files=sorted(x for x in path.rglob('*') if x.is_file()) if path.is_dir() else [path]
        fingerprint=digest([(str(x.relative_to(path)) if path.is_dir() else x.name,file_hash(x)) for x in files])
        frame=gpd.read_file(path,layer=spec['layer'])
        if frame.crs is None:raise ValueError('补充图层缺少坐标系')
        frame=frame.to_crs(catalog.crs)
        normal=lambda s:re.sub(r'[()（）\s]','',s)
        matched=[r for r in getattr(catalog,'rules',{}).values() if normal(r.get('level2',''))==normal(spec['category'])]
        reference_rule=matched[0] if len(matched)==1 else None
        replaced=0
        if spec.get('replace_report_category'):
            before=len(catalog.features)
            catalog.features=[f for f in catalog.features if f['category']!=spec['category']]
            replaced=before-len(catalog.features)
        added=0
        for index,row in frame.iterrows():
            if row.geometry is None or row.geometry.is_empty:continue
            geom=affinity.translate(make_valid(force_2d(row.geometry)),xoff=catalog.offset[0],yoff=catalog.offset[1])
            name=next((clean(row.get(k)) for k in ('name_zh','name','ZRBHDMC','HXMC','Name') if clean(row.get(k))), '')
            if name.replace('.','').isdigit() or name in ('乡道','道路','小路','未命名',spec['layer'],spec['category']):name=''
            uid='supp:'+digest([fingerprint,spec['layer'],str(index)])[:20]
            catalog.features.append(dict(uid=uid,src_fid=str(index),category=spec['category'],level1='报告补充图层',
                name=name,label=name or spec['category'],name_source='补充GDB属性' if name else '',
                county='',county_source='',village='',tunnel='',rule_id=reference_rule['rule_id'] if reference_rule else None,geometry=geom,
                supplemental=True,source_layer=spec['layer'],source_path=str(path)))
            added+=1
        evidence.append({'path':str(path),'layer':spec['layer'],'category':spec['category'],
                         'sha256':fingerprint,'count':added,'replaced_report_feature_count':replaced,
                         'reference_rule_id':reference_rule['rule_id'] if reference_rule else None,
                         'scope':'仅报告空间核查，不改变规划器已执行的规则和计价'})
    catalog.frame=gpd.GeoDataFrame(catalog.features,geometry='geometry',crs=catalog.crs)
    catalog.index=catalog.frame.sindex
    catalog.provenance['supplemental_layers']=evidence
    catalog.provenance['supplemental_layers_sha256']=digest(evidence)
