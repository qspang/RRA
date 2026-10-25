import math
import pytest
from shapely.geometry import LineString, Polygon
from road_description.facts import (official_name,county_name,intersection_events,
    pair_schemes,canonical_path,compass,parallel_sections,route_segments)
from road_description.planner import select_scheme,PlannerError
from road_description.narrative import validate_selection


def test_name_priority_and_reject_numeric_placeholder():
    assert official_name({'std_level2':'自然保护区缓冲区','attr_Name':'2010'})==('','')
    assert official_name({'std_level2':'生态保护红线一般区域','attr_ZRBHDMC':'阴那山自然保护区'})[0]=='阴那山自然保护区'
    assert official_name({'attr_src_uid':'x'}, {'x':'确认名称'})==('确认名称','name_overrides:x')


def test_parcel_attribution_not_village_as_county():
    assert county_name({'attr_所属区p':'441402梅江区','attr_XZQMC':'鲤溪村'})[0]=='梅江区'
    assert county_name({'attr_XZQMC':'鲤溪村'})==('','')


def test_two_crossings_same_feature_stay_separate():
    route=LineString([(0,0),(10,0),(10,10),(0,10)])
    events=intersection_events(route,LineString([(5,-1),(5,11)]))
    assert [e[0] for e in events]==[5,25]


def test_polygon_hole_is_not_inside():
    polygon=Polygon([(0,0),(10,0),(10,10),(0,10)],holes=[[(4,4),(6,4),(6,6),(4,6)]])
    route=LineString([(-1,5),(11,5)])
    events=intersection_events(route,polygon)
    assert len(events)==2
    assert sum(hi-lo for lo,hi,_ in events)==8


def test_polygon_tangent_is_not_crossing():
    polygon=Polygon([(0,0),(2,0),(2,2),(0,2)])
    assert intersection_events(LineString([(-1,1),(1,3)]),polygon)==[]


def test_north_south_sorting_and_no_duplicate_scheme():
    north={'id':'n','path':[[0,0],[50,100],[100,0]]}
    south={'id':'s','path':[[0,0],[50,-100],[100,0]]}
    items=[south,north];pair_schemes(items,tolerance=5)
    assert [x['id'] for x in items]==['n','s']
    assert items[0]['name']=='北方案'
    with pytest.raises(ValueError):pair_schemes([north,dict(north)],tolerance=5)


def test_orientation_and_length_consistency():
    s={'analysis':{'simplified_waypoints':[[3,4],[0,0]],'total_length':5}}
    route=canonical_path(s,[0,0]);assert list(route.coords)[0]==(0,0)
    s['analysis']['total_length']=10
    with pytest.raises(ValueError):canonical_path(s)


def test_only_final_feasible_results():
    good={'feasible':True,'analysis':{'validations':{'feasible':True},'total_cost':100}}
    assert select_scheme({'schemes':[good]}) is good
    for d in [{'schemes':[]},{'schemes':[good],'coarse_review_pending':True},
              {'schemes':[dict(good,partial_feasible=True)]}]:
        with pytest.raises(PlannerError):select_scheme(d)


def test_model_cannot_add_numbers_names_or_reorder():
    entries=[{'id':'a','text':'向西走线2km。','fact_ids':['a']},
             {'id':'b','text':'跨越某河。','fact_ids':['b']}]
    out=validate_selection({'paragraphs':[[{'id':'a'},{'id':'b','connector':'随后，'}]]},entries)
    assert out[0]['text']=='向西走线2km。随后，跨越某河。'
    for group in [[{'id':'b'},{'id':'a'}],[{'id':'a','connector':'经过韩江，'},{'id':'b'}],
                  [{'id':'a'},{'id':'unknown'}]]:
        with pytest.raises(ValueError):validate_selection({'paragraphs':[group]},entries)


def test_compass_wraparound():
    assert compass(359)=='北'
    assert compass(270)=='西'


def test_parallel_uses_actual_direction_not_nearness_alone():
    from types import SimpleNamespace
    route=LineString([(0,0),(2000,0)])
    features=[{'uid':'parallel','category':'输电线路220kV','geometry':LineString([(0,100),(2000,100)]),
               'label':'220kV 已知线路','name_source':'test'},
              {'uid':'crossing','category':'输电线路220kV','geometry':LineString([(1000,-1000),(1000,1000)]),
               'label':'220kV 垂直线路','name_source':'test'}]
    cat=SimpleNamespace(nearby=lambda *args:features,rule=lambda f:{})
    runs=parallel_sections(route,cat)
    assert len(runs)==1 and runs[0]['feature_uid']=='parallel' and runs[0]['length_m']==2000


def test_segments_follow_turns_and_conserve_length():
    from types import SimpleNamespace
    route=LineString([(0,0),(1000,0),(1000,3000)])
    cat=SimpleNamespace(bearing=lambda a,b:math.degrees(math.atan2(b[0]-a[0],b[1]-a[1]))%360)
    segments=route_segments(route,cat)
    assert [s['direction'] for s in segments]==['东','北']
    assert sum(s['length_m'] for s in segments)==4000


def test_self_intersecting_route_is_rejected():
    s={'analysis':{'simplified_waypoints':[[0,0],[10,10],[0,10],[10,0]]}}
    with pytest.raises(ValueError):canonical_path(s)
