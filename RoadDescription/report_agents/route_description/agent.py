from road_description.io import read_json, file_hash


class RouteDescriptionAgent:
    manifest = {'id':'route_description','version':'0.3.0','name':'路径描述Agent',
                'sections':['3.3.1','3.3.2'],'depends_on':[],
                'inputs':['南北方案最终响应','原始地物与规则','可选已确认照片'],
                'outputs':['Word/PDF','路线事实JSON','地图及照片清单','资料缺口']}

    def run(self, ctx):
        # Reuse the same implementation as the original CLI. Standalone operation
        # explicitly disables nested plugin dispatch to prevent recursion.
        if not ctx.cache.get('description_ready'):
            from road_description.pipeline import run
            run(ctx.cache['config_path'], description_only=True)
        validation=read_json(ctx.source/'validation.json')
        facts=read_json(ctx.source/'route_facts.json')
        docx=ctx.source/'路径方案描述_联调样章.docx'
        return {'status':'draft_pending_evidence',
                'documents':[{'docx':str(docx),'pdf':validation['pdf'],'sha256':file_hash(docx)}],
                'facts':facts,'narratives':read_json(ctx.source/'narrative.json'),
                'figures':read_json(ctx.source/'figure_manifest.json'),
                'missing':validation['missing'],'photos_pending':validation['photos_pending']}
