"""Measure ordered administrative intervals in engineering chainage (metres)."""
from collections import defaultdict
from pathlib import Path

import pyogrio
from pyproj import Transformer
from shapely import affinity, make_valid
from shapely.geometry import LineString, Point

from .io import digest, file_hash

# Fields from the delivered Guangdong FileGDB. Preserve parent names for homonyms.
LAYERS = {
    'county': ('guangdong_adm_dist', ['province', 'city', 'district'], 'adcode'),
    'town': ('guangdong_adm_town', ['province', 'city', 'county', 'town'], None),
    'village': ('guangdong_adm_village', ['省级', '市级', '区县级', '乡镇级', 'NAME'], 'PAC'),
}


def line_parts(geom):
    if geom.geom_type == 'LineString' and not geom.is_empty:
        yield geom
    elif hasattr(geom, 'geoms'):
        for part in geom.geoms:
            yield from line_parts(part)


def measure_level(route, rows):
    """Use individual edges so retracing a line still yields distinct visits."""
    changes = defaultdict(list)
    changes[0.0] = []
    changes[route.length] = []
    index = rows.sindex
    offset = 0.0
    for a, b in zip(route.coords, list(route.coords)[1:]):
        edge = LineString([a, b])
        for idx in index.query(edge, predicate='intersects'):
            row = rows.iloc[idx]
            for line in line_parts(edge.intersection(row.geometry).difference(row.geometry.boundary)):
                lo, hi = sorted(edge.project(Point(pt)) for pt in (line.coords[0], line.coords[-1]))
                if hi-lo < 1e-6:
                    continue
                label = row['label']
                changes[round(offset+lo, 6)].append((label, 1))
                changes[round(offset+hi, 6)].append((label, -1))
        offset += edge.length
    active = defaultdict(int)
    runs = []
    previous = 0.0
    for station in sorted(changes):
        if station-previous > 1e-6:
            labels = sorted(x for x, n in active.items() if n > 0)
            if runs and runs[-1]['labels'] == labels:
                runs[-1]['end_m'] = station
            else:
                runs.append(dict(start_m=previous, end_m=station, labels=labels))
        for label, delta in changes[station]:
            active[label] += delta
        previous = station
    unresolved = sum(s['end_m']-s['start_m'] for s in runs if len(s['labels']) != 1)
    return {'runs': runs, 'unresolved_m': unresolved, 'complete': unresolved < 1e-5}


def guangdong_profile(route, catalog, path):
    path = Path(path)
    projected = affinity.translate(route, xoff=-catalog.offset[0], yoff=-catalog.offset[1])
    profile = {}
    if 'admin_boundary_sha256' not in catalog.provenance:
        catalog.provenance['admin_boundary_sha256'] = digest([(p.name, file_hash(p)) for p in sorted(path.glob('*.gdbtable'))])
    for level, (layer, names, code) in LAYERS.items():
        crs = pyogrio.read_info(path, layer=layer)['crs']
        bbox = Transformer.from_crs(catalog.crs, crs, always_xy=True).transform_bounds(*projected.bounds)
        rows = pyogrio.read_dataframe(path, layer=layer, columns=names+([code] if code else []), bbox=bbox, fid_as_index=True).to_crs(catalog.crs)
        records = {}
        labels = []
        for fid, row in rows.iterrows():
            parts = [str(row[n]).strip() if row[n] is not None else '' for n in names]
            label = '/'.join(parts)
            labels.append(label)
            records.setdefault(label, dict(name=parts[-1], parents=parts[:-1], code=str(row[code]) if code else None, fids=[]))['fids'].append(int(fid))
        rows['label'] = labels
        rows = rows[rows['label'].map(lambda key: bool(records[key]['name']))].copy()
        rows.geometry = rows.geometry.map(make_valid)
        measured = measure_level(projected, rows)
        used = {label for run in measured['runs'] for label in run['labels']}
        profile[level] = dict(**measured, layer=layer, areas={key:records[key] for key in sorted(used)})
    return profile


def area_at(level, station):
    for run in level['runs']:
        if run['start_m'] <= station < run['end_m'] and len(run['labels']) == 1:
            return level['areas'][run['labels'][0]]['name']
    return ''


def outline(level):
    return '、'.join(dict.fromkeys(level['areas'][run['labels'][0]]['name'] for run in level['runs'] if len(run['labels']) == 1))


def description_entries(profile, scheme_id):
    entries = []
    def add(text):
        identifier = f'{scheme_id}_ADM{len(entries)+1:02d}'
        entries.append(dict(id=identifier, text=text, fact_ids=[identifier], group='route'))

    for level, title in [('county', '县区'), ('town', '乡镇'), ('village', '村级')]:
        layer = profile[level]
        phrases = []
        for span in layer['runs']:
            labels = span['labels']
            location = '属地待核'
            if len(labels) == 1:
                area = layer['areas'][labels[0]]
                location = ''.join(area['parents'][-1:] + [area['name']]) if level != 'village' else area['name']
            elif labels:
                location = '边界重叠，涉及'+'、'.join(layer['areas'][key]['name'] for key in labels)
            phrases.append(f"K{span['start_m']/1000:.3f}～K{span['end_m']/1000:.3f} {location}")
        if layer['complete'] and level in ('county', 'town'):
            route_text = []
            for index, span in enumerate(layer['runs']):
                area = layer['areas'][span['labels'][0]]
                place = ''.join(area['parents'][-1:] + [area['name']])
                distance = (span['end_m'] - span['start_m']) / 1000
                if index == 0:
                    route_text.append(f'线路自{place}境内起步，在该{title}范围内走线约{distance:.3f}公里')
                else:
                    route_text.append(f"至K{span['start_m']/1000:.3f}进入{place}，境内走线约{distance:.3f}公里")
            add('，'.join(route_text)+'。')
        elif phrases:
            add(f'按{title}界图层，从起点沿线路依次经过以下区段：'+'，'.join(phrases)+'。')
    add('以上里程按路线中心线与各级行政界线分别量取。村名表示经过该村行政范围，村界与上级界线的位置以各自图层为准。')
    return entries
