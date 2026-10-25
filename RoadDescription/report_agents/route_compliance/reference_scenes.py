"""Combine nearby major objects into illustrated scenes, not inferred engineering spans."""
from shapely.geometry import LineString
from road_description.presentation import crossing_scenes
from road_description.figures import draw_map
from ..common.report import prose


def render_scenes(ctx,fact,events,out):
    blocks=[];figures=[];route=LineString(fact['path'])
    for index,group in enumerate(crossing_scenes(events),1):
        names='、'.join(dict.fromkeys(e['label'] for e in group))
        a,b=group[0]['start_m'],group[-1]['start_m'];station=f'K{a/1000:.3f}' if b-a<1 else f'K{a/1000:.3f}～K{b/1000:.3f}'
        blocks.append(prose(f'（{index}）{names}：图示交叉位置位于{station}。跨越方式、档距和净空待设计资料确认。'))
        if any(e.get('tunnel_status')=='tunnel' for e in group):
            blocks.append(prose('其中隧道段为平面投影相交，不直接等同露天道路架空跨越；洞口、埋深及塔基位置待核。'))
        xs=[e['xy'][0] for e in group];ys=[e['xy'][1] for e in group]
        focus=dict(group[0],label='主要跨越场景',xy=list(route.interpolate((a+b)/2).coords[0]))
        figure=draw_map(ctx.catalog,[fact],out/'figures'/f'scene_{index:02d}.png',names[:44],
            bounds=[min(xs)-900,min(ys)-900,max(xs)+900,max(ys)+900],focus=focus,overview=False)
        for e in group:
            figures.append(dict(figure,event_id=e['event_id'],scene_id=fact['id']+f'_scene_{index}',
                scene_event_ids=[x['event_id'] for x in group],source_uids=e['source_uids']))
        blocks.append({'type':'figure','path':figure['path'],'caption':f'图3.4.8-{index} {names}位置示意'})
    if blocks:blocks.insert(0,prose('邻近交点按同一图幅展示，不表示已确定为同一跨越档；普通乡道与补充小路明细保留在数据附件。'))
    return blocks,figures
