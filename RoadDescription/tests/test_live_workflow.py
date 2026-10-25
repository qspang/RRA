import json
import math
from pathlib import Path
import threading
import time

import pytest
from shapely.geometry import LineString

from road_description.automatic_routes import corridor_points,choose_pair,generate_two_routes
from road_description.io import read_json,write_json
from road_description.model_runtime import credential,decode_json,model_call,parallel_map,prepare_model_config,telemetry


def test_corridors_are_derived_from_endpoints_on_opposite_sides():
    points=list(corridor_points([0,0],[2000,0],[.1],100))
    assert points[0]['point']==[1000,200]
    assert points[3]['point']==[1000,-200]
    with pytest.raises(ValueError):list(corridor_points([0,0],[10,0]))


def candidate(points,cost=100):
    return {'line':LineString(points),'scheme':{'analysis':{'total_cost':cost}}}


def test_route_pair_rejects_duplicates_and_single_spike():
    a=candidate([[0,0],[1000,0]])
    assert choose_pair([a,a],100) is None
    spike=candidate([[0,0],[5,0],[6,200],[7,0],[1000,0]])
    assert choose_pair([a,spike],100) is None
    b=candidate([[0,0],[500,250],[1000,0]])
    assert choose_pair([a,b],100) is not None


def test_automatic_generation_archives_real_selected_responses_and_keeps_original_config(tmp_path,monkeypatch):
    config={'planner_url':'http://fake','start':[0,0],'end':[2000,0],'dataset':'dataset','output_dir':'output',
            'schemes':[],'request':{},'route_generation':{'enabled':True,'offset_fractions':[.12],
            'min_separation_m':150,'maximum_length_ratio':2},'llm':{'model_id':'before'}}
    path=tmp_path/'config.json';write_json(path,config);original=path.read_bytes()
    class Client:
        count=0
        def __init__(self,*a):pass
        def initialize(self):return {},{'geo_meta':{'working_crs':'EPSG:4548','offset':[0,0]}}
        def validate(self,*a):return {'valid':True}
        def plan(self,payload,folder,**kwargs):
            Client.count+=1
            p=payload['must_pass_points'][0]
            points=[[0,0],[p['x'],p['y']],[2000,0]]
            result={'schemes':[{'id':'winner','feasible':True,'path':points,
                    'analysis':{'total_length':LineString(points).length,'total_cost':100,
                                'validations':{'feasible':True}}}], 'plan_run_id':'fake_'+str(Client.count)}
            write_json(folder/'request.json',payload);write_json(folder/'response.json',result)
            return result
    monkeypatch.setattr('road_description.automatic_routes.PlannerClient',Client)
    resolved=generate_two_routes(path)
    assert path.read_bytes()==original and Client.count==2
    r=read_json(resolved);assert [s['id'] for s in r['schemes']]==['upper','lower']
    for sid in ('upper','lower'):
        response=read_json(tmp_path/'output'/sid/'response.json')
        assert response['report_selection']['source_sha256']
        assert response['plan_run_id'].startswith('fake_')
    config['llm']['model_id']='new';write_json(path,config)
    assert read_json(generate_two_routes(path))['llm']['model_id']=='new'
    assert Client.count==2


def test_credential_file_is_explicit_and_does_not_replace_other_keys(tmp_path,monkeypatch):
    path=tmp_path/'provider.env';path.write_text('PROVIDER_TEST_KEY=private-test-value\n')
    cfg={'llm':{'credential_file':'provider.env','api_key_env':'PROVIDER_TEST_KEY'}}
    monkeypatch.setenv('ROAD_LLM_API_KEY','original-key')
    prepare_model_config(cfg,tmp_path)
    assert credential(cfg['llm'])=='private-test-value'
    import os
    assert os.environ['ROAD_LLM_API_KEY']=='original-key'
    monkeypatch.setenv('PROVIDER_TEST_KEY','override-key')
    assert credential(cfg['llm'])=='override-key'


