import gzip,json
from pathlib import Path
from types import SimpleNamespace
import pytest
from shapely.geometry import LineString,Polygon
from report_agents.common.context import AgentContext
from report_agents.common.specialists import specialist,recommendation
from road_description.io import write_json,digest
from road_description.materials import approved_materials
from road_description.map_snapshot import bind_snapshot,apply_snapshot
from road_description.service import create_app

@pytest.fixture
def ctx(tmp_path):
    (tmp_path/'source.txt').write_text('TEST FIXTURE ONLY')
    fact={'id':'n','name':'北方案','geometry_hash':'h','metrics':{'length_m':100},'events':[{'fact_id':'E'}],'segments':[]}
    return AgentContext(config={},root=tmp_path,source=tmp_path,output=tmp_path/'out',
        catalog=SimpleNamespace(features=[{'uid':'eco'}]),facts={'schemes':[fact]},responses={},schemes={},provenance={},
        supplement={'schemes':{'n':{'route_geometry_hash':'h'}}})

def confirmed(**kwargs):return {'confirmed':True,'source_file':'source.txt','text':'测试专项说明',**kwargs}

def test_specialist_terrain_partial_complete_and_overlap(ctx):
    value=confirmed(records=[{'class':'测试丘陵','start_m':0,'end_m':40}])
    ctx.supplied('n')['specialists']={'terrain':value}
    assert specialist(ctx,'n','terrain')['totals'][0]['percent']==40
    assert not specialist(ctx,'n','terrain')['complete']
    value['records'].append({'class':'测试山地','start_m':40,'end_m':100})
    assert specialist(ctx,'n','terrain')['complete']
    value['records'][1]['start_m']=39
    with pytest.raises(ValueError,match='重叠'):specialist(ctx,'n','terrain')

def test_sources_and_ecology_binding(ctx):
    ctx.supplied('n')['specialists']={'traffic':confirmed(source_file='missing')}
    assert specialist(ctx,'n','traffic')['status']=='pending'
    ctx.supplied('n')['specialists']['ecology']=confirmed(records=[{'source_uids':['other'],'measure':'测试措施'}])
    with pytest.raises(ValueError,match='当前有效'):specialist(ctx,'n','ecology')
    ctx.supplied('n')['specialists']['ecology']['records'][0]['source_uids']=['eco']
    assert specialist(ctx,'n','ecology')['status']=='confirmed_input'

def test_recommendation_binds_both_routes_and_keeps_conflicts(ctx):
    ctx.supplement['recommendation']=confirmed(scheme_id='n',route_geometry_hashes={'n':'stale'})
    with pytest.raises(ValueError,match='几何版本'):recommendation(ctx,[])
    ctx.supplement['recommendation']['route_geometry_hashes']={'n':'h'}
    with pytest.raises(ValueError,match='冲突'):recommendation(ctx,['n'])
    ctx.supplement['recommendation']['conflict_note']='测试：仍须复核'
    assert recommendation(ctx,['n'])['recommended_scheme_id']=='n'

def test_shared_pdf_material_binding_and_page_validation(ctx):
    import pymupdf
    with pymupdf.open() as doc:
        doc.new_page().insert_text((60,100),'TEST MATERIAL');doc.save(ctx.root/'material.pdf')
    material={'id':'m','scheme_id':'n','route_geometry_hash':'h','path':'material.pdf','caption':'测试素材',
              'approved':True,'fact_ids':['E'],'event_id':'n_CROSS_001'}
    config={'materials':[material]}
    for target in ('description','comparison','compliance'):
        result=approved_materials(config,ctx.root,ctx.facts,ctx.output,target,[{'event_id':'n_CROSS_001'}])
        assert len(result)==1 and result[0]['sha256'] and Path(result[0]['path']).is_file()
    material['pages']=[2]
    with pytest.raises(ValueError,match='页码越界'):approved_materials(config,ctx.root,ctx.facts,ctx.output,'description')
    material['route_geometry_hash']='old'
    with pytest.raises(ValueError,match='geometry_hash'):approved_materials(config,ctx.root,ctx.facts,ctx.output,'description')

def feature(identifier='a',**kwargs):
    return {'id':identifier,'name':'乡道','shape_type':'line','geometry':[[0,0],[10,0]],'layer_kind':'primary',
            'src_uid':identifier,'cross_rule':'allowed','tower_rule':'allowed',**kwargs}

