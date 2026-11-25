"""Read the generated Word body and keep reviewed paragraph revisions per job."""
import io
import json
import re
import tempfile
from pathlib import Path
from zipfile import ZipFile

from docx import Document
from docx.oxml.ns import qn
from docx.text.paragraph import Paragraph
from docx.table import Table
from flask import abort, jsonify, request, send_file

from .document import render_pdf
from .io import file_hash, read_json, write_json
from .model_runtime import model_call
from .terminology import check_document


def content(doc):
    blocks = []
    def images(el):
        return [Path(str(doc.part.related_parts[node.get(qn('r:embed'))].partname)).name
                for node in el.xpath('.//a:blip') if node.get(qn('r:embed'))]
    for idx, el in enumerate(doc.element.body):
        if el.tag == qn('w:p'):
            p = Paragraph(el, doc)
            for img in images(el):
                blocks.append(dict(type='image', file=img))
            text = p.text.strip()
            if text:
                heading = p.style.name.startswith('Heading') or re.match(r'^3\.\d[.\d]*\s+',text)
                kind = 'heading' if heading else 'caption' if re.match(r'^[图表]\s*3\.',text) else 'paragraph'
                blocks.append(dict(type=kind,id=str(idx),text=text))
        elif el.tag == qn('w:tbl'):
            rows = [[dict(text=cell.text,images=images(cell._tc)) for cell in row.cells] for row in Table(el, doc).rows]
            blocks.append(dict(type='table',rows=rows))
    return blocks


def register_documents(app, manager, groups):
    paths = {name: groups[key][1][i]+'.docx' for name,key,i in [
        ('description','description',0),('comparison','comparison',0),
        ('upper','compliance',0),('lower','compliance',1),('assembly','assembly',0)]}

    @app.route('/api/kml-jobs/<jid>/document/<kind>/<action>',methods=['GET','POST'])
    def document(jid,kind,action):
        if kind == 'assembly' and (request.method != 'GET' or action not in ('read', 'image')):
            abort(405)
        folder = manager.folder(jid)
        if kind not in paths or read_json(folder/'job.json').get('source')!='kml':
            abort(404)
        path = folder/'output'/paths[kind]
        if not path.is_file():
            abort(404)
        if action=='image' and request.method=='GET':
            name=request.args.get('name','')
            if not re.fullmatch(r'image\d+\.(?:png|jpe?g)',name,re.I):
                abort(404)
            with ZipFile(path) as z:
                entry='word/media/'+name
                if entry not in z.namelist():abort(404)
                return send_file(io.BytesIO(z.read(entry)),download_name=name)
        doc=Document(path)
        signature=file_hash(path)
        saved=folder/'revisions'/kind/(signature+'.json')
        def state():
            return read_json(saved) if saved.exists() else dict(version=0,edits={})
        draft=state()
        if request.method=='GET' and action=='read':
            blocks=content(doc)
            for b in blocks:
                if b.get('id') in draft['edits']:
                    b['text']=draft['edits'][b['id']]
            return jsonify(blocks=blocks,version=draft['version'],source=signature)
        if request.method=='GET' and action in ('docx','pdf'):
            for idx,text in draft['edits'].items():
                p=Paragraph(doc.element.body[int(idx)],doc)
                if p.runs:
                    p.runs[0].text=text
                    for run in p.runs[1:]:run.text=''
                else:p.add_run(text)
            with tempfile.TemporaryDirectory() as tmp:
                output=Path(tmp)/('审校版_'+path.name)
                check_document(doc)
                doc.save(output)
                if action=='pdf':
                    if render_pdf(output,manager.base.get('soffice',''))['status']!='completed':
                        return jsonify(error='审校版 PDF 排版失败'),503
                    output=output.with_suffix('.pdf')
                return send_file(io.BytesIO(output.read_bytes()),download_name=output.name,as_attachment=True)
        if request.method!='POST' or action not in ('save','suggest'):abort(404)
        body=request.get_json()
        if not isinstance(body,dict):raise ValueError('请求内容无效')
        idx=body.get('id')
        valid={b['id']:b['text'] for b in content(doc) if b['type']=='paragraph'}
        if not isinstance(idx,str) or idx not in valid:raise ValueError('请选择正文段落')
        text=body.get('text')
        if not isinstance(text,str) or not 0<len(text.strip())<=16000:raise ValueError('正文应为1至16000字符')
        if action=='save' and '交叉' in text:raise ValueError('请按实际关系使用跨越、穿越、临近或占用')
        with manager.lock:
            draft=state()
            if body.get('source')!=signature or body.get('version')!=draft['version']:
                return jsonify(error='此文档已更新，请保留编辑文字并刷新页面。'),409
            if action=='save':
                draft['edits'][idx]=text.strip()
                draft['version']+=1
                write_json(saved,draft)
                return jsonify(version=draft['version'])
        instruction=body.get('instruction')
        if not isinstance(instruction,str) or not 0<len(instruction.strip())<=1500:raise ValueError('请输入修改要求（最多1500字）')
        try:
            result,_=model_call(dict(manager.base['llm'],_purpose='paragraph_revision'),[
                {'role':'system','content':'你是输电设计报告编辑。依据原文和用户要求改写本段，不添加或改变工程量、地名、走向和审批结论；保留待核限定。仅返回JSON对象，text为改后段落。'},
                {'role':'user','content':json.dumps(dict(original=valid[idx],draft=text,instruction=instruction),ensure_ascii=False)}])
        except (ValueError,RuntimeError,OSError):
            return jsonify(error='模型接口未返回有效建议，当前草稿已保留，可重试。'),502
        proposal=result.get('text')
        if not isinstance(proposal,str) or not 0<len(proposal.strip())<=16000 or '交叉' in proposal:
            return jsonify(error='模型建议格式无效，请重试。'),502
        return jsonify(text=proposal)
