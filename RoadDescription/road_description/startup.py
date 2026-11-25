"""Credential-safe, offline reminders shared by the service and report worker."""
import os
from pathlib import Path

from .model_runtime import credential


def startup_notices(config, root, planning=False):
    notices = []
    models = [(key, config.get(key, {})) for key in ('llm', 'vlm')]
    for agent, options in config.get('agents', {}).items():
        if isinstance(options, dict) and 'llm' in options:
            models.append((agent + '.llm', options['llm']))
    for label, settings in models:
        missing = [field for field in ('api_base', 'model_id') if not settings.get(field)]
        settings = dict(settings)
        if settings.get('credential_file'):
            settings['credential_file'] = str(root / settings['credential_file'])
        try:
            key = credential(settings)
        except (OSError, UnicodeError):
            key = ''
        if not key:
            missing.append(settings.get('api_key_env', 'ROAD_LLM_API_KEY'))
        if missing or not settings.get('enabled'):
            state = '已启用' if settings.get('enabled') else '未启用'
            fields = '，请配置 ' + '、'.join(missing) if missing else ''
            impact = '图像模型审阅不可用' if label == 'vlm' else '对应正文可用模板生成'
            notices.append(f'{label} {state}{fields}。{impact}。')
        else:
            notices.append(f'{label} 已配置，远端可用性以实际调用为准，并发上限 {settings.get("max_concurrency", 15)}。')
    if config.get('use_satellite'):
        notices.append('已选天地图。密钥由规划服务 opt_v56 的 TIANDITU_TK 提供，绘图时检查授权或使用缓存。')
    else:
        notices.append('已选 GIS 矢量底图，无需天地图密钥。')
    if planning and not os.getenv('ROAD_PLANNER_TOKEN'):
        notices.append('未设置 ROAD_PLANNER_TOKEN。规划服务如启用鉴权，请在启动报告服务前导出此变量。')
    if config.get('route_source') == 'kml' and config.get('output_dir'):
        seed = root / config['output_dir']
        for filename in ('map.json', 'map.raw.json.gz'):
            if not (seed / filename).is_file():
                notices.append(f'KML 导入缺少地图快照 {seed / filename}。请从同一工程的数据包补齐。')
    return notices


def print_startup_notices(config, root, planning=False):
    for msg in startup_notices(config, Path(root), planning):
        print('[配置提示] ' + msg, flush=True)
