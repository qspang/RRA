"""Reference report editorial policy; full GIS evidence is never discarded."""
def reference_style(config):
    return config.get('report_style')=='reference'


def major_event(event):
    category=event.get('category','')
    return (bool(event.get('design')) or event.get('angle_status')=='conflict' or
            any(w in category for w in ('高速','国道','省道','县道','铁路','河流','输电','生态','保护','水源','湿地','公园','矿')))


def representative_events(events,limit=6):
    selected=[]
    # Cover distinct themes before filling nearby examples of the same theme.
    priority=lambda e: 0 if any(w in e.get('category','') for w in ('生态','保护','水源')) else 1 if '高速' in e.get('category','') else 2 if any(w in e.get('category','') for w in ('铁路','河流')) else 3
    for e in sorted([e for e in events if major_event(e)],key=lambda e:(priority(e),e['start_m'])):
        if len(selected)>=limit:break
        if any(abs(e['start_m']-x['start_m'])<800 for x in selected):continue
        selected.append(e)
    return sorted(selected,key=lambda e:e['start_m'])


def crossing_scenes(events,max_span_m=1800):
    groups=[]
    for e in sorted([e for e in events if major_event(e)],key=lambda e:e['start_m']):
        if not groups or e['start_m']-groups[-1][0]['start_m']>max_span_m:groups.append([])
        groups[-1].append(e)
    return groups
