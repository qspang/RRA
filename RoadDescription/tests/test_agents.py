from pathlib import Path
from types import SimpleNamespace

import geopandas as gpd
import pytest
from shapely.geometry import LineString, Polygon

from road_description.io import digest
from report_agents.common.context import AgentContext
from report_agents.common.gis import crossings, crossing_angle, overlap_length, building_screen, layer_checks, ecology_relations
from report_agents.common.supplement import agreements, survey
from report_agents.common.report import organise
from report_agents.route_comparison.agent import comparable_cost
from report_agents.route_compliance.agent import confirmed_designs
from report_agents.registry import agent_ids, create_agent, register_agent


def feature(uid, geometry, name='已知线路', category='输电线路500kV'):
    return dict(uid=uid,geometry=geometry,name=name,category=category,label=name or category,
                name_source='test' if name else '',tunnel='')


def catalog(features, minimum=45):
    return SimpleNamespace(features=features,nearby=lambda g,*a:[f for f in features if f['geometry'].intersects(g.buffer(a[0]) if a and a[0] else g)],
                           rule=lambda f:{'min_cross_angle':minimum})


@pytest.fixture
def context(tmp_path):
    route=[[0,0],[100,0]]
    geom_hash=digest(route)
    return AgentContext(config={'agents':{},'llm':{'enabled':False}},root=tmp_path,source=tmp_path,
                        output=tmp_path/'out',catalog=None,
                        facts={'schemes':[{'id':'n','geometry_hash':geom_hash,'path':route}]},
                        responses={},schemes={},provenance={})


def bind(context, data):
    context.supplement={'schemes':{'n':{'route_geometry_hash':context.facts['schemes'][0]['geometry_hash'],**data}}}


def source_record(context, **kwargs):
    (context.root/'source.txt').write_text('人工核实的资料')
    return {'confirmed':True,'source_file':'source.txt',**kwargs}


def test_crossing_keeps_repeat_visits_but_merges_same_named_fragments():
    route=LineString([(0,0),(10,0),(10,10),(0,10)])
    cat=catalog([feature('a',LineString([(5,-1),(5,5)])),feature('b',LineString([(5,5),(5,11)]))])
    hits=crossings(route,cat)
    assert len(hits)==2
    assert [h['start_m'] for h in hits]==[5,25]
    assert all(h['angle_deg']==90 and h['angle_status']=='pass' for h in hits)


def test_tangent_and_overlap_do_not_count_as_crossings():
    route=LineString([(0,0),(10,0)])
    cat=catalog([feature('touch',LineString([(4,3),(5,0),(6,3)]),name='接触'),
                 feature('overlap',LineString([(7,0),(9,0)]),name='重叠')])
    assert crossings(route,cat)==[]
    assert {x['relation'] for x in crossings(route,cat,True)}=={'contact','overlap'}


def test_unnamed_features_not_merged_and_no_fake_angle_for_polygon():
    route=LineString([(0,0),(10,0)])
    cat=catalog([feature('a',LineString([(2,-1),(2,1)]),name=''),
                 feature('b',LineString([(2.1,-1),(2.1,1)]),name='')])
    assert len(crossings(route,cat))==2
    assert crossing_angle(route,Polygon([(1,-1),(3,-1),(3,1),(1,1)]),2) is None


def test_angle_violation_is_not_suppressed():
    route=LineString([(0,0),(100,0)])
    cat=catalog([feature('a',LineString([(0,-10),(100,10)]))],minimum=45)
    hit=crossings(route,cat)[0]
    assert hit['angle_status']=='conflict' and hit['angle_deg']<12


def test_ecology_distinguishes_forbidden_transit_from_expensive_allowed_crossing():
    route=LineString([(0,0),(100,0)])
    features=[feature('forbidden',Polygon([(10,-5),(20,-5),(20,5),(10,5)]),category='自然保护区缓冲区'),
              feature('allowed',Polygon([(40,-5),(60,-5),(60,5),(40,5)]),category='一级水源保护区')]
    cat=catalog(features)
    cat.rule=lambda f:{'cross_forbidden':f['uid']=='forbidden','tower_forbidden':True,'cross_cost':5000}
    result=ecology_relations(route,cat,300)
    assert result[0]['geometry_status']=='conflict' and result[0]['inside_length_m']==10
    assert result[1]['geometry_status']=='review' and result[1]['inside_length_m']==20


def test_redline_union_and_buildings_are_not_double_counted():
    route=LineString([(0,0),(100,0)])
    shapes=[feature('a',Polygon([(0,-10),(60,-10),(60,10),(0,10)]),category='建筑物'),
            feature('b',Polygon([(40,-10),(100,-10),(100,10),(40,10)]),category='建筑物')]
    assert overlap_length(route,shapes)==100
    screen=building_screen(route,catalog(shapes),20)
    assert screen['polygon_overlap_m2']==2000
    assert screen['feature_count']==2
    assert '不是拆迁' in screen['meaning']


def test_missing_agreements_never_become_agreed(context):
    bind(context,{'agreements':[{'region':'某县','department':'林业局','status':'agreed','confirmed':True,
                               'source_file':'missing.pdf'}],
                  'required_departments':[{'region':'某县','department':'林业局'},{'region':'某县','department':'水务局'}]})
    value=agreements(context,'n')
    assert value['status']=='pending'
    assert len(value['records'])==2 and all(r['status']=='pending' for r in value['records'])


