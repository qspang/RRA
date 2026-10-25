"""HTTP adapter; preserves planner cookies and saves complete request/response evidence."""
import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

from .io import public_data, write_json

_active_plan = None


def install_cancel_handler():
    import signal
    def stop(signum,frame):
        active=_active_plan
        if active:
            session,url,run_id,output=active
            try:
                response=session.post(url+'/api/plan/cancel',json={'plan_run_id':run_id},timeout=3)
                write_json(output/'cancellation.json',{'reason':'report_job_cancelled','http_status':response.status_code,
                                                      'response':public_data(response.json())})
            except (requests.RequestException,ValueError):
                write_json(output/'cancellation.json',{'reason':'report_job_cancelled','status':'cancel_request_failed'})
        raise SystemExit(128+signum)
    signal.signal(signal.SIGTERM,stop)


class PlannerError(RuntimeError):
    pass


class PlannerClient:
    def __init__(self, base_url, token=None):
        self.base = base_url.rstrip('/')
        self.session = requests.Session()
        token = token or os.getenv('ROAD_PLANNER_TOKEN')
        if token:
            self.session.headers['Authorization'] = 'Bearer ' + token

    def call(self, method, path, timeout=120, **kwargs):
        self.last_failure = None
        try:
            r = self.session.request(method, self.base + path, timeout=timeout, **kwargs)
        except requests.RequestException as exc:
            self.last_failure={'error_type':type(exc).__name__,'path':path}
            raise PlannerError(f'{method} {path}: {type(exc).__name__}') from exc
        if not r.ok:
            try: body=r.json()
            except ValueError: body={'message':r.text[:4000]}
            self.last_failure={'status_code':r.status_code,'response':public_data(body)}
            raise PlannerError(f'{method} {path}: HTTP {r.status_code}: {r.text[:1800]}')
        try:
            data = r.json()
        except ValueError as exc:
            self.last_failure={'status_code':r.status_code,'error_type':'InvalidJSON','path':path}
            raise PlannerError(f'{method} {path}: 响应不是有效JSON') from exc
        if not isinstance(data,dict):
            self.last_failure={'status_code':r.status_code,'error_type':'InvalidShape','path':path}
            raise PlannerError(f'{method} {path}: 预期JSON对象')
        return data

    def map_meta(self):
        return self.call('GET', '/api/map/meta')

    def map_features(self, bounds, **options):
        return self.call('GET', '/api/map/features', params=dict(zip(('xmin','ymin','xmax','ymax'),bounds),**options))

    def progress(self, run_id):
        return self.call('GET','/api/plan/progress',params={'plan_run_id':run_id})

    def cancel(self, run_id):
        if not run_id:
            raise PlannerError('取消必须提供本次任务ID，避免影响其他任务')
        return self.call('POST','/api/plan/cancel',json={'plan_run_id':run_id})

    def initialize(self):
        health = self.call('GET', '/api/health')
        data = self.call('GET', '/api/map')
        if not data.get('preprocess_mode') or not data.get('geo_meta'):
            raise PlannerError('报告联调需要真实预处理地图及坐标元数据')
        if data.get('features_lazy'):
            preview=self.call('GET','/api/map/features',params={'tol':0,'max_features':1})
            full=self.call('GET','/api/map/features',params={'tol':0,'max_features':max(1,preview['total_in_view'])})
            if full.get('capped') or full['returned']!=full['total_in_view']:
                raise PlannerError('地图快照未完整返回，不能生成遗漏地物的报告')
            data.update(features=full['features'],features_lazy=False,report_full_snapshot=True)
        return health, data

    def validate(self, point, cell_size=100):
        return self.call('GET', '/api/validate_constraint_point',
                         params={'x': point[0], 'y': point[1], 'cell_size': cell_size})

    def plan(self, payload, output, poll_seconds=10, max_seconds=None):
        global _active_plan
        output = Path(output)
        output.mkdir(parents=True, exist_ok=True)
        payload = dict(payload, plan_run_id='rd_' + uuid.uuid4().hex)
        for kind in ('start', 'end'):
            point = [payload[kind + '_x'], payload[kind + '_y']]
            check = self.validate(point, payload.get('fine_cell_size', 100))
            if not check.get('valid'):
                raise PlannerError(f'{kind} {point} 未通过控制点校验: {check}')
        for p in payload.get('must_pass_points', []):
            if not self.validate([p['x'], p['y']], payload.get('fine_cell_size', 100)).get('valid'):
                raise PlannerError(f"必过点{p.get('id', '')}未通过校验")
        write_json(output / 'request.json', payload)
        # Separate read-only session for polling; requests.Session is not shared across threads.
        poll = requests.Session()
        poll.cookies.update(self.session.cookies)
        poll.headers.update(self.session.headers)
        started = time.monotonic()
        _active_plan=(poll,self.base,payload['plan_run_id'],output)
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(self.call, 'POST', '/api/plan', timeout=(15, max_seconds+45 if max_seconds else 7200), json=payload)
            cancelled = False
            while not future.done():
                if max_seconds and time.monotonic()-started > max_seconds and not cancelled:
                    try:
                        cancellation = poll.post(self.base+'/api/plan/cancel',json={'plan_run_id':payload['plan_run_id']},timeout=15)
                        write_json(output/'cancellation.json', {'reason':'attempt_deadline', 'http_status':cancellation.status_code,
                                   'response':public_data(cancellation.json())})
                    except (requests.RequestException, ValueError):
                        pass
                    cancelled = True
                try:
                    r = poll.get(self.base + '/api/plan/progress',
                                 params={'plan_run_id': payload['plan_run_id']}, timeout=15)
                    if r.ok:
                        progress = r.json()
                        progress.pop('latest_result', None)
                        write_json(output / 'progress.json', public_data(progress))
                        print(f"规划 {int(time.monotonic()-started)}s: "
                              f"{progress.get('stage', progress.get('status'))}", flush=True)
                except (requests.RequestException, ValueError):
                    pass
                time.sleep(poll_seconds)
            try:
                result = future.result()
            except Exception:
                if hasattr(self,'last_failure'):write_json(output/'http_error.json',self.last_failure)
                raise
        write_json(output / 'response.json', public_data(result))
        _active_plan=None
        if cancelled:
            raise PlannerError('本次候选规划超过时限，已请求取消；该结果不作为自动选定方案')
        return result

    def submit_job(self, project_id, revision_id, request_key):
        return self.call('POST', f'/api/projects/{project_id}/jobs',
                         json={'revision_id': revision_id, 'request_key': request_key})

    def create_project(self,name):
        return self.call('POST','/api/projects',json={'name':name})

    def import_map(self,project_id,source='default'):
        return self.call('POST',f'/api/projects/{project_id}/maps',timeout=600,json={'source':source,'name':'报告联调地图'})

    def create_scenario(self,project_id,map_id,name,payload):
        return self.call('POST',f'/api/projects/{project_id}/scenarios',timeout=600,
                         json={'map_id':map_id,'name':name,'request':payload})

    def wait_job(self,job_id,output,max_seconds=720,poll_seconds=2):
        output=Path(output);output.mkdir(parents=True,exist_ok=True);started=time.monotonic()
        while True:
            state=self.call('GET',f'/api/jobs/{job_id}')
            write_json(output/'job_state.json',public_data(state))
            if state['status']=='completed':
                result=self.job_result(job_id);write_json(output/'response.json',public_data(result));return result
            if state['status'] in ('failed','cancelled','interrupted'):
                raise PlannerError('工程任务结束：'+state['status'])
            if time.monotonic()-started>max_seconds:
                cancellation=self.call('POST',f'/api/jobs/{job_id}/cancel',json={})
                write_json(output/'cancellation.json',public_data(cancellation))
                raise PlannerError('工程任务超时，已请求取消')
            time.sleep(poll_seconds)

    def job_result(self, job_id):
        state = self.call('GET', f'/api/jobs/{job_id}')
        if state['status'] != 'completed':
            raise PlannerError(f"任务尚未完成: {state['status']}")
        return self.call('GET', f'/api/jobs/{job_id}/result')


def select_scheme(response):
    if response.get('coarse_review_pending'):
        raise PlannerError('仅有粗规划预览，不生成完成方案报告')
    choices = [s for s in response.get('schemes', [])
               if s.get('feasible') is True and not s.get('coarse_review')
               and not s.get('partial_feasible') and not s.get('remaining_violations', 0)
               and s.get('analysis', {}).get('validations', {}).get('feasible') is True]
    if not choices:
        raise PlannerError('没有通过当前模型校核的完整方案: ' +
                           str(response.get('solver_failure', response.get('plan_outcome'))))
    return min(choices, key=lambda s: s.get('analysis', {}).get('total_cost', float('inf')))
