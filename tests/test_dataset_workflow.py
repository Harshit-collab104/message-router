"""Dataset setup, contracts, configuration, errors, and offline end-to-end checks."""

import json
import os
import subprocess
import sys

import pandas as pd
import pytest


def run_cli(router, script, *arguments, settings=None):
    guard = """import os, runpy, sys
attempts = []
def audit(event, arguments):
    if event in ('socket.connect', 'socket.getaddrinfo'):
        attempts.append(event)
        raise OSError('Network blocked by offline CLI test')
sys.addaudithook(audit)
sys.argv = sys.argv[1:]
sys.path[0] = os.path.dirname(os.path.abspath(sys.argv[0]))
try:
    runpy.run_path(sys.argv[0], run_name='__main__')
finally:
    if attempts:
        print('Offline CLI attempted network access', file=sys.stderr)
        raise SystemExit(99)
"""
    return subprocess.run(
        [sys.executable, '-B', '-c', guard, str(router.workspace / script), *arguments],
        cwd=router.workspace, env={**os.environ, **(settings or {})},
        capture_output=True, text=True, timeout=30,
    )


def test_missing_dataset_has_an_authenticated_setup_status(router, client):
    assert router.http('GET', '/api/dataset/status').status_code == 401
    response = client.get('/api/dataset/status')
    assert response.status_code == 200
    status = response.json()
    assert status['ready'] is False
    assert set(status['missing']) == set(router.store.REQUIRED_TABLES)
    assert status['errors'] == []
    assert not router.store.DATA_DIR.exists()


def test_bootstrap_is_deterministic_idempotent_and_preserves_derived_output(router):
    first = router.store.bootstrap_demo()
    assert first['status'] == 'created'
    original = {p.name: p.read_bytes() for p in router.store.DATA_DIR.glob('*.csv')}
    second_path = router.workspace / 'second-dataset'
    router.store.bootstrap_demo(second_path)
    assert original == {p.name: p.read_bytes() for p in second_path.glob('*.csv')}
    output = router.store.DATA_DIR / 'output.csv'
    output.write_text('Caller-owned derived output\n', encoding='utf-8')
    assert router.store.bootstrap_demo()['status'] == 'unchanged'
    assert output.read_text(encoding='utf-8') == 'Caller-owned derived output\n'
    assert not (router.store.DATA_DIR / 'chroma_db').exists()


def test_bootstrap_refuses_existing_or_edited_input(router):
    router.store.bootstrap_demo()
    users = router.store.DATA_DIR / 'users.csv'
    users.write_text(users.read_text().replace('Demo Recipient', 'Edited Recipient'), encoding='utf-8')
    before = users.read_bytes()
    with pytest.raises(router.store.DatasetError, match='Refusing to replace'):
        router.store.bootstrap_demo()
    assert users.read_bytes() == before


def test_bootstrap_does_not_overwrite_an_unrelated_directory(router):
    router.store.DATA_DIR.mkdir()
    sentinel = router.store.DATA_DIR / 'keep.txt'
    sentinel.write_text('Keep this', encoding='utf-8')
    with pytest.raises(router.store.DatasetError, match='Refusing to replace'):
        router.store.bootstrap_demo()
    assert list(router.store.DATA_DIR.iterdir()) == [sentinel]


def test_failed_publication_leaves_no_partial_dataset(router, monkeypatch):
    def denied(*args):
        raise PermissionError('Synthetic denied rename')

    monkeypatch.setattr(router.store.os, 'rename', denied)
    with pytest.raises(router.store.DatasetError, match='Cannot publish dataset'):
        router.store.bootstrap_demo()
    assert not router.store.DATA_DIR.exists()
    assert not list(router.store.DATA_DIR.parent.glob('.message-router-data-*'))


@pytest.mark.parametrize('case,expected', [
    ('columns', 'missing columns'), ('negative_count', 'non-negative integers'),
    ('duplicate', 'duplicate key'), ('conversation', 'invalid conversation_type'),
    ('timestamp', 'created_at'), ('context', 'sender_user_id is required'),
])
def test_malformed_messages_are_reported_instead_of_silently_empty(router, message, case, expected):
    router.store.DATA_DIR.mkdir()
    records = [dict(message)]
    if case == 'columns':
        records = [{'message_id': 'one'}]
    elif case == 'negative_count':
        records[0]['forwarded_count'] = -1
    elif case == 'duplicate':
        records.append(dict(message))
    elif case == 'conversation':
        records[0]['conversation_type'] = 'unsupported'
    elif case == 'timestamp':
        records[0]['created_at'] = 'yesterday'
    elif case == 'context':
        records[0]['sender_user_id'] = ''
    path = router.store.DATA_DIR / 'messages.csv'
    pd.DataFrame(records).to_csv(path, index=False)
    with pytest.raises(router.store.DatasetError, match=expected):
        router.main.get_messages()
    assert router.main.messages is None