def test_conditional_reply_remains_conditional(context):
    record=source_record(context,region='某县',department='林业局',status='conditional',conditions='先核实林地占用')
    bind(context,{'agreements':[record],'required_departments':[{'region':'某县','department':'林业局'}]})
    result=agreements(context,'n')
    assert result['records'][0]['status']=='conditional'
    assert result['status']=='pending'
    record['status']='rejected'
    assert agreements(context,'n')['status']=='rejected'


def test_human_confirmed_survey_requires_real_source_and_nonnegative_quantity(context):
    bind(context,{'surveys':{'demolition':{'confirmed':True,'records':[{'kind':'棚','quantity':0,'unit':'m2'}]}}})
    assert survey(context,'n','demolition')['status']=='pending'
    record=source_record(context,records=[{'kind':'棚','quantity':120,'unit':'m2'}])
    bind(context,{'surveys':{'demolition':record}})
    assert survey(context,'n','demolition')['records'][0]['quantity']==120
    record['records'][0]['quantity']=-1
    with pytest.raises(ValueError):survey(context,'n','demolition')


def test_old_route_supplement_is_rejected(context):
    bind(context,{})
    context.supplement['schemes']['n']['route_geometry_hash']='stale'
    with pytest.raises(ValueError,match='route_geometry_hash'):context.supplied('n')


def test_crossing_design_must_reference_this_routes_features(context):
    bind(context,{'crossing_designs':[source_record(context,source_uids=['unrelated'],span_m=500)]})
    with pytest.raises(ValueError):confirmed_designs(context,{'id':'n'},[{'source_uids':['actual']}])


def test_same_object_repeated_crossing_needs_chainage_binding(context):
    record=source_record(context,source_uids=['actual'],span_m=500)
    bind(context,{'crossing_designs':[record]})
    events=[{'source_uids':['actual'],'start_m':10,'end_m':10},
            {'source_uids':['actual'],'start_m':50,'end_m':50}]
    with pytest.raises(ValueError,match='唯一关联'):confirmed_designs(context,{'id':'n'},events)
    record['chainage_m']=50
    assert confirmed_designs(context,{'id':'n'},events)[0]['crossing_start_m']==50


def test_statistical_towers_and_endpoint_exemption_are_not_full_pass(context):
    cat=SimpleNamespace(root=context.root)
    context.catalog=cat
    polygon=Polygon([(0,-1),(1,-1),(1,1),(0,1)])
    frame=gpd.GeoDataFrame([{'level2':'输电线路500kV','geometry':polygon}],crs='EPSG:4548')
    empty=gpd.GeoDataFrame({'level2':[],'geometry':[]},geometry='geometry',crs='EPSG:4548')
    (context.root/'m2').mkdir()
    for name,value in [('forbidden_polygons',empty),('no_tower_polygons',frame)]:
        (context.root/'m2'/f'{name}.gpkg').write_bytes(b'fixture')
        context.cache['layer_'+name]=value
    analysis={'towers':[{'id':'T1','x':0,'y':0,'type':'terminal'}],
              'tower_placement':{'mode':'statistical','straight_placement_checked':False}}
    checks=layer_checks(context,LineString([(0,0),(100,0)]),analysis)
    assert checks['no_tower_polygons']['status']=='review'
    assert not checks['no_tower_polygons']['complete']
    analysis['towers'][0]['type']='angle'
    assert layer_checks(context,LineString([(0,0),(100,0)]),analysis)['no_tower_polygons']['status']=='conflict'
    analysis['towers']=[]
    assert layer_checks(context,LineString([(0,0),(100,0)]),analysis)['no_tower_polygons']['status']=='partial'


def test_cost_ranking_requires_same_model_and_reference_scope(context):
    context.facts={'schemes':[{'id':'n'},{'id':'s'}]}
    for sid in ('n','s'):
        context.responses[sid]={'params':{},'dem_loaded':False}
        context.schemes[sid]={'analysis':{'total_cost':100,'cost_model_version':'v1',
            'engineering_evaluation':{'version':'v1','scope':'fixed','cell_size_m':25,'independent_of_search_resolution':True}}}
    assert comparable_cost(context)
    context.schemes['s']['analysis']['cost_model_version']='v2'
    assert not comparable_cost(context)


def test_model_cannot_invent_approval(context,monkeypatch):
    context.config['llm']={'enabled':True,'model_id':'fake'}
    monkeypatch.setattr('report_agents.common.report.model_call',lambda *a:({'paragraphs':[[{'id':'已批准'}]]},{}))
    paragraphs,mode=organise(context,'route_compliance',['停电方案待补。'])
    assert paragraphs[0]['text']=='停电方案待补。'
    assert mode['mode']=='deterministic_after_model_failure'


def test_agents_load_independently_and_do_not_require_each_other():
    assert set(agent_ids())=={'route_description','route_comparison','route_compliance'}
    for identifier in agent_ids():
        assert create_agent(identifier).manifest['depends_on']==[]
    with pytest.raises(ValueError):register_agent('route_comparison','other:Agent')
    with pytest.raises(ValueError):create_agent('missing')
