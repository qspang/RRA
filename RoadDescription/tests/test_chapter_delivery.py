from types import SimpleNamespace
import requests
import pytest
from road_description.planner import PlannerClient, PlannerError
from road_description.narrative import candidates
from road_description.quality_review import collect_documents
from road_description.io import write_json


def test_every_crossing_is_retained_in_description_even_same_name():
    events=[{'fact_id':f'E{i}','label':'同一条道路','relation':'cross','start_m':i*10} for i in range(5)]
    facts={'id':'n','name':'北方案','events':events,'segments':[{'fact_id':'S','event_ids':[e['fact_id'] for e in events],
           'direction':'西','length_m':100}],'constraints':[],'counties':[],
           'metrics':{'length_m':100,'straight_distance_m':100,'tortuosity':1}}
    result=candidates(facts,{'start_name':'起点','end_name':'终点'})
    assert set(e['fact_id'] for e in events).issubset(result[0]['fact_ids'])
    assert result[0]['text'].count('同一条道路')==5


@pytest.mark.parametrize('failure',[requests.Timeout(),ValueError(),[]])
def test_planner_transport_and_json_errors_have_diagnostics(failure):
    client=PlannerClient('http://fixture')
    def request(*a,**k):
        if isinstance(failure,requests.Timeout):raise failure
        def decode():
            if isinstance(failure,ValueError):raise failure
            return failure
        return SimpleNamespace(ok=True,status_code=200,json=decode)
    client.session.request=request
    with pytest.raises(PlannerError):client.call('GET','/api/health')
    assert client.last_failure['error_type'] in ('Timeout','InvalidJSON','InvalidShape')


def test_registering_description_does_not_double_count_document_review(tmp_path):
    doc=tmp_path/'路径方案描述_联调样章.docx'
    result=tmp_path/'agents/route_description/result.json'
    write_json(result,{'agent':{'sections':['3.3.1','3.3.2']}})
    write_json(tmp_path/'agents/agent_run.json',{'results':{'route_description':{
        'result_json':str(result),'documents':[{'docx':str(doc)}]}}})
    assert len(collect_documents(tmp_path))==1


def test_dem_profile_preserves_station_and_nodata_instead_of_bridging_gap(tmp_path):
    import numpy as np
    import rasterio
    from rasterio.transform import from_origin
    from shapely.geometry import LineString
    from report_agents.common.gis import elevation
    path=tmp_path/'dem.tif'
    with rasterio.open(path,'w',driver='GTiff',width=4,height=1,count=1,dtype='float32',
                       crs='EPSG:4548',transform=from_origin(100,110,10,10),nodata=-9999) as ds:
        ds.write(np.array([[10,-9999,30,40]],dtype='float32'),1)
    ctx=SimpleNamespace(options={'dem_path':str(path),'elevation_step_m':10},root=tmp_path,cache={},
                        catalog=SimpleNamespace(crs='EPSG:4548',offset=[-100,-100]))
    result=elevation(ctx,LineString([(5,5),(35,5)]))
    assert result['status']=='partial' and result['valid_samples']==3
    assert result['profile']==[{'chainage_m':0.,'height_m':10.},{'chainage_m':10.,'height_m':None},
                               {'chainage_m':20.,'height_m':30.},{'chainage_m':30.,'height_m':40.}]
    assert result['min_m']==10 and result['max_m']==40 and result['sha256']


def test_partial_crossing_design_does_not_hide_remaining_requirements():
    from report_agents.route_compliance.agent import design_text,design_missing
    design={'status':'confirmed_input','input':{'span_m':500}}
    assert set(design_missing(design))=={'跨越方式（塔型排列）','耐张段长度','净空说明','导地线接头要求'}
    # The reference-facing report does not require an unprovided design angle.
    assert '设计交叉角' not in design_text(design)
    text=design_text(design)
    assert '500m' in text and '耐张段长度' in text and '净空' in text and '待设计资料确认' in text


def test_report_page_with_only_header_and_footer_is_empty():
    import pymupdf
    from road_description.quality_review import empty_body_pages
    pdf=pymupdf.open()
    page=pdf.new_page(width=595,height=842)
    page.insert_text((70,45),'Header');page.insert_text((290,800),'37')
    assert empty_body_pages(pdf)==[1]
    page.insert_text((70,120),'Report body')
    assert empty_body_pages(pdf)==[]
    pdf.close()
