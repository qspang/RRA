from datetime import datetime

from road_description.io import write_json
from .common.context import load_context
from .registry import create_agent, agent_ids
from road_description.runlog import RunLog


def run_agents(config_path, selected=None, description_ready=False):
    ctx = load_context(config_path)
    ctx.cache.update(config_path=str(config_path),description_ready=description_ready)
    selected = selected if selected is not None else ctx.options.get('enabled', agent_ids())
    if not isinstance(selected, list) or len(set(selected)) != len(selected):
        raise ValueError('agents.enabled必须是无重复的Agent ID数组')
    agents = [create_agent(s) for s in selected]
    ctx.output.mkdir(parents=True, exist_ok=True)
    log=RunLog(ctx.output,'agents')
    state = {'run_id':log.run_id,'status': 'running', 'started_at': datetime.now().isoformat(), 'selected': selected,
             'provenance': ctx.provenance, 'results': {}}
    write_json(ctx.output/'agent_run.json', state)
    try:
        for identifier, agent in zip(selected, agents):
            print('Agent:', identifier, flush=True)
            state['active'] = identifier
            write_json(ctx.output/'agent_run.json', state)
            log.event('agent_started',agent=identifier)
            result = agent.run(ctx)
            log.event('agent_completed',agent=identifier,status=result['status'],documents=len(result['documents']))
            destination = ctx.output/identifier/'result.json'
            result.update(agent=agent.manifest, provenance=ctx.provenance)
            write_json(destination, result)
            state['results'][identifier] = {'result_json': str(destination), 'documents': result['documents'],
                                             'status': result['status']}
        if ctx.options.get('assembly',{}).get('enabled') and {'route_comparison','route_compliance'}.issubset(selected):
            from .assembly import assemble
            log.event('assembly_started')
            state['assembly']=assemble(ctx)
            log.event('assembly_completed',documents=len(state['assembly']['documents']))
        from .delivery import delivery
        state['delivery_status']=delivery(ctx,state)['status']
        state.update(status='completed', active=None, completed_at=datetime.now().isoformat())
        write_json(ctx.output/'facts.json', ctx.facts)
        # Bound empty inputs are a starting point; no dummy approvals or survey quantities.
        write_json(ctx.output/'补充资料待填写.json', {'schemes': {
            s['id']: {'route_geometry_hash': s['geometry_hash'], 'surveys': {},
                      'crossing_designs': [], 'agreements': [], 'required_departments': [],
                      'specialists':{k:{'confirmed':False,'source_file':'','text':'','records':[]} for k in ('terrain','traffic','military','mining','ecology')}}
            for s in ctx.facts['schemes']}})
    except Exception as exc:
        log.event('failed',agent=state.get('active'),error_type=type(exc).__name__)
        state.update(status='failed', error_type=type(exc).__name__, error=str(exc)[:1000])
        raise
    finally:
        write_json(ctx.output/'agent_run.json', state)
    return state
