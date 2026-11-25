import io
import json
from unittest.mock import Mock

from road_description.service import create_app


def kml(points):
    coords=' '.join(f'{x},{y},0' for x,y in points)
    return io.BytesIO(f'<kml><Placemark><LineString><coordinates>{coords}</coordinates></LineString></Placemark></kml>'.encode())


def test_import_pair_stages_only_its_own_evidence(tmp_path):
    seed=tmp_path/'seed'
    seed.mkdir()
    (seed/'map.json').write_text(json.dumps({'geo_meta':{'working_crs':'EPSG:3857','offset':[0,0]},
        'planning_bounds':[[-100,-100],[2000,-100],[2000,1000],[-100,1000]]}))
    (seed/'map.raw.json.gz').write_bytes(b'snapshot')
    config=tmp_path/'config.json'
    config.write_text(json.dumps({'output_dir':'seed','route_source':'kml','start':[0,0],'agents':{
        'assembly':{'section_notes':'prior-case.json'}}}))
    app=create_app(config,tmp_path/'jobs')
    queue=Mock()
    app.extensions['reports'].pool.submit=queue
    client=app.test_client()
    north=[(0,0),(.005,.004),(.012,0)]
    south=[(.012,0),(.005,.001),(0,0)]
    def submit(a,b):
        return client.post('/api/kml-jobs',data={'upper':(kml(a),'n.kml'),'lower':(kml(b),'s.kml')})
    assert submit(south,north).status_code==400
    assert not list((tmp_path/'jobs').iterdir())
    result=submit(north,south)
    assert result.status_code==202
    job=result.json['id']
    folder=tmp_path/'jobs'/job
    queued=json.loads((folder/'config.json').read_text())
    assert queued['start']==[0,0] and queued['end'][0]>1300
    assert 'section_notes' not in queued['agents']['assembly']
    for side in ('upper','lower'):
        metadata=json.loads((folder/'output'/side/'request.json').read_text())
        assert metadata['start_x']==0 and metadata['end_x']>1300
    recent = client.get('/api/kml-jobs/recent').json
    assert recent['ids']==[job]
    assert recent['jobs'][0]['title']==queued['project_title']
    assert recent['jobs'][0]['created_at'] and not recent['jobs'][0]['has_report']
    state=client.get('/api/kml-jobs/'+job).json
    assert state['status']=='queued' and all(not files for files in state['groups'].values())
    queue.assert_called_once()


def test_current_report_links_only_move_to_a_complete_delivery(tmp_path):
    from road_description.report_files import GROUPS, publish_workbench_files

    jobs = tmp_path/'workbench_jobs'
    job = jobs/'first'
    for plugin, stems in GROUPS.values():
        result = job/'output'/'agents'/plugin/'result.json'
        result.parent.mkdir(parents=True, exist_ok=True)
        result.write_text('{}')
        for stem in stems:
            for ext in ('.docx', '.pdf'):
                path = job/'output'/(stem+ext)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.touch()
    assert publish_workbench_files(job)
    assert publish_workbench_files(job)
    shortcut = tmp_path/'最近成稿'
    assert len(list(shortcut.iterdir())) == 10
    assert (shortcut/'完整报告.pdf').resolve().name.startswith('完整报告_')
    assert not publish_workbench_files(jobs/'incomplete')
    assert shortcut.resolve() == job/'成稿'
