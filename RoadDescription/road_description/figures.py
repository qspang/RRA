"""Reproducible map figures, with optional existing Tianditu satellite basemap."""
import math
from pathlib import Path

import geopandas as gpd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager
import numpy as np
from PIL import Image
from pyproj import Transformer
from shapely.geometry import LineString, box

from .facts import line_parts
from .presentation import representative_events


FONT='/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc'
if Path(FONT).exists():
    font_manager.fontManager.addfont(FONT)
    plt.rcParams['font.family']=font_manager.FontProperties(fname=FONT).get_name()
plt.rcParams['axes.unicode_minus']=False


def satellite_background(ax,bounds,catalog,key,cache,zoom=12):
    if not key:
        return False
    import io
    import requests
    import rasterio
    from rasterio.warp import reproject,Resampling
    x0,y0,x1,y1=bounds;ox,oy=catalog.offset
    transform=Transformer.from_crs(catalog.crs,3857,always_xy=True)
    corners=[transform.transform(x-ox,y-oy) for x,y in [(x0,y0),(x0,y1),(x1,y0),(x1,y1)]]
    half=20037508.342789244
    while zoom>=7:
        size=2*half/2**zoom
        tx0=int((min(x for x,y in corners)+half)/size);tx1=int((max(x for x,y in corners)+half)/size)
        ty0=int((half-max(y for x,y in corners))/size);ty1=int((half-min(y for x,y in corners))/size)
        if (tx1-tx0+1)*(ty1-ty0+1)<=36:break
        zoom-=1
    mosaic=Image.new('RGB',((tx1-tx0+1)*256,(ty1-ty0+1)*256))
    cache=Path(cache);cache.mkdir(parents=True,exist_ok=True)
    try:
        for x in range(tx0,tx1+1):
            for y in range(ty0,ty1+1):
                prefix='img_cia' if key.startswith('browser-labels:') else 'img'
                path=cache/f'{prefix}_{zoom}_{x}_{y}.jpg'
                if path.exists():
                    tile=Image.open(path).convert('RGB')
                elif key.startswith(('browser:','browser-labels:')):
                    from .browser_basemap import tile as browser_tile
                    tile=browser_tile(key.split(':',1)[1],zoom,x,y,annotations=key.startswith('browser-labels:'));tile.save(path)
                else:
                    r=requests.get('https://t0.tianditu.gov.cn/img_w/wmts',params={
                        'SERVICE':'WMTS','REQUEST':'GetTile','VERSION':'1.0.0','LAYER':'img',
                        'STYLE':'default','TILEMATRIXSET':'w','TILEMATRIX':zoom,
                        'TILEROW':y,'TILECOL':x,'FORMAT':'tiles','tk':key},timeout=12)
                    r.raise_for_status();tile=Image.open(io.BytesIO(r.content)).convert('RGB');tile.save(path)
                mosaic.paste(tile,((x-tx0)*256,(y-ty0)*256))
        src=np.asarray(mosaic).transpose(2,0,1)
        height=700;width=max(300,int(height*(x1-x0)/(y1-y0)))
        dst=np.zeros((3,height,width),dtype=np.uint8)
        reproject(src,dst,src_transform=rasterio.transform.from_origin(tx0*size-half,half-ty0*size,size/256,size/256),
            src_crs='EPSG:3857',dst_transform=rasterio.transform.from_bounds(x0-ox,y0-oy,x1-ox,y1-oy,width,height),
            dst_crs=catalog.crs,resampling=Resampling.bilinear)
        ax.imshow(dst.transpose(1,2,0),extent=bounds_to_extent(bounds),origin='upper',zorder=0)
        return True
    except Exception:
        # Fail closed to vector basemap; never print secret-bearing tile URLs.
        return False


def bounds_to_extent(b):return (b[0],b[2],b[1],b[3])


def category_style(category):
    if '河流' in category:return '#7bbbd4', '#317da5', .5
    if '高速' in category:return 'none','#c78c28',1.2
    if any(k in category for k in ('国道','省道','县道','乡道','道路')):return 'none','#ba9b68',.7
    if '输电' in category:return 'none','#8f68a7',.7
    if '保护' in category or '公园' in category:return '#d7e7bc','#719557',.4
    if '禁止' in category:return '#e2c7bf','#a77a70',.5
    if '建筑' in category:return '#bdb7ac','#a49b8d',.35
    return '#f0ede3','#d6d1c4',.2


