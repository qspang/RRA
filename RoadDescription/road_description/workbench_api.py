"""Import two supplied engineering routes into an isolated report job."""
import copy
from functools import lru_cache
from pathlib import Path
import shutil
import uuid
from xml.etree.ElementTree import ParseError

from flask import abort, jsonify, request, send_from_directory
from shapely.geometry import LineString, Polygon

from .facts import canonical_path, pair_schemes
from .io import file_hash, read_json, write_json
from .planner import report_scheme

GROUPS = {
    'description': ('route_description', ['路径方案描述_联调样章']),
    'comparison': ('route_comparison', ['agents/route_comparison/路径方案比选']),
    'compliance': ('route_compliance', ['agents/route_compliance/upper/北方案_路径合规性分析',
                                       'agents/route_compliance/lower/南方案_路径合规性分析']),
    'assembly': ('assembly', ['agents/assembly/完整报告_路径描述_方案比选_南北方案合规分析']),
}


def submit_pair(manager):
    config = copy.deepcopy(manager.base)
    seed = Path(config['output_dir'])
    snapshot = read_json(seed/'map.json')
    jid = uuid.uuid4().hex
    folder = manager.folder(jid)
    out = folder/'output'
    out.mkdir(parents=True)
    try:
        routes = []
        config['route_source'] = 'kml'
        config['header_title'] = '输电线路候选路径报告'
        identical = manager.base.get('route_source') == 'kml'
        for sid, name in [('upper', '北方案'), ('lower', '南方案')]:
            upload = request.files.get(sid)
            if upload is None or not upload.filename.lower().endswith('.kml'):
                raise ValueError('请分别选择南、北方案 KML 文件')
            target = out/sid
            target.mkdir()
            path = target/(name+'.kml')
            body = upload.read()
            if len(body) > 2*1024*1024 or not body:
                raise ValueError('每条路线文件须为非空 KML，最大 2 MB')
            path.write_bytes(body)
            record = dict(input_type='supplied_kml', source=str(path), sha256=file_hash(path))
            try:
                scheme = report_scheme(record, config, folder, snapshot)
                if len(scheme['path']) > 10000:
                    raise ValueError('每条路线最多支持一万个顶点')
                route = canonical_path(scheme, config.get('start') if sid=='upper' else routes[0]['path'][0])
            except (ParseError, IndexError, TypeError, OverflowError) as exc:
                raise ValueError('无法解析路线，请检查 KML 中 LineString 的经纬度') from exc
            if not Polygon(snapshot['planning_bounds']).covers(route):
                raise ValueError(name+'超出当前工程规划地图范围')
            routes.append(dict(id=sid,path=list(route.coords)))
            write_json(target/'response.json',record)
            write_json(target/'request.json',{'source':str(path),'start_x':route.coords[0][0],'start_y':route.coords[0][1],
                                             'end_x':route.coords[-1][0],'end_y':route.coords[-1][1]})
            original = seed/sid/'response.json'
            identical = identical and original.exists() and read_json(original).get('sha256') == record['sha256']
        north = routes[0]
        pair_schemes(routes)
        if routes[0]['id'] != 'upper':
            raise ValueError('北方案位于南方案以南，请核对两个文件的选择顺序')
        config['schemes'] = [{'id':'upper'},{'id':'lower'}]
        config['start'],config['end'] = north['path'][0],north['path'][-1]
        config['route_generation'] = {'enabled':False}
        config['output_dir'] = str(out)
        agents = config['agents']
        agents.update(output_dir=str(out/'agents'),enabled=['route_description','route_comparison','route_compliance'])
        agents.setdefault('assembly',{}).update(enabled=True,scheme_id=None,include_candidate_books=False)
        config.pop('_resolved_supplement',None)
        if not identical:
            config.update(project_title='南北候选线路工程',start_name='线路起点',end_name='线路终点',photos=[],materials=[])
            agents['supplemental_file']=None
            agents['assembly'].pop('section_notes',None)
        for name in ('map.json','map.raw.json.gz'):
            shutil.copy2(seed/name,out/name)
        if (seed/'tiles').is_dir():
            shutil.copytree(seed/'tiles',out/'tiles')
        write_json(folder/'config.json',config)
        write_json(folder/'job.json',dict(id=jid,status='queued',source='kml',title=config['project_title'],
            routes=[dict(id=r['id'],km=LineString(r['path']).length/1000) for r in routes]))
        manager.pool.submit(manager.run,jid)
    except Exception:
        shutil.rmtree(folder)
        raise
    return jid


