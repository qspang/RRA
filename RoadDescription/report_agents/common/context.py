from dataclasses import dataclass, field
from pathlib import Path
import math

from road_description.facts import Catalog, canonical_path, extract_facts, pair_schemes
from road_description.io import read_json, file_hash, digest, config_root
from road_description.planner import select_scheme
from road_description.model_runtime import prepare_model_config


@dataclass
class AgentContext:
    config: dict
    root: Path
    source: Path
    output: Path
    catalog: object
    facts: dict
    responses: dict
    schemes: dict
    provenance: dict
    supplement: dict = field(default_factory=dict)
    cache: dict = field(default_factory=dict)

    @property
    def options(self):
        return self.config.get('agents', {})

    def supplied(self, scheme_id):
        data = self.supplement.get('schemes', {}).get(scheme_id, {})
        if data:
            current = next(s['geometry_hash'] for s in self.facts['schemes'] if s['id'] == scheme_id)
            if data.get('route_geometry_hash') != current:
                raise ValueError(f'{scheme_id}补充资料未绑定当前route_geometry_hash，不能复用旧路线结论')
        return data

    def evidence(self, record):
        """A confirmed human input must have a real source, never just a boolean."""
        if not record or record.get('confirmed') is not True or not record.get('source_file'):
            return {'verified': False, 'reason': '缺人工确认或来源文件'}
        path = (self.root / record['source_file']).resolve()
        if not path.is_file():
            return {'verified': False, 'reason': '来源文件不存在'}
        return {'verified': True, 'source_file': str(path), 'sha256': file_hash(path),
                'confirmation': '输入资料中明确标记已人工确认；程序未代替专业复核'}


def load_context(config_path):
    path = Path(config_path).resolve()
    root = config_root(path)
    config = read_json(path)
    prepare_model_config(config,root)
    if config.get('soffice') and '/' in config['soffice']:
        config['soffice'] = str((root/config['soffice']).resolve())
    for key in ('dataset', 'output_dir', 'reference_pdf', 'admin_boundary'):
        if config.get(key):
            config[key] = str((root / config[key]).resolve())
    config['supplemental_layers']=[dict(s,path=str((root/s['path']).resolve())) for s in config.get('supplemental_layers',[])]
    source = Path(config['output_dir'])
    opts = config.get('agents', {})
    output = (root / opts['output_dir']).resolve() if opts.get('output_dir') else source / 'agents'
    responses, chosen, items, archives = {}, {}, [], []
    definitions = config.get('schemes', [])
    if len(definitions) != 2 or len({x['id'] for x in definitions}) != 2:
        raise ValueError('插件需要两个ID不同、起终点一致的南北方案')
    from road_description.map_snapshot import bind_snapshot
    map_data = bind_snapshot(read_json(source/'map.json'),[read_json(source/spec['id']/'response.json') for spec in definitions])
    catalog = Catalog(config['dataset'],map_data,config.get('name_overrides'),source,config.get('supplemental_layers'))
    catalog.report_style=config.get('report_style','detailed')
    if config.get('use_satellite') and config.get('basemap_mode')=='browser':
        catalog.basemap_key=('browser-labels:' if config.get('basemap_annotations') else 'browser:')+config['planner_url']
        catalog.basemap_cache=source/'tiles'
    for spec in definitions:
        sid = spec['id']
        if not sid or Path(sid).name != sid or sid in ('.', '..'):
            raise ValueError('方案ID必须为单个安全文件名')
        response_path = source / sid / 'response.json'
        response = read_json(response_path)
        aux = response.get('map_auxiliary') or {}
        stamp = (aux.get('base_map') or {}).get('manifest_mtime')
        if stamp is not None and map_data.get('manifest_mtime') is not None:
            if abs(float(stamp) - float(map_data['manifest_mtime'])) > 1:
                raise ValueError('规划结果与地图快照版本不一致')
        scheme = select_scheme(response)
        route = canonical_path(scheme, config.get('start'))
        for name, endpoint in (('start', route.coords[0]), ('end', route.coords[-1])):
            if not config.get(name) or math.dist(endpoint, config[name]) > 1:
                raise ValueError('报告起终点与实际规划结果不一致')
        responses[sid], chosen[sid] = response, scheme
        items.append(extract_facts(scheme, catalog, config, sid))
        archives.append({'scheme_id': sid, 'plan_run_id': response.get('plan_run_id'),
                         'response': str(response_path), 'sha256': file_hash(response_path)})
    pair = pair_schemes(items)
    # An existing fact package must belong to the same data package and routes.
    old_path = source / 'route_facts.json'
    if old_path.exists():
        old = read_json(old_path)
        for key in ('manifest_sha256', 'features_sha256', 'rules_sha256','adjustments_sha256','supplemental_layers_sha256'):
            if old.get('provenance', {}).get(key) != catalog.provenance.get(key):
                raise ValueError('已归档事实与当前GIS数据哈希不匹配，请先重新生成路径描述')
        prior = {s['id']: s['geometry_hash'] for s in old['schemes']}
        if prior != {s['id']: s['geometry_hash'] for s in items}:
            raise ValueError('已归档事实与响应路径不一致，请先重新生成路径描述')
    supplement = {}
    supplemental_provenance = None
    if opts.get('supplemental_file'):
        sp = (root / opts['supplemental_file']).resolve()
        supplement = read_json(sp)
        supplemental_provenance = {'path': str(sp), 'sha256': file_hash(sp)}
    provenance = {**catalog.provenance, 'responses': archives,
                  'reference_pdf_sha256': file_hash(config['reference_pdf']),
                  'supplemental': supplemental_provenance,
                  'runtime_rules_sha256': digest(catalog.runtime_rules)}
    ctx = AgentContext(config, root, source, output, catalog,
                       {'project': config['project_title'], 'schemes': items, 'comparison': pair},
                       responses, chosen, provenance, supplement)
    for item in items:
        ctx.supplied(item['id'])
    return ctx
