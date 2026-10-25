from types import SimpleNamespace
from shapely.geometry import LineString,Polygon
from road_description.facts import village_name,tunnel_mark
from report_agents.common.gis import ecology_relations,crossings
from report_agents.common.environment import relief


def test_ecology_positive_intervals_and_located_tower_conflict():
    f={'uid':'eco1','category':'一级水源保护区','label':'测试水源','geometry':Polygon([(2,-2),(6,-2),(6,2),(2,2)])}
    catalog=SimpleNamespace(nearby=lambda *args:[f],rule=lambda f:{'cross_forbidden':False,'tower_forbidden':True})
    result=ecology_relations(LineString([(0,0),(10,0)]),catalog,300,[{'id':'T1','x':3,'y':0}],False)[0]
    assert result['inside_length_m']==4
    assert result['intervals']==[{'start_m':2.,'end_m':6.}]
    assert result['xy']==[4.,0.] and result['located_tower_ids']==['T1']
    assert result['geometry_status']=='conflict' and not result['tower_coverage_complete']


def test_same_named_tunnel_and_surface_segments_are_distinguished_at_each_crossing():
    features=[dict(uid=str(x),category='高速公路',name='测试高速',label='测试高速',name_source='name',
                   tunnel=mark,geometry=LineString([(x,-2),(x,2)])) for x,mark in [(3,'T'),(7,'F')]]
    catalog=SimpleNamespace(nearby=lambda *args:features,rule=lambda f:{'min_cross_angle':45})
    result=crossings(LineString([(0,0),(10,0)]),catalog)
    assert [r['tunnel_status'] for r in result]==['tunnel','surface']
    assert tunnel_mark('F') is False and tunnel_mark('unknown') is None


def test_village_comes_from_location_not_ownership():
    assert village_name({'attr_XZQMC':'梅县区','attr_ZLDWMC':'人和村','attr_QSDWMC':'另一村'})==('人和村','attr_ZLDWMC')
    assert village_name({'attr_QSDWMC':'另一村'})==('','')


def test_dem_relief_does_not_bridge_nodata():
    value=relief({'profile':[{'chainage_m':0,'height_m':10},{'chainage_m':10,'height_m':None},
                             {'chainage_m':20,'height_m':30},{'chainage_m':30,'height_m':20}]})
    assert value['ascent_m']==0 and value['descent_m']==10 and value['covered_m']==10


def test_supplemental_known_category_rule_is_retained_for_review(tmp_path):
    import geopandas as gpd
    from road_description.source_layers import attach_layers
    from road_description.facts import Catalog
    p=tmp_path/'source.gpkg'
    gpd.GeoDataFrame({'Name':['测试保护区'],'geometry':[Polygon([(0,0),(2,0),(2,2),(0,2)])]},crs=4548).to_file(p,layer='保护')
    c=SimpleNamespace(crs='EPSG:4548',offset=(0,0),features=[],provenance={},runtime_rules={},
        rules={3:{'rule_id':3,'level2':'自然保护区缓冲区','cross_allow':False,'is_landable':False}})
    attach_layers(c,[{'path':str(p),'layer':'保护','category':'自然保护区缓冲区'}])
    assert c.features[0]['rule_id']==3
    assert Catalog.rule(c,c.features[0])['cross_forbidden'] is True


def test_description_review_excludes_unrelated_compliance_verdicts():
    from road_description.quality_review import document_evidence
    evidence={'schemes':[{'id':'upper'}],'comparison':{'matrix':[]},
              'compliance':{'lower':{'status':'conflict_requires_review'}}}
    assert document_evidence(evidence,'description')=={'schemes':[{'id':'upper'}]}
    assert 'compliance' not in document_evidence(evidence,'route_comparison_0')
    assert document_evidence(evidence,'assembly_all')==evidence


def test_actual_crossing_conflict_is_disclosed_with_location():
    from report_agents.route_compliance.agent import crossing_conflict_note
    text=crossing_conflict_note(dict(angle_status='conflict',label='测试线',event_id='lower_CROSS_031',
                                   start_m=12635,angle_deg=44.919,minimum_angle_deg=45))
    assert '44.92°' in text and '45°' in text and 'K12.635' in text and '尚未满足' in text
    assert crossing_conflict_note({'angle_status':'pass'}) is None


def test_review_consistency_preserves_real_errors_and_original_opinion(monkeypatch):
    import road_description.quality_review as q
    raw={'verdict':'needs_review','issues':[{'severity':'blocking','description':'成稿准确，不构成错误'},
                                          {'severity':'blocking','description':'正文错误地声称无跨越'}]}
    monkeypatch.setattr(q,'model_call',lambda *args:({'decisions':[
        {'index':0,'classification':'self_contradictory','reason':'原意见称不构成错误'},
        {'index':1,'classification':'coherent','reason':'明确指出成稿错误'}]},{}))
    result,trace=q.check_review_consistency({},raw)
    assert result['verdict']=='needs_review' and len(result['issues'])==1
    assert trace['original_review']==raw and len(raw['issues'])==2
