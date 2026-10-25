from road_description.presentation import major_event,representative_events,crossing_scenes
from road_description.figures import thematic_style


def test_small_roads_remain_outside_main_content_but_real_conflicts_are_retained():
    assert not major_event({'category':'乡道'})
    assert not major_event({'category':'道路（补充，等级待核）'})
    assert major_event({'category':'乡道','angle_status':'conflict'})
    assert major_event({'category':'输电线路500kV'})


def test_major_scene_grouping_does_not_drop_or_duplicate_events():
    events=[{'category':'高速公路','start_m':x,'event_id':str(x)} for x in [0,400,1800,2200,5000]]
    groups=crossing_scenes(events)
    assert [[x['start_m'] for x in g] for g in groups]==[[0,400,1800],[2200],[5000]]
    assert [x for g in groups for x in g]==events


def test_representative_images_exclude_local_roads_and_keep_ecology():
    events=[{'category':'乡道','start_m':0},{'category':'高速公路','start_m':1000},
            {'category':'生态保护红线','start_m':1300},{'category':'铁路','start_m':4000}]
    chosen=representative_events(events)
    assert len(chosen)==2 and any(x['category']=='生态保护红线' for x in chosen)
    assert all(x['category']!='乡道' for x in chosen)


def test_sensitive_area_themes_have_distinct_fill_and_hatch():
    values=[thematic_style(x) for x in ['生态保护红线','一级水源保护区','自然保护区缓冲区']]
    assert len({v['color'] for v in values})==3 and all(v['hatch'] for v in values)


def test_usage_counts_retry_tokens_without_double_counting_cached_subset():
    from tools.measure_report_run import usage_summary
    calls=[{'purpose':'generation','attempts':2,'usage':{'total_tokens':999},'usage_attempts':[
        {'prompt_tokens':100,'completion_tokens':10,'total_tokens':110,'prompt_tokens_details':{'cached_tokens':80}},
        {'prompt_tokens':200,'completion_tokens':20,'total_tokens':220}]}]
    t=usage_summary(calls)['totals']
    assert t['total_tokens']==330 and t['prompt_tokens']==300 and t['cached_prompt_tokens']==80
    assert t['http_attempts']==2 and t['attempts_without_usage']==0


def test_compliance_review_is_scoped_to_its_own_scheme():
    from road_description.quality_review import document_evidence
    evidence={'schemes':[{'id':'upper'},{'id':'lower'}],
              'compliance':{'upper':{'status':'pending'},'lower':{'status':'conflict'}}}
    e=document_evidence(evidence,'route_compliance_0')
    assert list(e['compliance'])==['upper'] and e['schemes']==[{'id':'upper'}]


def test_review_format_suggestion_is_preserved_as_minor(monkeypatch):
    import road_description.quality_review as q
    raw={'verdict':'needs_review','issues':[{'severity':'blocking','description':'事件数3与证据一致，但建议拆成两行'}]}
    monkeypatch.setattr(q,'model_call',lambda *args:({'decisions':[
        {'index':0,'classification':'suggestion_only','reason':'数据准确，只是格式建议'}]},{}))
    revised,trace=q.check_review_consistency({},raw)
    assert revised['issues'][0]['severity']=='minor' and trace['original_review']==raw
