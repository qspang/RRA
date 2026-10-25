from types import SimpleNamespace
import geopandas as gpd
from shapely.geometry import LineString
from road_description.source_layers import attach_layers
from report_agents.common.coverage import inventory, scope_text


def test_coverage_distinguishes_missing_layers_distance_and_missing_name():
    catalog=SimpleNamespace(features=[{'uid':'r','category':'乡道','name':'','label':'乡道','geometry':LineString([(5,-1),(5,1)])},
        {'uid':'e','category':'生态保护红线','name':'保护范围','label':'保护范围','geometry':LineString([(0,3000),(10,3000)])}])
    values={x['type']:x for x in inventory(catalog,[{'id':'n','path':[(0,0),(10,0)]}],1000)}
    assert '未提供该专题图层' in scope_text(values['矿区'],'n')
    assert '3.00km' in scope_text(values['生态敏感点'],'n')
    assert '未提供专名' in scope_text(values['普通道路'],'n')
    assert values['普通道路']['schemes']['n']['intersecting_features']==1


def test_supplemental_layer_uses_crs_offset_and_does_not_invent_rule(tmp_path):
    source=tmp_path/'roads.gpkg'
    gpd.GeoDataFrame({'Name':['测试道路'],'geometry':[LineString([(420010,2684000),(420020,2684000)])]},crs=4548).to_file(source,layer='补充')
    c=SimpleNamespace(features=[],crs='EPSG:4548',offset=(-420000,-2684000),provenance={})
    spec=[{'path':str(source),'layer':'补充','category':'道路（补充，等级待核）'}]
    attach_layers(c,spec)
    assert c.features[0]['geometry'].bounds==(10,0,20,0)
    assert c.features[0]['rule_id'] is None
    assert c.features[0]['supplemental'] is True
    first=c.provenance['supplemental_layers_sha256']
    c.features=[];attach_layers(c,spec)
    assert c.provenance['supplemental_layers_sha256']==first


def test_two_page_reference_logo_does_not_require_original_chapter_pages(tmp_path):
    import pymupdf
    from road_description.document import extract_logo
    pdf=pymupdf.open();pdf.new_page();pdf.new_page();pdf.save(tmp_path/'reference.pdf');pdf.close()
    assert extract_logo(tmp_path/'reference.pdf',tmp_path/'logo') is None


def test_full_ecology_replaces_clipped_report_category_without_changing_planner_frames(tmp_path):
    source=tmp_path/'ecology.gpkg'
    gpd.GeoDataFrame({'HXMC':['完整生态范围'],'geometry':[LineString([(0,0),(10,0)])]},crs=4548).to_file(source,layer='生态')
    original={'category':'生态保护红线一般区域','geometry':LineString([(4,0),(5,0)])}
    constraints=object()
    c=SimpleNamespace(features=[original],crs='EPSG:4548',offset=(0,0),provenance={},constraint_frames=constraints)
    attach_layers(c,[{'path':str(source),'layer':'生态','category':'生态保护红线一般区域','replace_report_category':True}])
    assert len(c.features)==1 and c.features[0]['label']=='完整生态范围'
    assert c.features[0]['geometry'].length==10
    assert c.constraint_frames is constraints
    assert c.provenance['supplemental_layers'][0]['replaced_report_feature_count']==1
