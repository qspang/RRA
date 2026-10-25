"""Confirmed specialist evidence; missing sources never turn into business facts."""
from .supplement import finite_quantity


def specialist(ctx, sid, key):
    item=ctx.supplied(sid).get('specialists',{}).get(key,{})
    evidence=ctx.evidence(item)
    if not evidence['verified']:
        return {'status':'pending','evidence':evidence,'text':'待补专项资料','records':[]}
    text=item.get('text','')
    if not isinstance(text,str) or not text.strip():
        raise ValueError(key+'专项资料须提供确认说明text')
    records=item.get('records',[])
    if not isinstance(records,list):raise ValueError(key+'的records必须为数组')
    result={'status':'confirmed_input','evidence':evidence,'text':text,'records':records}
    if key=='terrain':
        length=next(s['metrics']['length_m'] for s in ctx.facts['schemes'] if s['id']==sid)
        intervals=[];totals={}
        for row in records:
            lo,hi=finite_quantity(row.get('start_m')),finite_quantity(row.get('end_m'))
            if hi<=lo or hi>length+.1 or not row.get('class'):raise ValueError('地形分段类别或里程范围无效')
            intervals.append((lo,hi));totals[row['class']]=totals.get(row['class'],0)+hi-lo
        intervals.sort()
        if any(a[1]>b[0]+.01 for a,b in zip(intervals,intervals[1:])):raise ValueError('地形分类区段重叠')
        covered=sum(totals.values())
        result.update(coverage_m=covered,complete=abs(covered-length)<=.1,
                      totals=[{'class':k,'length_m':v,'percent':v/length*100} for k,v in totals.items()])
        if not intervals:raise ValueError('已确认地形分类必须包含分段records')
    if key=='ecology':
        known={f['uid'] for f in ctx.catalog.features}
        for row in records:
            if not row.get('source_uids') or not set(row['source_uids']).issubset(known) or not row.get('measure'):
                raise ValueError('生态措施必须关联当前有效地物source_uids并填写measure')
    return result


def recommendation(ctx, conflict_schemes):
    item=ctx.supplement.get('recommendation',{})
    source=ctx.evidence(item)
    pending={'status':'pending_professional_review','recommended_scheme_id':None,'evidence':source}
    if not source['verified']:return pending
    hashes={f['id']:f['geometry_hash'] for f in ctx.facts['schemes']}
    if item.get('route_geometry_hashes')!=hashes:raise ValueError('推荐意见必须绑定两方案几何版本')
    sid=item.get('scheme_id')
    if sid not in hashes or not item.get('text'):raise ValueError('推荐意见缺有效scheme_id或确认text')
    if sid in conflict_schemes and not item.get('conflict_note'):
        raise ValueError('推荐方案存在已检出冲突，须提供conflict_note说明，不能隐藏冲突')
    return {'status':'confirmed_professional_opinion','recommended_scheme_id':sid,'text':item['text'],
            'conflict_note':item.get('conflict_note',''),'evidence':source,
            'scope':'记录有来源的人工意见，不覆盖GIS冲突及待办状态'}
