"""Screen local-map chords for diverse test scenarios; actual planning must follow."""
import sys,json,itertools,math,argparse
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from report_agents.common.context import load_context
from shapely.geometry import LineString,Point
from shapely.ops import unary_union
import geopandas as gpd
from shapely import affinity
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--config',default='configs/config.rich-case.resolved.json')
parser.add_argument('--outside-ecology-endpoints',action='store_true')
parser.add_argument('--output',default='outputs/rich_case_20261025/straight_candidate_screen.json')
args=parser.parse_args()
c=load_context(args.config);cat=c.catalog
patterns={'highway':['高速'],'rail':['铁路'],'river':['河流'],'ecology':['生态保护红线','水源'],'power':['输电']}
frames={k:gpd.GeoDataFrame([f for f in cat.features if any(w in f['category'] for w in words)],geometry='geometry',crs=cat.crs) for k,words in patterns.items()}
forbidden=gpd.read_file(cat.root/'m2/forbidden_polygons.gpkg');forbidden.geometry=forbidden.geometry.map(lambda g:affinity.translate(g,xoff=cat.offset[0],yoff=cat.offset[1]))
points=[(x,y) for x in range(3000,40000,3000) for y in range(2000,17000,3000)]
points=[p for p in points if len(forbidden.sindex.query(Point(p),predicate='intersects'))==0]
if args.outside_ecology_endpoints:
 from report_agents.common.gis import is_ecology
 points=[p for p in points if not any(is_ecology(f) for f in cat.nearby(Point(p)))]
rows=[]
for a,b in itertools.combinations(points,2):
 length=math.dist(a,b)
 if not 7000<length<19000:continue
 line=LineString([a,b]);hit={};labels={}
 for k,fr in frames.items():
  ids=fr.sindex.query(line,predicate='intersects');hit[k]=len(ids);labels[k]=sorted(set(fr.iloc[ids]['label']))
 if not all(hit[k] for k in ['highway','river','ecology']):continue
 ids=forbidden.sindex.query(line,predicate='intersects');bad=sum(line.intersection(forbidden.iloc[i].geometry).length for i in ids)
 if bad>1500:continue
 score=20*sum(bool(hit[k]) for k in ['highway','river','ecology','rail'])+min(hit['power'],5)*2 -length/10000-bad/500
 rows.append(dict(start=a,end=b,length=length,hits=hit,labels=labels,forbidden_length=bad,score=score))
rows.sort(key=lambda x:-x['score']);target=Path(args.output);target.parent.mkdir(parents=True,exist_ok=True);target.write_text(json.dumps(rows,ensure_ascii=False,indent=2))
print(json.dumps(rows[:10],ensure_ascii=False,indent=2))
