import geopandas as gpd
from shapely.geometry import LineString, box
from road_description.administration import measure_level


def test_return_visits_overlap_gaps_and_point_contacts():
    areas = gpd.GeoDataFrame({'label':['A','B','C']}, geometry=[box(0,-1,3,1),box(2,-1,4,1),box(5,0,6,2)])
    result = measure_level(LineString([(0,0),(5,0),(0,0)]),areas)
    assert [(r['end_m'],r['labels']) for r in result['runs']]==[(2,['A']),(3,['A','B']),(4,['B']),(6,[]),(7,['B']),(8,['A','B']),(10,['A'])]
    assert result['unresolved_m']==4 and not result['complete']


def test_path_coincident_with_boundary_has_no_unique_interior():
    areas=gpd.GeoDataFrame({'label':['A']},geometry=[box(0,0,5,1)])
    result=measure_level(LineString([(0,0),(5,0)]),areas)
    assert result['unresolved_m']==5
