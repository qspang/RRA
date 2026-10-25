import argparse
from pathlib import Path
import time

from .io import read_json,write_json,public_data,archive_map, config_root
from .planner import PlannerClient,select_scheme
from .facts import Catalog,extract_facts,pair_schemes
from .narrative import compose,inspect_photo
from .figures import generate_figures
from .document import extract_logo,create_template,render_docx,render_pdf,inspect_pdf
from .model_runtime import prepare_model_config,parallel_map,telemetry
from .materials import approved_materials
from .runlog import RunLog


def run(config_path,plan=False,description_only=False):
    config_path=Path(config_path).resolve();root=config_root(config_path)
    config=read_json(config_path)
    if config.get('route_generation',{}).get('enabled') and (plan or not config.get('schemes')):
        from .automatic_routes import generate_two_routes
        resolved=generate_two_routes(config_path,force=plan)
        return run(resolved,plan=False,description_only=description_only)
    prepare_model_config(config,root)
    if config.get('soffice') and '/' in config['soffice']:
        config['soffice'] = str((root/config['soffice']).resolve())
    for key in ('dataset','output_dir','reference_pdf','admin_boundary'):
        if config.get(key):config[key]=str((root/config[key]).resolve())
    config['supplemental_layers']=[dict(s,path=str((root/s['path']).resolve())) for s in config.get('supplemental_layers',[])]
    out=Path(config['output_dir']);out.mkdir(parents=True,exist_ok=True)
    log=RunLog(out,'pipeline')
    state={'run_id':log.run_id,'stage':'loading','started_at':time.strftime('%Y-%m-%d %H:%M:%S')}
    def stage(name):
        log.event(name,error_type=state.get('error_type'))
        state['stage']=name;write_json(out/'report_job.json',state);print(name,flush=True)
    try:
        stage('loading')
        key=''
        if plan:
            client=PlannerClient(config['planner_url']);health,map_data=client.initialize()
            write_json(out/'health.json',health);archive_map(out,map_data)
        else:
            map_data=read_json(out/'map.json')
        if config.get('use_satellite') and config.get('basemap_mode')=='browser':
            key=('browser-labels:' if config.get('basemap_annotations') else 'browser:')+config['planner_url']
        elif config.get('use_satellite') and plan:
            key=map_data['geo_meta'].get('tianditu_tk','')
        elif config.get('use_satellite'):
            try:
                client=PlannerClient(config['planner_url']);_,live=client.initialize()
                key=live['geo_meta'].get('tianditu_tk','')
            except Exception:
                state['basemap_warning']='在线底图不可用，采用矢量地图'
        responses={}
        for item in config['schemes']:
            target=out/item['id']
            if plan:
                request=dict(config.get('request',{}),start_x=config['start'][0],start_y=config['start'][1],
                             end_x=config['end'][0],end_y=config['end'][1],
                             solver_options={**config.get('request',{}).get('solver_options',{}),'pause_after_coarse_review':False})
                if item.get('waypoint'):
                    x,y=item['waypoint'];request['must_pass_points']=[{'id':item['id'],'x':x,'y':y,'tolerance_m':100}]
                responses[item['id']]=client.plan(request,target)
            else:responses[item['id']]=read_json(target/'response.json')
        from .map_snapshot import bind_snapshot
        map_data=bind_snapshot(map_data,list(responses.values()))
        catalog=Catalog(config['dataset'],map_data,config.get('name_overrides'),out,config.get('supplemental_layers'))
        catalog.report_style=config.get('report_style','detailed')
        catalog.basemap_key=key
        catalog.basemap_cache=out/'tiles'
        write_json(out/'data_audit.json',{'coverage':catalog.coverage(),'provenance':catalog.provenance,
            'html_sources':{'feature_title':'feature.name (分类名称)','regions':['保护范围','奖励走廊','密集通道','风冰区'],
                            'place_labels':'天地图cia_w注记瓦片；无对应可查询地名属性表'}})
        stage('extracting_facts')
        extracted=[];response_provenance=[]
        for item in config['schemes']:
            target=out/item['id']
            response=responses[item['id']]
            auxiliary=response.get('map_auxiliary') or {}
            base=auxiliary.get('base_map') or {}
            if base.get('manifest_mtime') is not None and map_data.get('manifest_mtime') is not None:
                if abs(float(base['manifest_mtime'])-float(map_data['manifest_mtime']))>1:
                    raise ValueError('规划结果与地图快照版本时间不一致，请重新获取匹配数据')
            requested=read_json(target/'request.json') if (target/'request.json').exists() else response.get('replay_request',{})
            for kind in ('start','end'):
                if all(k in requested for k in (kind+'_x',kind+'_y')) and config.get(kind):
                    if __import__('math').dist([requested[kind+'_x'],requested[kind+'_y']],config[kind])>1:
                        raise ValueError('报告配置与归档规划请求的起终点不一致')
            chosen=select_scheme(response)
            extracted.append(extract_facts(chosen,catalog,config,item['id']))
            response_provenance.append({'source':str(target/'response.json'),'plan_run_id':response.get('plan_run_id'),
                                        'scheme_id':chosen.get('id'),'request':str(target/'request.json')})
        pair=pair_schemes(extracted)
        facts={'project':config['project_title'],'schemes':extracted,'comparison':pair,
               'provenance':catalog.provenance,'planning':response_provenance,
               'draft':True,'model_configured':bool(config.get('llm',{}).get('enabled'))}
        write_json(out/'route_facts.json',facts)
        stage('generating_figures')
        figures=generate_figures(catalog,facts,out/'figures',key=key)
        photo_audit=[]
        for photo in config.get('photos',[]):
            p=(root/photo['path']).resolve()
            record=dict(photo,path=str(p))
            if config.get('vlm',{}).get('enabled'):
                try:record['vlm']=inspect_photo(p,config['vlm'])
                except Exception as exc:record['vlm_error']=type(exc).__name__
            photo_audit.append(record)
        materials=approved_materials(config,root,facts,out,'description')
        figures.extend(materials)
        for scheme in facts['schemes']:
            scheme['figure_ids'].extend(m['id'] for m in materials if m['scheme_id']==scheme['id'])
        write_json(out/'photo_audit.json',photo_audit)
        write_json(out/'figure_manifest.json',figures);write_json(out/'route_facts.json',facts)
        stage('writing')
        drafted=parallel_map(lambda s:compose(s,config),facts['schemes'],config.get('llm',{}).get('max_concurrency',15))
        narratives={s['id']:n for s,n in zip(facts['schemes'],drafted)}
        write_json(out/'narrative.json',narratives)
        stage('rendering')
        logo=extract_logo(config['reference_pdf'],root/'assets/reference_header')
        template=root/'templates/route_description_v1.docx'
        if not template.exists():create_template(template,config,logo)
        docx=render_docx(config,facts,narratives,figures,out/'路径方案描述_联调样章.docx',template)
        pdf=render_pdf(docx,config.get('soffice',''))
        if pdf['status']=='completed':write_json(out/'layout_review.json',inspect_pdf(pdf['path'],out/'preview'))
        validation={'status':'draft','schemes':len(extracted),'names':[s['name'] for s in extracted],
            'length_checks':[{'id':s['id'],'geometry_m':s['metrics']['length_m'],'api_m':s['metrics']['api_length_m']} for s in extracted],
            'missing':{s['name']:s['missing'] for s in extracted},'photos_pending':not any(f['kind']=='approved_photo' for f in figures),
            'model_modes':{sid:n['mode'] for sid,n in narratives.items()},'pdf':pdf,
            'scope':'路径通过当前规划模型校核；不代表已经完成全部实际直线塔定位或专业审批',
            'font_note':'DOCX指定宋体/Times New Roman；本机预览可能由Noto Serif CJK/Liberation Serif替代，需在安装原字体的Word中确认。'}
        write_json(out/'validation.json',validation)
        import csv
        with (out/'跨越与地物事件.csv').open('w',encoding='utf-8-sig',newline='') as stream:
            writer=csv.writer(stream);writer.writerow(['方案','事实ID','起始里程m','结束里程m','地物名称/类别','关系','原始ID','名称字段'])
            for s in facts['schemes']:
                for e in s['events']:
                    writer.writerow([s['name'],e['fact_id'],round(e['start_m'],1),round(e['end_m'],1),
                                     e['label'],e['relation'],';'.join(e['source_uids']),e['name_source']])
        lines=['路径描述样章生成说明','',config['project_title'],'',
               '该文档使用真实规划接口响应及底层地物资料生成。模型实际调用模式和现场素材缺口分别见下方及validation.json。',
               '']
        for s in facts['schemes']:
            lines.append(f"{s['name']}：{s['metrics']['length_m']/1000:.3f}km；曲折系数{s['metrics']['tortuosity']:.3f}；重要地物事件{len(s['events'])}项。")
            lines.extend('  待核实：'+x for x in s['missing'])
        lines+=['','模型模式：'+str(validation['model_modes']),
                f"插图{len(figures)}张（含总览）；图件类型："+'、'.join(sorted({f['kind'] for f in figures})),
                validation['font_note'],'','完整证据见route_facts.json、跨越与地物事件.csv和各方案response.json。']
        (out/'生成说明.txt').write_text('\n'.join(lines)+'\n',encoding='utf-8')
        state.update(docx=docx,pdf=pdf)
        if config.get('agents', {}).get('enabled') and not description_only:
            stage('running_agents')
            from report_agents.runner import run_agents
            state['agents'] = run_agents(config_path,description_ready=True)
        write_json(out/'model_calls.json',telemetry())
        if config.get('quality_review',{}).get('enabled') and not description_only:
            stage('reviewing_reports')
            from .quality_review import review_reports
            review=review_reports(config,out)
            state['quality_review']={'status':review['status'],'path':str(out/'quality_review.json')}
            if review['status']!='passed':
                stage('review_required')
                return state
        stage('completed')
        return state
    except Exception as exc:
        state.update(error_type=type(exc).__name__,error=str(exc)[:1200]);stage('failed');raise


def main():
    from .planner import install_cancel_handler
    install_cancel_handler()
    parser=argparse.ArgumentParser(description='生成南北双方案路径描述Word')
    parser.add_argument('--config',default='configs/config.demo.json')
    parser.add_argument('--plan',action='store_true',help='重新通过HTTP规划；默认使用已归档response.json')
    args=parser.parse_args();result=run(args.config,args.plan);print(result)
    if result.get('stage')=='review_required':parser.exit(2,'成稿需复核，详见quality_review.json\n')


if __name__=='__main__':main()
