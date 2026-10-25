import hashlib
import json
from pathlib import Path


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    temp.replace(path)


def digest(data):
    return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def file_hash(path):
    h = hashlib.sha256()
    with open(path, 'rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def public_data(value):
    """Remove credentials from all archived planner payloads."""
    if isinstance(value, dict):
        return {k: public_data(v) for k, v in value.items()
                if k.lower() not in {'tianditu_tk', 'api_key', 'authorization', 'access_token'}}
    if isinstance(value, list):
        return [public_data(v) for v in value]
    return value


def archive_map(folder, data):
    """Full map geometry can be hundreds of MB; keep a gzip source plus light metadata."""
    import gzip
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    safe=public_data(data)
    with gzip.open(folder/'map.raw.json.gz','wt',encoding='utf-8') as stream:
        json.dump(safe,stream,ensure_ascii=False,separators=(',',':'))
    omitted={'features','feature_group_index','wind_ice_layer'}
    meta={k:v for k,v in safe.items() if k not in omitted}
    meta['raw_map_file']='map.raw.json.gz'
    meta['archived_feature_count']=len(data.get('features',[]))
    write_json(folder/'map.json',meta)
    return meta


def config_root(config_path, config=None):
    """Resolve the declared project root, retaining old config-relative semantics."""
    path = Path(config_path).resolve()
    config = read_json(path) if config is None else config
    return (path.parent / config.get('project_root', '.')).resolve()
