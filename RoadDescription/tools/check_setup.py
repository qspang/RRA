"""Check local report inputs without generating routes or calling paid model APIs."""
import argparse
import json
from pathlib import Path
import shutil
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from road_description.io import read_json, config_root
from road_description.model_runtime import prepare_model_config, credential


def check(config_path, deep=False):
    path = Path(config_path).resolve()
    root = config_root(path)
    config = read_json(path)
    prepare_model_config(config, root)
    checks = []
    def record(name, ok, required=True, note=''):
        checks.append(dict(item=name, status='pass' if ok else 'error' if required else 'warning', note=note))
    def exists(name, value, required=True):
        target = (root/value).resolve() if value else None
        ok = bool(target and target.exists())
        record(name, ok, required, '已找到' if ok else '缺少配置或文件')
        return target if ok else None
    data = exists('dataset', config.get('dataset'))
    if data:
        for name in ('manifest.json', 'm1/standardized_features.gpkg', 'm3/rule_config.json'):
            exists('dataset/'+name, str(data/name))
        for name in ('forbidden_polygons', 'no_tower_polygons', 'wind_ice_zones'):
            exists('dataset/m2/'+name, str(data/'m2'/f'{name}.gpkg'), False)
    exists('reference_pdf', config.get('reference_pdf'))
    exists('template', 'templates/route_description_v1.docx')
    opts = config.get('agents', {})
    dem = exists('DEM', opts.get('dem_path'), False)
    exists('行政边界（未配置时仅使用现有地物属性）', config.get('admin_boundary'), False)
    for index, spec in enumerate(config.get('supplemental_layers', [])):
        source = exists(f'supplemental_layers[{index}]', spec.get('path'))
        if deep and source:
            import pyogrio
            layers = pyogrio.list_layers(source)[:, 0].tolist()
            record(f'supplemental_layers[{index}].layer', spec.get('layer') in layers,
                   note='检查指定图层是否存在')
    if deep and dem:
        import rasterio
        with rasterio.open(dem) as raster:
            record('DEM坐标系', raster.crs is not None, note='此检查不代替路线范围与NoData核查')
    binary = config.get('soffice')
    renderer = ((root/binary).is_file() if binary and '/' in binary else shutil.which(binary)) if binary else (shutil.which('soffice') or shutil.which('libreoffice'))
    record('PDF渲染器', bool(renderer), note='需要 LibreOffice 或本地 wrapper')
    for name in ('llm', 'vlm'):
        settings = config.get(name, {})
        if not settings.get('enabled'):
            record(name, False, False, '未启用；仅能验证模板回退，不能视为模型验收')
            continue
        record(name+'连接参数', bool(settings.get('api_base') and settings.get('model_id')), note='仅检查配置，不发送模型请求')
        try:
            ready = bool(credential(settings))
        except (OSError, ValueError):
            ready = False
        record(name+'凭据', ready, note='只报告是否存在，不输出密钥或地址')
    return {'status': 'failed' if any(c['status']=='error' for c in checks) else 'ready_with_warnings' if any(c['status']=='warning' for c in checks) else 'ready', 'checks': checks,
            'scope': '本地静态检查；不保证规划服务在线、路线可行、卫星底图或外部模型可用。'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', default='configs/config.local.json')
    parser.add_argument('--deep', action='store_true', help='读取GDB图层列表与DEM元信息')
    args = parser.parse_args()
    try:
        result = check(args.config, args.deep)
    except Exception as exc:
        result = {'status':'failed', 'error_type':type(exc).__name__, 'note':'配置或数据无法读取；请检查文件及格式。未输出可能含凭据的异常正文。'}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if result['status']=='failed' else 0

if __name__ == '__main__':
    raise SystemExit(main())
