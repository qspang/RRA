"""Additional measurements from existing weather zones and DEM, not survey guesses."""
import math
import geopandas as gpd
from shapely import affinity
from shapely.geometry import LineString
from shapely.ops import unary_union
from road_description.io import file_hash


def weather_zones(ctx,fact):
    path=ctx.catalog.root/'m2/wind_ice_zones.gpkg'
    if not path.exists():return {'status':'missing','records':[],'reason':'缺风冰区图层'}
    key='weather_vector'
    if key not in ctx.cache:
        frame=gpd.read_file(path).to_crs(ctx.catalog.crs)
        frame.geometry=frame.geometry.map(lambda g:affinity.translate(g,xoff=ctx.catalog.offset[0],yoff=ctx.catalog.offset[1]))
        ctx.cache[key]=frame
    frame=ctx.cache[key];route=LineString(fact['path']);groups={};all_cuts=[]
    def number(value,positive=False):
        try:
            value=float(value)
            return value if math.isfinite(value) and (value>0 if positive else value>=0) else None
        except (ValueError,TypeError):return None
    for i in frame.sindex.query(route,predicate='intersects'):
        row=frame.iloc[i];cut=route.intersection(row.geometry)
        if cut.length<=.01:continue
        wind=number(row.get('wi_wind_ms'),True);ice=number(row.get('wi_ice_mm'))
        groups.setdefault((wind,ice),[]).append(cut);all_cuts.append(cut)
    records=[{'wind_ms':w,'ice_mm':i,'length_m':unary_union(cuts).length,
              'percent':unary_union(cuts).length/route.length*100} for (w,i),cuts in groups.items()]
    covered=unary_union(all_cuts).length if all_cuts else 0
    return {'status':'measured' if route.length-covered<1 else 'partial','records':records,
            'covered_m':covered,'uncovered_m':max(0,route.length-covered),'source':str(path),'sha256':file_hash(path),
            'scope':'五十年一遇风区与冰区原始预处理字段；零风速/无值不解释为无风，非当前天气预报'}


def relief(elevation):
    ascent=descent=longest=0.;grades=[];covered=0.
    points=elevation.get('profile',[])
    for a,b in zip(points,points[1:]):
        if a['height_m'] is None or b['height_m'] is None:continue
        distance=b['chainage_m']-a['chainage_m']
        if distance<=0:continue
        diff=b['height_m']-a['height_m'];ascent+=max(0,diff);descent+=max(0,-diff)
        grades.append(abs(diff)/distance*100);covered+=distance
    return {'status':'measured' if grades else 'missing','ascent_m':ascent,'descent_m':descent,
            'max_sample_grade_percent':max(grades) if grades else None,'covered_m':covered,
            'scope':'按DEM相邻有效采样点计算沿线高程变化；不跨越NoData，不等同地表坡度或正式丘陵/山地分类'}
