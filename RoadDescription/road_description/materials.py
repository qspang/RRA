"""Shared, version-bound image and PDF materials for all report agents."""
from pathlib import Path
from PIL import Image
from .io import file_hash


def approved_materials(config,root,facts,out,target,events=None,scheme_id=None):
    result=[];seen=set();by_id={s['id']:s for s in facts['schemes']}
    entries=[dict(p,_legacy=True,targets=['description','comparison']) for p in config.get('photos',[])]+config.get('materials',[])
    for item in entries:
        if target not in item.get('targets',['description','comparison','compliance']) or item.get('approved') is not True:continue
        identifier=item.get('id');sid=item.get('scheme_id')
        if scheme_id is not None and sid!=scheme_id:continue
        if not identifier or identifier in seen or sid not in by_id:raise ValueError('素材ID重复或方案ID无效')
        seen.add(identifier);fact=by_id[sid]
        if not item.get('_legacy') and item.get('route_geometry_hash')!=fact['geometry_hash']:
            raise ValueError('素材未绑定当前route_geometry_hash：'+identifier)
        valid={e['fact_id'] for e in fact['events']+fact['segments']+fact.get('terrain',[])}
        if target!='compliance' and (not item.get('fact_ids') or not set(item['fact_ids']).issubset(valid)):
            raise ValueError('素材须关联当前有效fact_ids：'+identifier)
        if target=='compliance':
            valid_events={e['event_id'] for e in (events or [])}
            if item.get('event_id') not in valid_events:raise ValueError('合规素材须关联当前event_id：'+identifier)
        source=(Path(root)/item['path']).resolve()
        if not source.is_file():raise ValueError('已确认素材文件不存在：'+source.name)
        title=item.get('caption')
        if not isinstance(title,str) or not title.strip():raise ValueError('素材缺图题：'+identifier)
        files=[]
        if source.suffix.lower()=='.pdf':
            import pymupdf
            with pymupdf.open(source) as pdf:
                pages=item.get('pages',list(range(1,len(pdf)+1)))
                if not pages or len(set(pages))!=len(pages):raise ValueError('PDF素材页码为空或重复')
                for page in pages:
                    if not isinstance(page,int) or not 1<=page<=len(pdf):raise ValueError('PDF素材页码越界')
                    dest=Path(out)/'materials'/f'{file_hash(source)[:16]}_{page}.png'
                    dest.parent.mkdir(parents=True,exist_ok=True)
                    pdf[page-1].get_pixmap(matrix=pymupdf.Matrix(2,2)).save(dest);files.append((dest,page))
        else:
            with Image.open(source) as im:im.verify()
            files=[(source,None)]
        for path,page in files:
            kind=item.get('kind','approved_photo')
            result.append({'id':identifier+(f'_p{page}' if page else ''),'scheme_id':sid,
                'path':str(path),'title':title+(f'（第{page}页）' if page else ''),
                'kind':kind,'fact_ids':item.get('fact_ids',[]),'event_id':item.get('event_id'),
                'source_file':str(source),'sha256':file_hash(source),'approved':True})
    return result
