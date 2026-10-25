"""Measured terrain only: never invent towers, conductors or clearance envelopes."""
from pathlib import Path
import matplotlib.pyplot as plt
import numpy as np


def crossing_profile(elevation, event, destination, radius=600):
    station = event['start_m']
    points = [p for p in elevation.get('profile', []) if abs(p['chainage_m']-station)<=radius]
    if sum(p['height_m'] is not None for p in points)<2:
        return None
    x = [p['chainage_m']/1000 for p in points]
    y = [p['height_m'] if p['height_m'] is not None else np.nan for p in points]
    fig, ax = plt.subplots(figsize=(8,3.0))
    ax.plot(x,y,color='#79583a',linewidth=1.5,label='DEM地面高程')
    ax.axvline(station/1000,color='#ba3b3b',linestyle='--',label='平面交点里程')
    ax.set_xlabel('路径里程 / km');ax.set_ylabel('DEM高程 / m')
    ax.set_title(event['label']+'附近地形剖面',fontsize=11)
    ax.grid(alpha=.25);ax.legend(fontsize=8)
    fig.text(.5,.015,'DEM采样示意；高程基准待核；不含杆塔、导线弧垂与净空设计',ha='center',fontsize=8)
    fig.tight_layout(rect=(0,.055,1,1))
    path=Path(destination);path.parent.mkdir(parents=True,exist_ok=True)
    fig.savefig(path,dpi=200);plt.close(fig)
    return {'path':str(path),'kind':'dem_terrain_profile','event_id':event['event_id'],
            'source':elevation['source'],'sha256':elevation['sha256'],
            'source_uids':event['source_uids'],'samples':points,
            'meaning':'地形采样剖面，非跨越设计断面；断面缺测保留空隙'}