def thematic_style(category):
    if '水源' in category:return {'color':'#1d91ff','hatch':'\\\\','label':'水源保护区'}
    if '红线' in category:return {'color':'#35d324','hatch':'////','label':'生态保护红线'}
    if any(w in category for w in ('保护','公园','湿地')):return {'color':'#ffb000','hatch':'xx','label':'自然保护范围'}
    if '矿' in category:return {'color':'#d64fd8','hatch':'..','label':'矿区'}
    return None


def draw_map(catalog,schemes,path,title,bounds=None,focus=None,key='',cache=None,overview=False,show_local_roads=False):
    key=key or getattr(catalog,'basemap_key','')
    cache=getattr(catalog,'basemap_cache',None) or cache
    routes=[LineString(s['path']) for s in schemes]
    if bounds is None:
        x0=min(r.bounds[0] for r in routes);y0=min(r.bounds[1] for r in routes)
        x1=max(r.bounds[2] for r in routes);y1=max(r.bounds[3] for r in routes)
        padding=max(800,(x1-x0)*.06);bounds=[x0-padding,y0-padding,x1+padding,y1+padding]
    x0,y0,x1,y1=bounds
    ratio=1.9 if overview else 1.35
    width=x1-x0;height=y1-y0
    if width/height<ratio:
        extra=(height*ratio-width)/2;x0-=extra;x1+=extra
    else:
        extra=(width/ratio-height)/2;y0-=extra;y1+=extra
    bounds=[x0,y0,x1,y1]
    fig,ax=plt.subplots(figsize=(9.2,5.3) if overview else (5.1,4.1),dpi=220)
    ax.set_facecolor('#f7f5ef')
    zoom=15 if x1-x0<6000 else 14 if x1-x0<16000 else 12
    sat=satellite_background(ax,bounds,catalog,key,cache,zoom=zoom) if key else False
    window=box(*bounds)
    nearby=catalog.nearby(window)
    # Keep relevant themes legible; land parcels remain background evidence, not visual noise.
    grouped={};highlighted=[]
    for feature in nearby:
        cat=feature['category']
        if not show_local_roads and '道路（补充' in cat:continue
        if cat in ('基本农田','一般耕地','UNKNOWN') or (cat=='山谷' and (focus or {}).get('category')!='山谷') or (not show_local_roads and cat in ('乡道','县道')):
            continue
        grouped.setdefault(cat,[]).append(feature['geometry'].intersection(window))
        if overview and thematic_style(cat) and feature['geometry'].geom_type in ('Polygon','MultiPolygon'):
            highlighted.append(feature)
    for cat,geoms in grouped.items():
        geoms=[g for g in geoms if not g.is_empty]
        if not geoms:continue
        face,edge,lw=category_style(cat)
        layer=gpd.GeoSeries(geoms)
        polygons=layer[layer.geom_type.isin(['Polygon','MultiPolygon'])]
        lines=layer[layer.geom_type.isin(['LineString','MultiLineString'])]
        theme=thematic_style(cat) if overview else None
        if len(polygons):
            if theme:
                polygons.plot(ax=ax,facecolor=theme['color'],edgecolor=theme['color'],linewidth=1.1,alpha=.32,zorder=2)
                polygons.plot(ax=ax,facecolor='none',edgecolor=theme['color'],linewidth=.8,hatch=theme['hatch'],alpha=.85,zorder=3)
            else:polygons.plot(ax=ax,facecolor=face,edgecolor=edge,linewidth=lw,alpha=.28 if sat else .65,zorder=1)
        if len(lines):lines.plot(ax=ax,color=edge,linewidth=lw,alpha=.8,zorder=2)
    for scheme,route in zip(schemes,routes):
        color='#c83732' if scheme['name']=='北方案' else '#176aa2'
        xs,ys=route.xy
        ax.plot(xs,ys,color='white',linewidth=3.8,zorder=5)
        ax.plot(xs,ys,color=color,linewidth=2.1,label=scheme['name'],zorder=6)
    area_labels=[]
    if overview:
        import textwrap
        unique={}
        for f in sorted(highlighted,key=lambda f:min(f['geometry'].distance(r) for r in routes)):
            unique.setdefault((f['category'],f['label']),f)
        labelled=[]
        for f in list(unique.values())[:8]:
            pt=f['geometry'].intersection(window).representative_point()
            labelled.append((f,pt,0 if pt.x<(x0+x1)/2 else 1))
        number=0
        for side in (0,1):
            items=sorted([v for v in labelled if v[2]==side],key=lambda v:-v[1].y)
            for row,(f,pt,_) in enumerate(items):
                number+=1;label=f"{number}. "+f['label'];label='\n'.join(textwrap.wrap(label,18))
                y=.83-row*(.5/max(1,len(items)-1))
                ax.annotate(label,xy=(pt.x,pt.y),xytext=(.02 if side==0 else .98,y),
                    textcoords='axes fraction',ha='left' if side==0 else 'right',va='center',fontsize=7,
                    color='#9b1b16',bbox=dict(boxstyle='round,pad=.25',fc='white',ec=thematic_style(f['category'])['color'],alpha=.95),
                    arrowprops=dict(arrowstyle='-',color=thematic_style(f['category'])['color'],lw=1),zorder=9)
                area_labels.append({'uid':f['uid'],'label':f['label'],'category':f['category']})
    route=routes[0]
    for text,p in [('起点',route.coords[0]),('终点',route.coords[-1])]:
        if window.contains(__import__('shapely').geometry.Point(p)):
            ax.scatter(*p,s=28,color='#222',zorder=8)
            ax.annotate(text,p,xytext=(5,8),textcoords='offset points',fontsize=9,
                        bbox=dict(facecolor='white',edgecolor='none',alpha=.8),zorder=9)
    if focus:
        p=focus.get('xy')
        if p:
            ax.scatter(*p,s=80,facecolors='none',edgecolors='#d02323',linewidths=1.4,zorder=9)
            label=focus['label']
            if len(label)>18:label=label[:18]+'…'
            ax.annotate(label,p,xytext=(8,32),textcoords='offset points',fontsize=8,
                        arrowprops=dict(arrowstyle='-',color='#555',linewidth=.6),
                        bbox=dict(facecolor='white',edgecolor='#aaa',alpha=.95),zorder=10)
    if overview and not highlighted:
        # Labels are explicit M1 attributes only; not OCR guesses from basemap.
        seen=set();positions=[]
        labels=sorted(nearby,key=lambda f:(0 if any(w in f['category'] for w in ('生态','水源','自然保护')) else 1,min(r.distance(f['geometry']) for r in routes)))
        for f in labels:
            label=f['name'] or f['category']
            if label in seen or not any(k in f['category'] for k in ('高速','国道','河流','生态','水源','自然保护')):continue
            p=f['geometry'].intersection(window).representative_point()
            if any(abs(p.x-q[0])<(x1-x0)*.18 and abs(p.y-q[1])<(y1-y0)*.10 for q in positions):continue
            label='\n'.join(label[i:i+14] for i in range(0,len(label),14))
            ax.annotate(label,p.coords[0],fontsize=6.5,color='#354735',zorder=4,ha='center',
                        bbox=dict(facecolor='white',edgecolor='#aaa',alpha=.85));seen.add(f['name'] or f['category']);positions.append((p.x,p.y))
            if len(seen)>=7:break
    ax.set_xlim(x0,x1);ax.set_ylim(y0,y1);ax.set_aspect('equal')
    # True north in the working CRS at the map center (accounts for grid convergence).
    cx,cy=(x0+x1)/2,(y0+y1)/2;ox,oy=catalog.offset
    lon,lat=catalog.to_lonlat.transform(cx-ox,cy-oy)
    reverse=Transformer.from_crs(4326,catalog.crs,always_xy=True)
    nx,ny=reverse.transform(lon,lat+.01);dx,dy=nx+ox-cx,ny+oy-cy
    norm=math.hypot(dx,dy);height=y1-y0
    base=(x0+.06*(x1-x0),y1-.17*height)
    tip=(base[0]+dx/norm*.11*height,base[1]+dy/norm*.11*height)
    ax.annotate('',xy=tip,xytext=base,arrowprops=dict(arrowstyle='-|>',color='#333'),zorder=10)
    ax.text(tip[0],tip[1]+.015*height,'N',ha='center',fontsize=10,
            bbox=dict(facecolor='white',edgecolor='none',alpha=.8),zorder=10)
    scale=10**math.floor(math.log10((x1-x0)/5))
    if scale*2<(x1-x0)/5:scale*=2
    sx=x0+(x1-x0)*.04;sy=y0+(y1-y0)*.07
    ax.plot([sx,sx+scale],[sy,sy],color='#222',linewidth=2,zorder=10)
    ax.text(sx+scale/2,sy+(y1-y0)*.025,f'{scale/1000:g} km',ha='center',fontsize=8,
            bbox=dict(facecolor='white',edgecolor='none',alpha=.8),zorder=10)
    ax.set_xticks([]);ax.set_yticks([])
    handles,labels=ax.get_legend_handles_labels()
    if overview:
        from matplotlib.lines import Line2D
        from matplotlib.patches import Patch
        themes={thematic_style(f['category'])['label']:thematic_style(f['category']) for f in highlighted}
        for label,theme in themes.items():
            handles.append(Patch(facecolor=theme['color'],edgecolor=theme['color'],alpha=.55,hatch=theme['hatch']));labels.append(label)
        for words,label,color in [(('高速','国道','省道'),'道路','#c78c28'),(('河流',),'河流/水域','#317da5')]:
            if any(any(w in c for w in words) for c in grouped):handles.append(Line2D([0],[0],color=color,lw=2));labels.append(label)
    ax.legend(handles,labels,loc='lower right',fontsize=7,framealpha=.9)
    ax.set_title(title,fontsize=11,pad=9)
    source='影像：天地图；地物与线路：本次规划数据' if sat else '地物矢量示意；来源：本次规划地图（非现场照片）'
    if sat and key.startswith('browser-labels:'):source='影像/底图注记：天地图；专题地物及线路：本次数据'
    fig.text(.5,.02,source,ha='center',fontsize=7,color='#555')
    fig.subplots_adjust(left=.03,right=.97,top=.9,bottom=.07)
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    if getattr(catalog,'report_style','detailed')=='reference':
        path=path.with_suffix('.jpg');fig.savefig(path,dpi=240,pil_kwargs={'quality':92,'subsampling':0})
    else:fig.savefig(path,dpi=240)
    plt.close(fig)
    return {'path':str(path),'title':title,'kind':'satellite_map' if sat else 'vector_map','bounds':bounds,'source':source,'highlighted_area_count':len(highlighted),'area_labels':area_labels}