def test_delta_delete_modify_add_and_runtime_rules(tmp_path):
    data={'features':[feature('a'),feature('b')],'features_lazy':False}
    with gzip.open(tmp_path/'map.raw.json.gz','wt') as f:json.dump(data,f)
    catalog=SimpleNamespace(features=[{'uid':'a','name':'原道路'},{'uid':'b'}],runtime_rules={},crs='EPSG:4548',provenance={})
    delta={'deleted_ids':['a'],'modified_features':[feature('b',cross_rule='forbidden')],
           'added_features':[feature('c',tower_rule='forbidden',buffer_range=3)]}
    apply_snapshot(catalog,{'report_adjustments':delta},tmp_path)
    assert {f['uid'] for f in catalog.features}=={'b','c'}
    assert catalog.features[0]['runtime_rule']['cross_rule']=='forbidden'
    assert len(catalog.constraint_frames['forbidden_polygons'])==1
    assert catalog.constraint_frames['no_tower_polygons'].geometry.iloc[0].area>0
    assert catalog.provenance['adjustments_sha256']==digest(delta)
    with pytest.raises(ValueError,match='版本不一致'):
        bind_snapshot({},[{'map_auxiliary':{'feature_adjustments':delta}},{}])
    delta['deleted_ids']=['missing']
    with pytest.raises(ValueError,match='删除地物ID'):apply_snapshot(catalog,{'report_adjustments':delta},tmp_path)
    moved={'modified_features':[feature('b',geometry=[[5,-5],[5,5]])]}
    with pytest.raises(ValueError,match='M1编辑仅更新规则'):apply_snapshot(catalog,{'report_adjustments':moved},tmp_path)

def test_service_queue_cancel_validation_and_download_sandbox(tmp_path,monkeypatch):
    seed=tmp_path/'seed';seed.mkdir()
    for sid in ('n','s'):
        (seed/sid).mkdir();write_json(seed/sid/'request.json',{});write_json(seed/sid/'response.json',{})
    config={'output_dir':str(seed),'start':[0,0],'end':[100,0],'schemes':[{'id':'n'},{'id':'s'}],
            'agents':{},'llm':{},'vlm':{}}
    write_json(tmp_path/'config.json',config)
    app=create_app(tmp_path/'config.json',tmp_path/'jobs');manager=app.extensions['reports']
    monkeypatch.setattr(manager.pool,'submit',lambda *a:None)
    client=app.test_client()
    assert client.post('/api/reports',json={'start':[1]}).status_code==400
    assert client.post('/api/reports',json={},headers={'Origin':'http://evil.test'}).status_code==403
    result=client.post('/api/reports',json={});assert result.status_code==202
    jid=result.json['id'];assert client.get('/api/reports/'+jid).json['status']=='queued'
    assert client.post('/api/reports/'+jid+'/cancel').json['status']=='cancelled'
    assert client.get('/api/reports/'+jid+'/files/../config.json').status_code==403
    assert client.get('/api/reports/not-a-uuid').status_code==400
    manager.pool.shutdown()


def test_lazy_map_fetches_all_features_and_rejects_capped_snapshot():
    from road_description.planner import PlannerClient,PlannerError
    client=PlannerClient('http://fake')
    answers=[{'status':'ok'},{'preprocess_mode':True,'geo_meta':{'working_crs':'EPSG:4548'},'features_lazy':True},
             {'total_in_view':2},{'features':[{'id':'a'},{'id':'b'}],'returned':2,'total_in_view':2,'capped':False}]
    client.call=lambda *a,**k:answers.pop(0)
    assert client.initialize()[1]['report_full_snapshot']
    answers.extend([{}, {'preprocess_mode':True,'geo_meta':{'x':1},'features_lazy':True},
                    {'total_in_view':2},{'returned':2,'total_in_view':3,'capped':True}])
    with pytest.raises(PlannerError,match='未完整'):client.initialize()


def test_description_keeps_nearby_repeat_crossings_and_distinguishes_touch(monkeypatch):
    import road_description.facts as module
    route=LineString([(0,0),(10,0),(10,10),(0,10)])
    feature={'uid':'road','src_fid':'0','geometry':LineString([(5,-1),(5,11)]),'category':'乡道',
             'county':'','village':'','name':'测试道路','label':'测试道路','name_source':'fixture','tunnel':''}
    cat=SimpleNamespace(nearby=lambda *a:[feature],rule=lambda f:{'cross_forbidden':False},bearing=lambda a,b:90)
    monkeypatch.setattr(module,'parallel_sections',lambda *a:[])
    facts=module.extract_facts({'path':list(route.coords),'analysis':{}},cat,{'start':[0,0]},'n')
    assert len(facts['events'])==2 and [e['start_m'] for e in facts['events']]==[5,25]
    feature['geometry']=LineString([(4,1),(5,0),(6,1)])
    facts=module.extract_facts({'path':[[0,0],[10,0]],'analysis':{}},cat,{'start':[0,0]},'n')
    assert facts['events'][0]['relation']=='contact'