def test_model_json_handles_fence_and_text_blocks_without_accepting_prose():
    assert decode_json('```json\n{"ok":true}\n```')=={'ok':True}
    assert decode_json([{'type':'text','text':'{"ok":true}'}])=={'ok':True}
    assert decode_json('结果如下：\n{"ok":true}\n以上为JSON。')=={'ok':True}
    with pytest.raises(ValueError):decode_json('已批准')
    with pytest.raises(ValueError):decode_json('[1,2]')


def test_model_retries_invalid_ids_and_does_not_duplicate_connectors():
    from road_description.narrative import model_selection,validate_selection
    entries=[{'id':'s1','text':'随后向西走线2km。','fact_ids':['s1']}]
    calls=[]
    def call(config,messages):
        calls.append(messages)
        return ({'paragraphs':[[{'id':'invented' if len(calls)==1 else 's1','connector':''}]]},{'total_tokens':1})
    paragraphs,usage,attempts=model_selection({},[],entries,call=call)
    assert paragraphs[0]['text']=='随后向西走线2km。'
    assert len(calls)==2 and attempts[0]['status']=='rejected' and attempts[1]['status']=='accepted'
    selected=validate_selection({'paragraphs':[[{'id':'s1','connector':'随后，'}]]},entries)
    assert selected[0]['text']=='随后向西走线2km。'


def test_invalid_json_retried_and_recorded_without_exposing_key(monkeypatch):
    monkeypatch.setenv('INVALID_JSON_KEY','sk-private-test-value')
    seen=[]
    class Response:
        status_code=200;ok=True
        def json(self):return {'choices':[{'message':{'content':'sk-private-test-value bad JSON' if len(seen)==1 else '{"ok":true}'}}]}
    def post(*args,**kwargs):seen.append(kwargs['json']);return Response()
    monkeypatch.setattr('road_description.model_runtime.requests.post',post)
    assert model_call({'enabled':True,'model_id':'test','api_base':'http://invalid-json-test',
                       'api_key_env':'INVALID_JSON_KEY'},[])[0]['ok']
    assert len(seen)==2
    event=telemetry()['calls'][-1]
    assert event['format_failures'] and 'sk-private-test-value' not in json.dumps(event)


def test_transport_concurrency_limit_and_retry_without_secret_in_telemetry(monkeypatch):
    monkeypatch.setenv('CONCURRENCY_TEST_KEY','secret-do-not-log')
    lock=threading.Lock();active=0;peak=0
    class Response:
        status_code=200;ok=True
        def json(self):return {'model':'test','choices':[{'message':{'content':'{"ok":true}'}}]}
    def post(*a,**kw):
        nonlocal active,peak
        with lock:active+=1;peak=max(peak,active)
        time.sleep(.03)
        with lock:active-=1
        return Response()
    monkeypatch.setattr('road_description.model_runtime.requests.post',post)
    config={'enabled':True,'api_base':'http://concurrency-test/v1','model_id':'test',
            'api_key_env':'CONCURRENCY_TEST_KEY','max_concurrency':3}
    results=parallel_map(lambda i:model_call(config,[{'role':'user','content':str(i)}]),range(9),15)
    assert len(results)==9 and peak==3
    assert 'secret-do-not-log' not in json.dumps(telemetry())
    with pytest.raises(ValueError):model_call(dict(config,max_concurrency=16),[])


def test_json_mode_unsupported_retries_without_changing_model(monkeypatch):
    monkeypatch.setenv('FALLBACK_TEST_KEY','fake')
    requests=[]
    class Response:
        def __init__(self,status):self.status_code=status;self.ok=status==200
        def json(self):return {'choices':[{'message':{'content':'{"ok":true}'}}]}
    def post(*a,**kw):
        requests.append(dict(kw['json']))
        return Response(400 if len(requests)==1 else 200)
    monkeypatch.setattr('road_description.model_runtime.requests.post',post)
    config={'enabled':True,'api_base':'http://fallback-test/v1','model_id':'same-model','api_key_env':'FALLBACK_TEST_KEY'}
    assert model_call(config,[])[0]['ok']
    assert 'response_format' in requests[0] and 'response_format' not in requests[1]
    assert all(r['model']=='same-model' for r in requests)