@lru_cache(maxsize=64)
def result_preview(path, modified_ns, kind):
    data = read_json(path)
    if kind == 'description':
        return [[name, data[sid]['paragraphs'][0]['text'].split('。')[0]+'。']
                for sid,name in [('upper','北方案'),('lower','南方案')] if data.get(sid,{}).get('paragraphs')]
    if kind == 'comparison':
        fields = {'线路长度/km','海拔分布','穿越生态保护红线/km','重要交叉跨越'}
        return [row[:3] for row in data['matrix']['rows'] if row[0] in fields]
    if kind == 'compliance':
        return [[s['name'], '存在需复核冲突' if s['status']=='conflict_requires_review' else '资料待核',
                 '、'.join(c['topic'] for c in s['checks'] if c['status']=='conflict') or '详见章节报告',
                 '模型整理' if s['model']['mode']=='llm_constrained' else '依据核查事实生成']
                for s in data['schemes'].values()]
    return [dict(name=s['name'],km=round(s['metrics']['length_m']/1000,3),
                 counties=[item['name'] for item in s['counties']],tortuosity=round(s['metrics']['tortuosity'],3))
            for s in data['schemes']]


def register(app, manager):
    from .workbench_document import register_documents
    register_documents(app,manager,GROUPS)
    assets = Path(__file__).parent/'workbench'
    dist = Path(__file__).resolve().parents[1]/'frontend_integration/route-planning-agent/dist'

    @app.get('/workbench/')
    def workspace():
        if not (dist/'index.html').is_file():
            return '未安装 route-planning-agent 前端，请参阅 README。',503
        original = (dist/'index.html').read_text()
        if '/report-ui/routes.mjs' in original:
            return original
        html = original.replace('</head>', '<link rel="stylesheet" href="/report-ui/style.css"></head>')
        return html.replace('</body>','<script type="module" src="/report-ui/routes.mjs"></script></body>')

    @app.get('/workbench/<path:name>')
    def original_asset(name):
        return send_from_directory(dist,name)

    @app.get('/report-ui/<name>')
    def report_asset(name):
        return send_from_directory(assets,name)

    @app.get('/api/kml-jobs/recent')
    def recent():
        records = sorted(manager.root.glob('*/job.json'), key=lambda p:p.parent.stat().st_ctime_ns, reverse=True)
        return jsonify(ids=[p.parent.name for p in records if read_json(p).get('source')=='kml'][:30])

    @app.get('/api/kml-jobs/<jid>/map')
    def overview(jid):
        folder = manager.folder(jid)
        if read_json(folder/'job.json').get('source') != 'kml':
            abort(404)
        return send_from_directory(folder/'output/figures','overview.jpg')

    @app.post('/api/kml-jobs')
    def upload():
        return jsonify(id=submit_pair(manager)),202

    @app.get('/api/kml-jobs/<jid>')
    def state(jid):
        folder=manager.folder(jid)
        job=read_json(folder/'job.json')
        if job.get('source')!='kml':
            abort(404)
        out=folder/'output'
        progress=out/'report_job.json'
        active=out/'agents/agent_run.json'
        groups={}
        for key,(plugin,stems) in GROUPS.items():
            files=[]
            if (out/'agents'/plugin/'result.json').exists():
                for stem in stems:
                    for ext in ('.pdf','.docx'):
                        name=stem+ext
                        if (out/name).is_file():
                            files.append(name)
            groups[key]=files
        data=read_json(progress) if progress.exists() else {}
        previews={}
        for kind,name in [('description','narrative.json'),('comparison','agents/route_comparison/result.json'),
                          ('compliance','agents/route_compliance/result.json'),('summary','route_facts.json')]:
            path=out/name
            if path.is_file():
                previews[kind]=result_preview(path,path.stat().st_mtime_ns,kind)
        return jsonify(**job,summary=previews.pop('summary',[]),previews=previews,has_map=(out/'figure_manifest.json').is_file(),stage=data.get('stage'),error=data.get('error'),active=read_json(active).get('active') if active.exists() else None,groups=groups)