def test_empty_csv_is_an_error_but_missing_optional_media_is_empty(router):
    missing = router.main.images
    assert missing.empty and list(missing.columns) == ['image_id', 'file_path']
    router.store.DATA_DIR.mkdir()
    (router.store.DATA_DIR / 'messages.csv').write_bytes(b'')
    with pytest.raises(router.store.DatasetError, match='Cannot read CSV'):
        router.main.get_messages()


@pytest.mark.parametrize('router', ['demo'], indirect=True)
@pytest.mark.parametrize('table,column,value,error', [
    ('users.csv', 'do_not_disturb_window', '24:70-06:00', 'do_not_disturb_window'),
    ('users.csv', 'messages_replied_30d', '1.5', 'non-negative integers'),
    ('users.csv', 'messages_replied_30d', '1e99', 'non-negative integers'),
    ('business_accounts.csv', 'verified', '2', '0 or 1'),
])
def test_profile_contracts_are_explicit(router, table, column, value, error):
    path = router.store.DATA_DIR / table
    frame = pd.read_csv(path, dtype=str, keep_default_na=False)
    frame.loc[0, column] = value
    frame.to_csv(path, index=False)
    with pytest.raises(router.store.DatasetError, match=error):
        router.store.read_csv_table(path)


@pytest.mark.parametrize('router', ['demo'], indirect=True)
def test_dataset_status_checks_recipient_and_reaction_relationships(router):
    path = router.store.DATA_DIR / 'message_events.csv'
    events = pd.read_csv(path)
    events.loc[0, 'user_id'] = 'unknown-recipient'
    events.to_csv(path, index=False)
    status = router.store.inspect_dataset()
    assert status['ready'] is False
    assert any('unknown recipient' in error for error in status['errors'])
    assert any('missing history' in error for error in status['errors'])


@pytest.mark.parametrize('router', ['demo'], indirect=True)
def test_invalid_lazy_data_has_a_structured_http_error(router, client):
    path = router.store.DATA_DIR / 'messages.csv'
    path.write_text('message_id\none\n', encoding='utf-8')
    response = client.get('/api/incoming/u_001')
    assert response.status_code == 503
    assert response.json()['code'] == 'dataset_invalid'
    assert 'missing columns' in response.json()['detail']
    status = client.get('/api/dataset/status').json()
    assert status['ready'] is False and status['errors']


@pytest.mark.parametrize('router', [{'demo': True, 'offline': True, 'provider_keys': True}], indirect=True)
def test_offline_demo_runs_the_existing_gateway_without_provider_or_vector_calls(router, client, monkeypatch):
    assert router.server.CONFIG['active_model'] == 'heuristic'
    assert router.server.CONFIG['offline_mode'] is True
    assert router.server.gemini_client is None and router.server.groq_key is None
    assert client.get('/api/dataset/status').json()['ready'] is True
    assert len(client.get('/api/users').json()) == 2
    assert len(client.get('/api/contacts/u_001').json()) == 3
    incoming = client.get('/api/incoming/u_001').json()
    assert len(incoming) == 5
    results = [client.post('/api/gateway/webhook', json=message).json() for message in incoming]
    assert [result['action'] for result in results] == ['notify', 'digest', 'mute', 'notify', 'mute']
    channels = client.get('/api/client/device/u_001').json()
    assert [len(channels[name]) for name in ['inbox', 'digest', 'quarantine']] == [2, 1, 2]
    assert router.vectors.writes == []
    monkeypatch.setenv('WHATSAPP_TOKEN', 'synthetic-must-not-be-used')
    monkeypatch.setenv('WHATSAPP_PHONE_NUMBER_ID', 'synthetic')
    preview = client.post('/api/digest/generate/u_001').json()
    assert preview['status'] == 'success'
    dispatch = client.post('/api/digest/generate/u_001?auto_send=true').json()
    assert dispatch['status'] == 'skipped'
    assert client.get('/api/digest/pending/u_001').json()['pending_count'] == 1
    response = client.post('/api/gateway/config', json={'active_model': 'groq'})
    assert response.status_code == 400
    assert 'offline mode' in response.json()['detail']
    assert router.vector_store.retrieve_relevant_history('u_001', 'personal', None, None, 'u_002', 'Hi') == []
    with pytest.raises(router.store.DatasetError, match='offline mode'):
        router.vector_store.get_client()


