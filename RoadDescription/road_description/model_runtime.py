"""Credential-safe model transport, bounded concurrency, retries and telemetry."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import threading
import time

import requests


_lock = threading.Lock()
_gate = threading.BoundedSemaphore(15)
_provider_gates = {}
_events = []
_active = 0
_peak = 0


def prepare_model_config(config, root):
    """Resolve only the declared credential file; never execute/shell-source it."""
    for name in ('llm', 'vlm'):
        settings = config.get(name, {})
        if settings.get('credential_file'):
            settings['credential_file'] = str((Path(root)/settings['credential_file']).resolve())
    for settings in config.get('agents', {}).values():
        if isinstance(settings, dict):
            prepare_model_config(settings, root)
    return config


def credential(config):
    name = config.get('api_key_env', 'ROAD_LLM_API_KEY')
    if os.getenv(name):
        return os.environ[name]
    path = config.get('credential_file')
    if path:
        # Keep the key local to the request, without changing other providers' env.
        for line in Path(path).read_text(encoding='utf-8').splitlines():
            key, sep, value = line.partition('=')
            if sep and key.strip() == name:
                return value.strip().strip('"\'')
    return ''


def decode_json(content):
    if isinstance(content, list):
        content = ''.join(x.get('text', '') for x in content if isinstance(x, dict))
    if not isinstance(content, str):
        raise ValueError('模型响应缺少文本内容')
    value = content.strip()
    if value.startswith('```') and value.endswith('```'):
        value = value.split('\n', 1)[1].rsplit('```', 1)[0].strip()
    try:
        parsed = json.loads(value, strict=False)
    except json.JSONDecodeError:
        # Some compatible providers add a short prose prefix/suffix despite JSON mode.
        # Extract a complete object, still requiring the caller's exact schema/IDs.
        start=value.find('{')
        if start<0:raise
        parsed,_=json.JSONDecoder(strict=False).raw_decode(value[start:])
    if not isinstance(parsed, dict):
        raise ValueError('模型必须返回JSON对象')
    return parsed


def telemetry():
    with _lock:
        return {'concurrency_limit': 15, 'peak_active': _peak, 'calls': list(_events)}


def parallel_map(function, values, workers=15):
    with ThreadPoolExecutor(max_workers=max(1, min(15, int(workers)))) as pool:
        return list(pool.map(function, values))


def model_call(config, messages):
    global _active, _peak
    if not config.get('enabled'):
        raise ValueError('模型未启用')
    base, model = config.get('api_base', '').rstrip('/'), config.get('model_id')
    key = credential(config)
    if not base or not model or not key:
        raise ValueError('缺少api_base、model_id或独立凭据')
    limit = int(config.get('max_concurrency', 15))
    if not 1 <= limit <= 15:
        raise ValueError('max_concurrency须在1至15之间')
    endpoint = base if base.endswith('/chat/completions') else base+'/chat/completions'
    payload = {'model': model, 'messages': messages, 'temperature': config.get('temperature', .1),
               'max_tokens': config.get('max_tokens', 3000)}
    if config.get('json_mode', True):
        payload['response_format'] = {'type': 'json_object'}
    started = time.monotonic()
    event = {'model_requested': model, 'api_base': base,'purpose':config.get('_purpose','generation'),
             'input_sha256': hashlib.sha256(json.dumps(messages,ensure_ascii=False,sort_keys=True).encode()).hexdigest(),
             'status': 'failed', 'attempts': 0}
    # A single gate is shared across description, comparison, compliance and VLM.
    with _lock:
        provider_gate=_provider_gates.setdefault((base,model,config.get('api_key_env'),limit),threading.BoundedSemaphore(limit))
    with provider_gate, _gate:
        with _lock:
            _active += 1; _peak = max(_peak, _active)
        try:
            max_attempts = int(config.get('max_retries', 2))+1
            for attempt in range(max_attempts):
                event['attempts'] += 1
                try:
                    response = requests.post(endpoint, headers={'Authorization':'Bearer '+key},
                                             json=payload, timeout=config.get('timeout_s',180))
                except requests.RequestException as exc:
                    if attempt+1 < max_attempts:
                        time.sleep(min(8, 2**attempt)); continue
                    raise RuntimeError('模型传输失败：'+type(exc).__name__) from None
                event['http_status'] = response.status_code
                if response.status_code in (400,422) and 'response_format' in payload and attempt+1 < max_attempts:
                    payload.pop('response_format')
                    event['json_mode_fallback'] = True
                    continue
                if response.status_code in (429,500,502,503,504) and attempt+1 < max_attempts:
                    time.sleep(min(8, 2**attempt)); continue
                if not response.ok:
                    raise RuntimeError(f'模型接口HTTP {response.status_code}')
                try:
                    data = response.json()
                    if isinstance(data.get('usage'),dict):event.setdefault('usage_attempts',[]).append({'attempt':attempt+1,**data['usage']})
                    choice = data['choices'][0]
                except (ValueError,KeyError,IndexError) as exc:
                    event.setdefault('format_failures',[]).append({'attempt':attempt+1,'stage':'http_envelope','error_type':type(exc).__name__})
                    if attempt+1 < max_attempts:continue
                    raise ValueError('模型HTTP响应结构无效') from None
                if choice.get('finish_reason') == 'length':
                    raise ValueError('模型响应被输出token上限截断')
                content=choice.get('message',{}).get('content')
                try:
                    parsed = decode_json(content)
                except (ValueError,IndexError,TypeError) as exc:
                    import re
                    sample=re.sub(r'sk-[A-Za-z0-9_-]+','[REDACTED]',str(content).replace(key,'[REDACTED]'))[:1200]
                    event.setdefault('format_failures',[]).append({'attempt':attempt+1,'stage':'model_json','error_type':type(exc).__name__,'sample':sample})
                    if attempt+1 < max_attempts:
                        payload['messages']=messages+[{'role':'user','content':'上一响应不是有效JSON。原因可能是字符串值内出现未转义的英文双引号。请重新返回纯JSON对象，不用Markdown代码块。JSON字段名和字符串外边界仍用英文双引号，但自然语言描述内部的引用一律用中文「」括号或直接不用引号。尤其summary和description内部不要出现英文双引号。保持原有事实判断，不要改变结论来凑格式。'}]
                        continue
                    raise ValueError('模型连续返回无法解析的JSON') from None
                usage = data.get('usage', {})
                event.update(status='completed',model_reported=data.get('model'),usage=usage,
                             response_sha256=hashlib.sha256(json.dumps(parsed,sort_keys=True,ensure_ascii=False).encode()).hexdigest())
                return parsed, usage
            raise RuntimeError('模型重试未完成')
        except Exception as exc:
            event['error_type'] = type(exc).__name__
            raise
        finally:
            event['elapsed_s'] = round(time.monotonic()-started, 3)
            with _lock:
                _active -= 1; _events.append(event)
