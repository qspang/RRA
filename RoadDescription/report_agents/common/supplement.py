import math


def finite_quantity(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        raise ValueError('确认数量必须是非负有限数值')
    return value


def survey(ctx, scheme_id, key):
    record = ctx.supplied(scheme_id).get('surveys', {}).get(key, {})
    source = ctx.evidence(record)
    if not source['verified']:
        return {'status': 'pending', 'reason': source['reason'], 'records': []}
    rows = record.get('records', [])
    if not isinstance(rows, list):
        raise ValueError('调查records必须是数组')
    for row in rows:
        if key == 'demolition':
            finite_quantity(row.get('quantity'))
            if row.get('unit') not in ('m2', '个', '座') or not row.get('kind'):
                raise ValueError('拆迁条目须有kind和明确单位m2/个/座')
        elif key == 'forestry':
            finite_quantity(row.get('height_m'))
            finite_quantity(row.get('felling_area_m2'))
            if not row.get('species'):
                raise ValueError('林木调查缺少树种')
    if key == 'forestry' and 'forest_length_m' in record:
        finite_quantity(record['forest_length_m'])
    return {'status': 'confirmed_input', 'records': rows, 'evidence': source,
            'forest_length_m': record.get('forest_length_m'), 'text': record.get('text', '')}


AGREEMENT_LABELS = {'no_objection': '无意见', 'agreed': '同意', 'conditional': '附条件意见',
                    'rejected': '不同意', 'sent': '已发函，复函待取得', 'pending': '待办理'}


def agreements(ctx, scheme_id):
    supplied = ctx.supplied(scheme_id)
    records = []
    seen = set()
    for item in supplied.get('agreements', []):
        pair = (item.get('region', ''), item.get('department', ''))
        if not all(pair) or pair in seen:
            raise ValueError('协议须有行政区域和部门；同部门重复意见需先明确有效版本')
        seen.add(pair)
        code = item.get('status', 'pending')
        if code not in AGREEMENT_LABELS:
            raise ValueError('未知协议状态：'+str(code))
        evidence = ctx.evidence(item)
        # Even a "sent" assertion needs its outgoing letter to be called confirmed.
        effective = code if evidence['verified'] else 'pending'
        records.append({'region': pair[0], 'department': pair[1], 'status': effective,
                        'status_label': AGREEMENT_LABELS[effective], 'declared_status': code,
                        'reference': item.get('reference', '') if evidence['verified'] else '',
                        'conditions': item.get('conditions', '') if evidence['verified'] else '',
                        'evidence': evidence})
    required = supplied.get('required_departments', [])
    for item in required:
        pair = (item.get('region', ''), item.get('department', ''))
        if not all(pair):
            raise ValueError('应办协议清单须有区域和部门')
        if pair not in seen:
            seen.add(pair)
            records.append({'region': pair[0], 'department': pair[1], 'status': 'pending',
                            'status_label': '待办理', 'reference': '', 'conditions': '',
                            'evidence': {'verified': False, 'reason': '尚无复函'}})
    closed = bool(required) and all(r['status'] in ('agreed', 'no_objection') for r in records)
    return {'records': records, 'required_list_provided': bool(required),
            'status': 'rejected' if any(r['status']=='rejected' for r in records) else 'recorded_closed' if closed else 'pending',
            'meaning': '按人工确认的应办清单及来源文件统计，不自动认定法定审批手续齐备'}
