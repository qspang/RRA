from pathlib import Path
from road_description.io import write_json
from road_description.service import absolute_config
from tools.check_setup import check


def test_setup_reports_missing_inputs_without_exposing_credentials(tmp_path):
    secret = 'test-private-value-must-not-appear'
    path = tmp_path/'config.local.json'
    write_json(path, {'dataset':'roaddata/preprocessed', 'reference_pdf':'roaddata/reference/reference.pdf',
                     'llm':{'enabled':True,'api_base':'https://private-provider.invalid/v1',
                            'model_id':'test-model','credential_file':'.env','api_key_env':'PRIVATE_TEST_KEY'}})
    (tmp_path/'.env').write_text('PRIVATE_TEST_KEY='+secret)
    result = check(path)
    assert result['status']=='failed'
    assert any(x['item']=='dataset' and x['status']=='error' for x in result['checks'])
    assert any(x['item']=='llm凭据' and x['status']=='pass' for x in result['checks'])
    assert secret not in str(result) and 'private-provider.invalid' not in str(result)


def test_service_rebases_data_paths_but_preserves_executable_lookup(tmp_path):
    config = {'dataset':'roaddata/preprocessed','reference_pdf':'roaddata/reference/reference.pdf',
              'soffice':'soffice', 'agents':{'dem_path':'roaddata/dem/terrain.tif','planner_source':None},
              'supplemental_layers':[{'path':'roaddata/source/ecology.gdb'}],
              'llm':{'credential_file':'.env'}}
    resolved = absolute_config(config, tmp_path)
    assert resolved['soffice']=='soffice'
    assert resolved['dataset']==str(tmp_path/'roaddata/preprocessed')
    assert resolved['agents']['dem_path']==str(tmp_path/'roaddata/dem/terrain.tif')
    assert resolved['supplemental_layers'][0]['path']==str(tmp_path/'roaddata/source/ecology.gdb')
    assert resolved['llm']['credential_file']==str(tmp_path/'.env')
    assert config['dataset']=='roaddata/preprocessed'
    config['soffice']='tools/soffice_local.sh'
    assert absolute_config(config,tmp_path)['soffice']==str(tmp_path/'tools/soffice_local.sh')


def test_configs_directory_root_survives_service_job_relocation(tmp_path):
    from road_description.io import config_root, read_json
    config_path = tmp_path/'configs/config.local.json'
    write_json(config_path, {'project_root':'..','dataset':'roaddata/preprocessed',
                            'llm':{'credential_file':'.env'},'output_dir':'outputs/local_run'})
    assert config_root(config_path)==tmp_path
    absolute = absolute_config(read_json(config_path), config_root(config_path))
    job_config = tmp_path/'outputs/jobs/job1/config.json'
    write_json(job_config, absolute)
    assert config_root(job_config)==tmp_path
    assert absolute['dataset']==str(tmp_path/'roaddata/preprocessed')
    assert absolute['llm']['credential_file']==str(tmp_path/'.env')
    legacy = tmp_path/'legacy.json'
    write_json(legacy,{})
    assert config_root(legacy)==tmp_path


def test_case_illustration_moves_with_notes(tmp_path):
    from report_agents.assembly import load_section_notes
    folder = tmp_path/'roaddata/cases/dapu'
    folder.mkdir(parents=True)
    image = folder/'example.png'
    image.touch()
    write_json(folder/'notes.json', {'3.3.1': [
        {'type': 'figure', 'caption': '重要交叉跨越', 'path': image.name},
    ]})
    block = load_section_notes(tmp_path, 'roaddata/cases/dapu/notes.json')['3.3.1'][0]
    assert block == {'type': 'figure', 'caption': '重要跨越', 'path': str(image)}


def test_startup_notices_warn_about_masked_credentials_without_exposing_values(tmp_path, monkeypatch):
    from road_description.model_runtime import credential
    from road_description.startup import startup_notices
    monkeypatch.delenv('TEST_RD_KEY', raising=False)
    settings = dict(enabled=True, api_base='https://private.test', model_id='test',
                    api_key_env='TEST_RD_KEY', credential_file='.env')
    local = tmp_path/'.env'
    local.write_text('TEST_RD_KEY=sk-********\n')
    config = dict(llm=settings, use_satellite=True, route_source='kml', output_dir='seed')
    text = '\n'.join(startup_notices(config, tmp_path))
    assert all(word in text for word in ('TEST_RD_KEY', 'TIANDITU_TK', 'map.raw.json.gz'))
    assert 'sk-' not in text and 'private.test' not in text
    local.write_text('TEST_RD_KEY=test-value-for-this-case\n')
    monkeypatch.setenv('TEST_RD_KEY', '[REDACTED]')
    assert credential(dict(settings, credential_file=str(local))) == 'test-value-for-this-case'
    text = '\n'.join(startup_notices(config, tmp_path))
    assert 'llm 已配置' in text and 'test-value-for-this-case' not in text
