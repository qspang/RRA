"""Material gaps, artifact hashes, and consistency gates for every run."""
from pathlib import Path
from road_description.io import read_json,write_json,file_hash


def delivery(ctx,state):
    records=[];gaps=[];checks=[]
    for agent,info in state['results'].items():
        result=read_json(info['result_json'])
        for doc in info['documents']:
            path=Path(doc['docx']);records.append({'agent':agent,'docx':str(path),'sha256':file_hash(path),'pdf':doc['pdf']})
            checks.append({'check':agent+' PDF渲染','passed':doc['pdf']['status']=='completed'})
        if agent=='route_compliance':
            for sid,scheme in result['schemes'].items():
                gaps.extend({'agent':agent,'scheme_id':sid,'reason':text,'kind':'external_evidence_or_review'} for text in scheme['missing'])
                maps={f.get('event_id') for f in scheme['figures'] if f['kind'] in ('vector_map','satellite_map')}
                checks.append({'check':sid+'正文主要跨越均有图（完整事件保留JSON）','passed':all(e['event_id'] in maps for e in scheme['crossings'] if e.get('presentation_included',True))})
        elif agent=='route_comparison':
            gaps.extend({'agent':agent,'reason':text,'kind':'external_evidence_or_review'} for text in result['missing'])
        else:
            for name,items in result['missing'].items():
                gaps.extend({'agent':agent,'scheme':name,'reason':text,'kind':'external_evidence'} for text in items)
            if result['photos_pending']:gaps.append({'agent':agent,'reason':'未提供已确认现场照片','kind':'external_evidence'})
    for item in state.get('assembly',{}).get('documents',[]):
        records.append({'agent':'assembly','docx':item['docx'],'sha256':file_hash(item['docx']),'pdf':item['pdf']})
    available=ctx.catalog.coverage()
    categories={'林业':['林地','林木','树种'],'矿产':['矿'],'军事':['军事'],'地形':['山谷'],'生态':['保护','水源','公园','湿地']}
    coverage={topic:{'status':'present_scope_unconfirmed' if any(any(w in k for w in words) for k in available) else 'not_provided',
                     'feature_count':sum(v['count'] for k,v in available.items() if any(w in k for w in words))}
              for topic,words in categories.items()}
    result={'status':'passed' if all(c['passed'] for c in checks) else 'needs_fix','checks':checks,'artifacts':records,
            'missing':gaps,'coverage':coverage,'provenance':ctx.provenance,
            'scope':'技术输出完整性与资料缺口；不将待补资料视为代码失败或正式审批通过'}
    write_json(ctx.source/'delivery_manifest.json',result)
    lines=['本轮输出与资料缺口','技术输出状态：'+result['status'],'',*('文件：'+r['docx'] for r in records),'','仍需资料/复核：']
    lines.extend(f"{i}. {g['agent']} {g.get('scheme_id',g.get('scheme',''))}：{g['reason']}" for i,g in enumerate(gaps,1))
    (ctx.source/'本轮资料缺口.txt').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    if result['status']!='passed':raise ValueError('交付完整性检查未通过，见delivery_manifest.json')
    return result