@pytest.mark.parametrize('router', [{'demo': True, 'offline': True, 'provider_keys': True}], indirect=True)
@pytest.mark.parametrize('provider', ['gemini', 'groq'])
def test_global_offline_mode_cannot_be_disabled_by_a_row_flag(router, message, monkeypatch, provider):
    from types import SimpleNamespace

    calls = []

    def provider_call(*args, **kwargs):
        calls.append('called')
        raise AssertionError('Offline provider was invoked')

    message['_offline'] = False
    monkeypatch.setattr(router.main, 'groq_completion', provider_call)
    if provider == 'gemini':
        sdk = SimpleNamespace(models=SimpleNamespace(generate_content=provider_call))
        result = router.main.process_message_with_gemini(sdk, message, 'synthetic')
    else:
        result = router.main.process_message_with_groq(message, 'Synthetic prompt')
    assert result[0] == 'digest'
    assert calls == []
    assert message['_model_used'] == 'heuristic (offline)'


@pytest.mark.parametrize('router', [{'demo': True, 'offline': True, 'data_dir': 'nested/demo'}], indirect=True)
def test_configured_root_is_shared_by_runtime_generation_evaluation_and_packaging(router):
    root = router.workspace / 'nested' / 'demo'
    assert router.store.DATA_DIR == root
    assert router.main.FOLDER_DIR == root and router.main.MEDIA_DIR == root / 'media'
    assert router.vector_store.CHROMA_DB_PATH == root / 'chroma_db'
    evaluate = router.load('evaluate')
    generator = router.load('generate_data')
    packager = router.load('pack')
    assert evaluate.DATA_DIR == generator.DATA_DIR == packager.DATA_DIR == root
    assert not (router.workspace.parent / 'submission').exists()
    assert not (router.workspace.parent / 'hackerrank-orchestrate-august26').exists()
    router.main.main()
    assert router.main.OUTPUT_FILE == root / 'output.csv'
    assert evaluate.main() == {'total': 5, 'correct_action': 5, 'correct_type': 5}


def test_existing_synthetic_generator_uses_the_same_publisher_and_root(router):
    generator = router.load('generate_data')
    assert not router.store.DATA_DIR.exists()  # Import has no writes or random generation.
    result = generator.generate_dataset(hist_rows=10, target_rows=5)
    assert result['status'] == 'created'
    assert router.store.inspect_dataset()['ready'] is True
    assert len(router.store.read_csv_table(router.store.DATA_DIR / 'messages.csv')) == 5
    with pytest.raises(router.store.DatasetError, match='Refusing to replace'):
        generator.generate_dataset(hist_rows=11, target_rows=5)
    with pytest.raises(router.store.DatasetError, match='positive'):
        generator.generate_dataset(hist_rows=0, target_rows=5)


def test_cli_missing_setup_and_invalid_configuration_have_clear_exit_codes(router):
    missing = run_cli(router, 'dataset_store.py', 'validate')
    assert missing.returncode == 2 and json.loads(missing.stdout)['ready'] is False
    invalid = run_cli(router, 'dataset_store.py', 'validate', settings={'MESSAGE_ROUTER_OFFLINE': 'sometimes'})
    assert invalid.returncode == 2
    assert 'MESSAGE_ROUTER_OFFLINE must be true or false' in invalid.stderr
    assert 'Traceback' not in invalid.stderr


def test_cli_bootstrap_batch_and_evaluation_complete_offline(router):
    settings = {'MESSAGE_ROUTER_OFFLINE': 'false', 'GEMINI_API_KEY': 'synthetic-must-not-be-used',
                'GROQ_API_KEY': 'synthetic-must-not-be-used'}
    setup = run_cli(router, 'dataset_store.py', 'bootstrap', settings=settings)
    assert setup.returncode == 0, setup.stderr
    assert json.loads(setup.stdout)['status'] == 'created'
    verify = run_cli(router, 'dataset_store.py', 'validate', settings=settings)
    assert verify.returncode == 0 and json.loads(verify.stdout)['ready'] is True
    batch = run_cli(router, 'main.py', '--offline', settings=settings)
    assert batch.returncode == 0, batch.stderr
    output = pd.read_csv(router.store.DATA_DIR / 'output.csv')
    assert output['action'].tolist() == ['notify', 'digest', 'mute', 'notify', 'mute']
    evaluation = run_cli(router, 'evaluate.py', '--offline', settings=settings)
    assert evaluation.returncode == 0, evaluation.stderr
    assert '5 / 5 (100.00%)' in evaluation.stdout
    blocked_index = run_cli(router, 'vector_store.py', settings={'MESSAGE_ROUTER_OFFLINE': 'true'})
    assert blocked_index.returncode == 2 and 'offline mode' in blocked_index.stderr
    assert 'Traceback' not in blocked_index.stderr
    rerun = run_cli(router, 'dataset_store.py', 'bootstrap', settings=settings)
    assert rerun.returncode == 0 and json.loads(rerun.stdout)['status'] == 'unchanged'


