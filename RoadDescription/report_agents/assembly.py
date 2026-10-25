"""Assemble complete reports with measured contents and both route schemes."""
import re
from pathlib import Path
import pymupdf
from .common.report import heading,prose,render_document
from road_description.io import read_json,write_json


def unified_blocks(comparison, compliance):
    """Keep 3.3 once; group both schemes under each compliance section."""
    blocks = list(comparison['blocks'])
    sections = {}
    introductions = []
    conclusions = []
    for sid, scheme in compliance['schemes'].items():
        current = introductions
        current.append(heading(scheme['name']+'核查依据与范围'))
        for block in scheme['blocks'][1:]:
            if block['type'] == 'heading':
                match = re.match(r'^(3\.\d+(?:\.\d+)*)\s', block['text'])
                if match:
                    key = match[1]
                    entry = sections.setdefault(key, {'title': block['text'], 'schemes': {}})
                    current = entry['schemes'].setdefault(sid, [])
                    continue
                if block['text'] == '本方案核查结论与待办':
                    current = conclusions
                    current.append(heading(scheme['name']+'核查结论与待办'))
                    continue
            current.append(block)
    blocks += [heading('路径合规性分析：核查依据与范围')] + introductions
    for key, section in sections.items():
        blocks.append(heading(section['title']))
        for sid, content in section['schemes'].items():
            if content:
                blocks.append(heading(compliance['schemes'][sid]['name']))
                blocks.extend(content)
    return blocks + [heading('南北方案核查结论与待办')] + conclusions


def assemble_all(ctx, comparison, compliance):
    blocks = unified_blocks(comparison, compliance)
    titles = [b['text'] for b in blocks if b['type']=='heading' and re.match(r'^3\.\d', b['text'])]
    path = ctx.output/'assembly'/'完整报告_路径描述_方案比选_南北方案合规分析.docx'
    def contents(pages):
        return [heading('目录'), prose('本册汇总三个Agent成果：3.3包含南北路径描述与方案比选；3.4.8—3.4.11及3.5按章节分别列出南北方案核查内容。未取得的调查、设计与审批资料仍按待补处理。')] + [
            prose(f"{title} {'·'*8} {pages.get(title, '—')}") for title in titles] + [{'type':'page_break'}]
    page_map = {}
    for _ in range(4):
        doc = render_document(ctx, path, contents(page_map)+blocks, '路径方案与南北方案合规完整报告', 1)
        if doc['pdf']['status'] != 'completed':
            raise ValueError('完整报告需要可用PDF渲染器')
        with pymupdf.open(doc['pdf']['path']) as pdf:
            text = [p.get_text().replace(' ','').replace('\n','') for p in pdf]
            measured = {title:next((i+1 for i, value in enumerate(text) if i>0 and title.replace(' ','') in value),None) for title in titles}
        if any(value is None for value in measured.values()):
            raise ValueError('完整报告目录无法定位章节')
        if measured == page_map:
            doc.update(scheme_id='all', contents=page_map)
            write_json(path.parent/'unified_result.json', {'document':doc, 'blocks':blocks})
            return doc
        page_map = measured
    raise ValueError('完整报告目录分页未收敛')


def assemble(ctx):
    opts=ctx.options.get('assembly',{})
    if not opts.get('enabled'):return None
    comparison=read_json(ctx.output/'route_comparison/result.json')
    compliance=read_json(ctx.output/'route_compliance/result.json')
    chosen=opts.get('scheme_id') or comparison['recommendation'].get('recommended_scheme_id')
    if chosen and chosen not in compliance['schemes']:raise ValueError('整册选择的方案无合规报告')
    schemes=[chosen] if chosen else list(compliance['schemes'])
    if opts.get('include_candidate_books') is False:schemes=[]
    out=ctx.output/'assembly';documents=[]
    for sid in schemes:
        result=compliance['schemes'][sid]
        blocks=comparison['blocks']+result['blocks']
        sections=[b['text'] for b in blocks if b['type']=='heading' and re.match(r'^3\.\d',b['text'])]
        def contents(pages):
            return [heading('目录'),prose('本册包含完整方案比选与'+result['name']+'合规章节。'+
                    ('按指定或已确认意见选择该方案编册；结论以正文证据状态为准。' if chosen else '本册为该候选方案的核查稿，尚未确定正式推荐方案。'))]+[
                    prose(f"{text} {'·'*8} {pages.get(text,'—')}") for text in sections]+[{'type':'page_break'}]
        path=out/(result['name']+'_路径方案与合规整册.docx')
        doc=render_document(ctx,path,contents({})+blocks,'路径方案与合规整册',1)
        if doc['pdf']['status']!='completed':raise ValueError('整册目录需要可用PDF渲染器')
        with pymupdf.open(doc['pdf']['path']) as pdf:
            page_map={text:next((i+1 for i,p in enumerate(pdf) if i>0 and text.replace(' ','') in p.get_text().replace(' ','').replace('\n','')),None) for text in sections}
        if any(v is None for v in page_map.values()):raise ValueError('整册目录无法定位章节页码')
        doc=render_document(ctx,path,contents(page_map)+blocks,'路径方案与合规整册',1)
        with pymupdf.open(doc['pdf']['path']) as pdf:
            if any(text.replace(' ','') not in pdf[page-1].get_text().replace(' ','').replace('\n','') for text,page in page_map.items()):
                raise ValueError('目录更新后分页改变，需复核')
        doc.update(scheme_id=sid,contents=page_map);documents.append(doc)
    documents.append(assemble_all(ctx, comparison, compliance))
    result={'status':'draft_pending_evidence','documents':documents,'selected_scheme':chosen,
            'sections':['3.3.1','3.3.2','3.3.3','3.4.8','3.4.9','3.4.10','3.4.11','3.5']}
    write_json(out/'result.json',result);return result
