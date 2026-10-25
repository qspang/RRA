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