@pytest.mark.parametrize('router', ['demo'], indirect=True)
def test_evaluation_refuses_incomplete_labels(router):
    path = router.store.DATA_DIR / 'ground_truth.csv'
    truth = pd.read_csv(path).iloc[:1]
    truth.to_csv(path, index=False)
    with pytest.raises(router.store.DatasetError, match='exactly match'):
        router.load('evaluate').main(offline=True)


def test_legacy_brand_name_and_leading_zero_identifiers_are_preserved(router):
    path = router.workspace / 'business_accounts.csv'
    path.write_text('business_id,brand_name,category,verified\n001,Demo,logistics,1\n', encoding='utf-8')
    frame = router.store.read_csv_table(path)
    assert frame.iloc[0]['business_id'] == '001'
    assert frame.iloc[0]['business_name'] == 'Demo'
    assert frame.iloc[0]['verified'] == 1


@pytest.mark.parametrize('router', [{'offline': True, 'settings': {
    'MESSAGE_ROUTER_DATA_DIR': 'custom/input', 'MESSAGE_ROUTER_CHROMA_DIR': 'state/vectors',
    'MESSAGE_ROUTER_GATEWAY_DB': 'state/gateway.db',
}}], indirect=True)
def test_explicit_storage_overrides_are_resolved_against_the_repository(router):
    assert router.main.FOLDER_DIR == router.workspace / 'custom' / 'input'
    assert router.vector_store.CHROMA_DB_PATH == router.workspace / 'state' / 'vectors'
    assert router.server.DB_PATH == router.workspace / 'state' / 'gateway.db'
    assert router.server.DB_PATH.exists()
    assert not (router.workspace / 'msg_router_gateway.db').exists()
    assert not router.vector_store.CHROMA_DB_PATH.exists()


def test_malformed_demo_manifest_is_a_clear_no_overwrite_error(router):
    router.store.bootstrap_demo()
    manifest_path = router.store.DATA_DIR / 'dataset_manifest.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    del manifest['tables']
    manifest_path.write_text(json.dumps(manifest), encoding='utf-8')
    with pytest.raises(router.store.DatasetError, match='Refusing to replace'):
        router.store.bootstrap_demo()


def test_invalid_index_input_is_rejected_before_opening_or_rebuilding_storage(router, monkeypatch):
    path = router.workspace / 'broken.csv'
    path.write_text('message_id\none\n', encoding='utf-8')
    calls = []
    monkeypatch.setattr(router.vector_store, 'get_client', lambda: calls.append('opened'))
    with pytest.raises(router.store.DatasetError, match='missing columns'):
        router.vector_store.init_db(path, force_rebuild=True)
    assert calls == []


@pytest.mark.parametrize('router', ['demo'], indirect=True)
def test_exported_archive_can_bootstrap_and_route_its_own_demo(router, monkeypatch):
    from pathlib import Path
    import shutil
    import zipfile

    source = Path(__file__).resolve().parents[1]
    for name in ['requirements.txt', 'README.md', 'DATASET_WORKFLOW.md']:
        shutil.copyfile(source / name, router.workspace / name)
    shutil.copytree(source / 'static', router.workspace / 'static', dirs_exist_ok=True)
    router.main.main(offline=True)
    packager = router.load('pack')
    # The legacy optional transcript path is outside this feature; never read host files in a test.
    monkeypatch.setattr(packager, 'LOG_FILE', router.workspace / 'no-transcript.log')
    packager.main()
    submission = router.workspace.parent / 'submission'
    assert (submission / 'output.csv').read_bytes() == (router.store.DATA_DIR / 'output.csv').read_bytes()
    extracted = router.workspace / 'unpacked'
    with zipfile.ZipFile(submission / 'code.zip') as archive:
        assert not any(name.endswith('.env') or name.endswith('.db') for name in archive.namelist())
        archive.extractall(extracted)  # This archive was just built from the explicit local code allowlist.
    packaged = extracted / 'msg_router'
    settings = {'MESSAGE_ROUTER_DATA_DIR': str(extracted / 'new-data'), 'MESSAGE_ROUTER_OFFLINE': 'true'}
    setup = run_cli(router, packaged / 'dataset_store.py', 'bootstrap', settings=settings)
    assert setup.returncode == 0, setup.stderr
    result = run_cli(router, packaged / 'main.py', '--offline', settings=settings)
    assert result.returncode == 0, result.stderr
    output = pd.read_csv(extracted / 'new-data' / 'output.csv')
    assert output['action'].tolist() == ['notify', 'digest', 'mute', 'notify', 'mute']
