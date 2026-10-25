"""Live add/modify/delete snapshot roundtrip in an isolated planner cookie."""
import sys,copy
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from road_description.planner import PlannerClient
from road_description.io import read_json,write_json,archive_map,digest
from road_description.facts import Catalog
from road_description.map_snapshot import bind_snapshot
out=Path('outputs/implementation_complete_20261025/integration/map_edits');out.mkdir(parents=True,exist_ok=True)
state={'status':'running'}
try:
 client=PlannerClient('http://127.0.0.1:5000');_,base=client.initialize();archive_map(out/'before',base)
 a,b=read_json('outputs/implementation_complete_20261025/integration/edit_candidates.json')
 changed=copy.deepcopy(b);changed.pop('geometry_full',None);changed['cross_cost']=float(changed.get('cross_cost',0))+1
 added={'id':'rd_map_edit_roundtrip','name':'乡道','category':'交通敏感点','shape_type':'line','geometry':[[30000,9000],[30100,9000]],'cross_rule':'allowed','tower_rule':'allowed','buffer_range':0}
 delta={'deleted_ids':[a['id']],'modified_features':[changed],'added_features':[added]}
 reply=client.call('POST','/api/sync_features',timeout=180,json={'feature_adjustments':delta,'sync_version':1})
 _,after=client.initialize();archive_map(out/'after',after)
 canonical=after['feature_adjustments'];write_json(out/'canonical.json',canonical)
 dataset=str(Path(__file__).resolve().parents[1]/'roaddata/preprocessed')
 replay=Catalog(dataset,bind_snapshot(read_json(out/'before/map.json'),[{'map_auxiliary':{'feature_adjustments':canonical}}]),archive_dir=out/'before')
 direct=Catalog(dataset,read_json(out/'after/map.json'),archive_dir=out/'after')
 def signature(cat):return digest(sorted((f['uid'],f['geometry'].wkb_hex) for f in cat.features))
 same=signature(replay)==signature(direct)
 state.update(status='passed' if same else 'failed',reply=reply,canonical_counts={k:len(v) for k,v in canonical.items()},
   geometry_roundtrip_equal=same,replayed_features=len(replay.features),current_features=len(direct.features))
 assert same
except Exception as exc:
 state.update(status='failed',error_type=type(exc).__name__,error=str(exc)[:1000]);raise
finally:write_json(out/'checks.json',state)
print(state)