def generate_figures(catalog,facts,out,key=''):
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    compact=getattr(catalog,'report_style','detailed')=='reference'
    routes=[LineString(f['path']) for f in facts['schemes']]
    region=[min(r.bounds[0] for r in routes)-6000,min(r.bounds[1] for r in routes)-6000,
            max(r.bounds[2] for r in routes)+6000,max(r.bounds[3] for r in routes)+6000]
    figures=[draw_map(catalog,facts['schemes'],out/'overview.png','南、北方案路径及周边地物分布',bounds=region,key=key,cache=out/'tiles',overview=True)]
    if figures[0]['kind']=='vector_map':key=''
    for scheme in facts['schemes']:
        chosen=representative_events(scheme['events']) if compact else list(scheme['events'])+list(scheme.get('terrain',[]))
        for segment in ([] if compact else scheme['segments']):
            mid=(segment['start_m']+segment['end_m'])/2
            if any(abs(mid-p['start_m'])<1000 for p in chosen):continue
            route=LineString(scheme['path'])
            chosen.append({'start_m':mid,'xy':list(route.interpolate(mid).coords[0]),
                           'label':f"向{segment['direction']}走线区段",'fact_id':segment['fact_id']})
        scheme['figure_ids']=[]
        for i,event in enumerate(sorted(chosen,key=lambda e:e['start_m'])):
            x,y=event['xy'];radius=1300
            title=f"{event['label']}附近（K{event['start_m']/1000:.1f}）"
            if len(title)>32:title=event['label'][:20]+f"（K{event['start_m']/1000:.1f}）"
            item=draw_map(catalog,[scheme],out/f"{scheme['id']}_{i+1}.png",title,
                bounds=[x-radius,y-radius,x+radius,y+radius],focus=event,key=key,cache=out/'tiles',show_local_roads=True)
            item.update(id=f"{scheme['id']}_IMG{i+1}",scheme_id=scheme['id'],fact_ids=[event['fact_id']])
            scheme['figure_ids'].append(item['id']);figures.append(item)
    figures[0]['id']='overview'
    return figures
