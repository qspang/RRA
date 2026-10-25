"""Loopback report jobs: durable status, subprocess isolation, cancellation, downloads."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import copy
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import threading
import uuid
from flask import Flask,request,jsonify,send_file,abort
from .io import read_json,write_json, config_root


def absolute_config(config,root):
    config=copy.deepcopy(config)
    config['project_root']=str(root.resolve())
    for key in ('dataset','reference_pdf','admin_boundary','output_dir'):
        if config.get(key):config[key]=str((root/config[key]).resolve())
    if config.get('soffice') and '/' in config['soffice']:
        config['soffice']=str((root/config['soffice']).resolve())
    for section in ('llm','vlm'):
        if config.get(section,{}).get('credential_file'):
            config[section]['credential_file']=str((root/config[section]['credential_file']).resolve())
    agents=config.get('agents',{})
    for key in ('dem_path','planner_source','supplemental_file','output_dir'):
        if agents.get(key):agents[key]=str((root/agents[key]).resolve())
    for value in agents.values():
        if isinstance(value,dict) and value.get('llm',{}).get('credential_file'):
            value['llm']['credential_file']=str((root/value['llm']['credential_file']).resolve())
    for item in config.get('photos',[])+config.get('materials',[])+config.get('supplemental_layers',[]):item['path']=str((root/item['path']).resolve())
    # Supplemental source_file values are relative to its original config root.
    if agents.get('supplemental_file'):
        data=read_json(agents['supplemental_file'])
        def resolve(value):
            if isinstance(value,dict):
                return {k:str((root/v).resolve()) if k=='source_file' and v else resolve(v) for k,v in value.items()}
            if isinstance(value,list):return [resolve(v) for v in value]
            return value
        config['_resolved_supplement']=resolve(data)
    return config


class JobManager:
    def __init__(self,config_path,root):
        self.config_path=Path(config_path).resolve();self.base=absolute_config(read_json(self.config_path),config_root(self.config_path))
        self.root=Path(root).resolve();self.root.mkdir(parents=True,exist_ok=True)
        self.pool=ThreadPoolExecutor(max_workers=1);self.lock=threading.RLock();self.processes={}
        for path in self.root.glob('*/job.json'):
            state=read_json(path)
            if state['status'] in ('queued','running','cancelling'):
                state.update(status='interrupted',reason='服务重启，未冒称旧任务仍在运行');write_json(path,state)

    def folder(self,jid):
        try:
            if uuid.UUID(jid).hex!=jid:raise ValueError()
        except (ValueError,AttributeError):raise ValueError('任务ID无效')
        return self.root/jid

    def state(self,jid):
        folder=self.folder(jid);state=read_json(folder/'job.json')
        progress=folder/'output/report_job.json'
        if progress.exists():state['progress']=read_json(progress)
        artifacts=[]
        for path in (folder/'output').rglob('*'):
            if path.is_file() and path.suffix.lower() in ('.docx','.pdf','.txt'):
                artifacts.append({'name':str(path.relative_to(folder/'output')),'bytes':path.stat().st_size})
        state['artifacts']=artifacts;return state

    def submit(self,payload):
        if not isinstance(payload,dict) or set(payload)-{'start','end','replan'}:raise ValueError('仅接受start/end/replan')
        config=copy.deepcopy(self.base)
        import math
        for kind in ('start','end'):
            point=payload.get(kind,config.get(kind))
            if not isinstance(point,list) or len(point)!=2 or any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) for v in point):
                raise ValueError(kind+'必须为两个有限数值的本地地图坐标')
            config[kind]=point
        if config['start']==config['end']:raise ValueError('起终点不能相同')
        if 'replan' in payload and not isinstance(payload['replan'],bool):raise ValueError('replan须为布尔值')
        replan=payload.get('replan',False) or any(config[k]!=self.base[k] for k in ('start','end'))
        jid=uuid.uuid4().hex;folder=self.folder(jid);out=folder/'output';out.mkdir(parents=True)
        config['output_dir']=str(out);config.setdefault('agents',{})['output_dir']=str(out/'agents')
        if '_resolved_supplement' in config:
            write_json(folder/'supplement.json',config.pop('_resolved_supplement'))
            config['agents']['supplemental_file']=str(folder/'supplement.json')
        if replan:
            config['schemes']=[];config.setdefault('route_generation',{}).update(enabled=True,resolved=False)
        else:
            seed=Path(self.base['output_dir'])
            for name in ('map.json','map.raw.json.gz','health.json','route_generation.json'):
                if (seed/name).exists():shutil.copy2(seed/name,out/name)
            for scheme in config['schemes']:
                (out/scheme['id']).mkdir()
                for name in ('request.json','response.json'):shutil.copy2(seed/scheme['id']/name,out/scheme['id']/name)
        write_json(folder/'config.json',config)
        write_json(folder/'job.json',{'id':jid,'status':'queued','replan':replan})
        self.pool.submit(self.run,jid)
        return jid

    def run(self,jid):
        folder=self.folder(jid)
        with self.lock:
            state=read_json(folder/'job.json')
            if state['status']=='cancelled':return
            state['status']='running';write_json(folder/'job.json',state)
            stream=(folder/'output/workflow.log').open('w')
            try:
                process=subprocess.Popen([sys.executable,'-m','road_description','--config',str(folder/'config.json')],
                    cwd=Path(__file__).resolve().parents[1],stdout=stream,stderr=subprocess.STDOUT,start_new_session=True)
            except Exception as exc:
                stream.close();state.update(status='failed',error_type=type(exc).__name__);write_json(folder/'job.json',state);return
            self.processes[jid]=process
        code=process.wait();stream.close()
        with self.lock:
            self.processes.pop(jid,None);state=read_json(folder/'job.json')
            progress=read_json(folder/'output/report_job.json') if (folder/'output/report_job.json').exists() else {}
            state.update(exit_code=code,status='cancelled' if state['status']=='cancelling' else
                         'completed' if code==0 and progress.get('stage')=='completed' else 'review_required' if code==2 else 'failed')
            write_json(folder/'job.json',state)

    def cancel(self,jid):
        with self.lock:
            folder=self.folder(jid);state=read_json(folder/'job.json')
            if state['status']=='queued':state['status']='cancelled'
            elif state['status']=='running':
                state['status']='cancelling';process=self.processes.get(jid)
                if process and process.poll() is None:
                    os.killpg(process.pid,signal.SIGTERM)
                    def force():
                        if process.poll() is None:
                            try:os.killpg(process.pid,signal.SIGKILL)
                            except ProcessLookupError:pass
                    timer=threading.Timer(5,force);timer.daemon=True;timer.start()
            write_json(folder/'job.json',state)
        return state


def create_app(config_path,job_root):
    app=Flask(__name__);app.config['MAX_CONTENT_LENGTH']=16384
    manager=JobManager(config_path,job_root);app.extensions['reports']=manager
    @app.before_request
    def protect():
        if request.host.split(':')[0] not in ('127.0.0.1','localhost','[::1]'):abort(403)
        if request.method=='POST' and request.headers.get('Origin'):
            from urllib.parse import urlparse
            if urlparse(request.headers['Origin']).netloc!=request.host:abort(403)
    @app.errorhandler(ValueError)
    def invalid(exc):return jsonify(error=str(exc)),400
    @app.errorhandler(FileNotFoundError)
    def missing(exc):return jsonify(error='任务或文件不存在'),404
    @app.get('/api/health')
    def health():return jsonify(status='ok',job_workers=1,model_concurrency=15)
    @app.post('/api/reports')
    def submit():
        jid=manager.submit(request.get_json(silent=True));return jsonify(id=jid,status='queued'),202
    @app.get('/api/reports/<jid>')
    def status(jid):return jsonify(manager.state(jid))
    @app.post('/api/reports/<jid>/cancel')
    def cancel(jid):return jsonify(manager.cancel(jid))
    @app.get('/api/reports/<jid>/log')
    def log(jid):
        path=manager.folder(jid)/'output/workflow.log'
        return app.response_class(path.read_text(errors='replace')[-32000:] if path.exists() else '',mimetype='text/plain')
    @app.get('/api/reports/<jid>/files/<path:name>')
    def download(jid,name):
        root=manager.folder(jid)/'output';path=(root/name).resolve()
        if not path.is_relative_to(root) or path.suffix.lower() not in ('.docx','.pdf','.txt','.json','.csv','.png','.log','.jsonl'):abort(403)
        if not path.is_file():abort(404)
        return send_file(path,as_attachment=True)
    @app.get('/')
    def index():return (Path(__file__).parent/'service.html').read_text()
    return app


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--config',required=True);parser.add_argument('--jobs',default='outputs/report_jobs');parser.add_argument('--port',type=int,default=5010)
    args=parser.parse_args();create_app(args.config,args.jobs).run(host='127.0.0.1',port=args.port,threaded=True)
