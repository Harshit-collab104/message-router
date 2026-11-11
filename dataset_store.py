"""Configured CSV contracts, safe synthetic bootstrap, and dataset readiness.

No database, vector index, or provider client is opened by this module.
"""

import argparse
from datetime import datetime
import hashlib
import json
import os
import sys
from pathlib import Path
import tempfile

import numpy as np
import pandas as pd
from dotenv import load_dotenv


class DatasetError(ValueError):
    """A local dataset/configuration cannot be used safely."""


ROOT_DIR = Path(__file__).resolve().parent
load_dotenv(ROOT_DIR / '.env')


def configured_path(name, default):
    value = os.environ.get(name, '').strip()
    try:
        path = Path(value).expanduser() if value else Path(default)
        return (path if path.is_absolute() else ROOT_DIR / path).resolve()
    except (OSError, ValueError, RuntimeError) as error:
        raise DatasetError(f'Invalid path setting {name}') from error


def configured_bool(name):
    value = os.environ.get(name, 'false').strip().lower()
    if value not in {'', 'false', 'true', '0', '1'}:
        raise DatasetError(f'{name} must be true or false')
    return value in {'true', '1'}


try:
    DATA_DIR = configured_path('MESSAGE_ROUTER_DATA_DIR', ROOT_DIR / 'dataset')
    MEDIA_DIR = DATA_DIR / 'media'
    CHROMA_DIR = configured_path('MESSAGE_ROUTER_CHROMA_DIR',
        ROOT_DIR / 'chroma_db' if DATA_DIR == ROOT_DIR / 'dataset' else DATA_DIR / 'chroma_db')
    GATEWAY_DB_PATH = configured_path('MESSAGE_ROUTER_GATEWAY_DB', ROOT_DIR / 'msg_router_gateway.db')
    OFFLINE = configured_bool('MESSAGE_ROUTER_OFFLINE')
except DatasetError as error:
    if __name__ == '__main__':
        print(f'Message Router configuration: {error}', file=sys.stderr)
        raise SystemExit(2)
    raise
ACTIONS = {'notify', 'digest', 'mute'}
MESSAGE_TYPES = {'personal', 'urgent', 'event', 'payment', 'business_update',
                 'promotion', 'greeting', 'forward', 'spam', 'scam', 'unknown'}
MESSAGE_COLUMNS = ['message_id', 'user_id', 'conversation_type', 'group_id', 'business_id',
                   'sender_user_id', 'created_at', 'message_text', 'media_type', 'media_id', 'forwarded_count']
OUTPUT_COLUMNS = ['message_id', 'action', 'message_type', 'reason', 'confidence', 'evidence_message_ids']
SCHEMAS = {
    'users.csv': ['user_id', 'user_name', 'do_not_disturb_window', 'messages_opened_30d',
                  'messages_replied_30d', 'notifications_dismissed_30d', 'messages_reported_30d'],
    'groups.csv': ['group_id', 'group_name', 'group_type'],
    'group_members.csv': ['group_id', 'user_id', 'role', 'group_muted_by_user'],
    'business_accounts.csv': ['business_id', 'business_name', 'category', 'verified'],
    'user_business_history.csv': ['user_id', 'business_id', 'allows_promotions'],
    'messages.csv': MESSAGE_COLUMNS,
    'message_history.csv': MESSAGE_COLUMNS,
    'message_events.csv': ['message_id', 'user_id', 'message_opened', 'message_replied',
                           'notification_dismissed', 'muted_after_message', 'message_reported'],
    'images.csv': ['image_id', 'file_path'],
    'voice_notes.csv': ['voice_note_id', 'file_path'],
    'output.csv': OUTPUT_COLUMNS,
    'ground_truth.csv': ['message_id', 'action', 'message_type'],
}
REQUIRED_TABLES = ('users.csv', 'groups.csv', 'group_members.csv', 'business_accounts.csv',
                   'user_business_history.csv', 'messages.csv', 'message_history.csv', 'message_events.csv')
KEYS = {
    'users.csv': ['user_id'], 'groups.csv': ['group_id'],
    'group_members.csv': ['group_id', 'user_id'], 'business_accounts.csv': ['business_id'],
    'user_business_history.csv': ['user_id', 'business_id'], 'messages.csv': ['message_id'],
    'message_history.csv': ['user_id', 'message_id'], 'message_events.csv': ['user_id', 'message_id'],
    'images.csv': ['image_id'], 'voice_notes.csv': ['voice_note_id'],
    'output.csv': ['message_id'], 'ground_truth.csv': ['message_id'],
}
FLAGS = {'group_muted_by_user', 'verified', 'allows_promotions', 'message_opened',
         'message_replied', 'notification_dismissed', 'muted_after_message', 'message_reported'}
COUNTS = {'messages_opened_30d', 'messages_replied_30d', 'notifications_dismissed_30d',
          'messages_reported_30d', 'forwarded_count'}


def read_csv_table(path, default_columns=None, *, table_name=None, required=False):
    """Missing optional files are empty; existing malformed files never disappear silently."""
    path = Path(path)
    name = table_name or path.name
    columns = SCHEMAS.get(name, default_columns)
    if columns is None:
        raise DatasetError(f'Unknown CSV contract: {name}')
    if not path.exists():
        if required:
            raise DatasetError(f'Missing required CSV: {path}')
        return pd.DataFrame(columns=columns)
    try:
        frame = pd.read_csv(path, dtype=str, keep_default_na=False)
    except (OSError, ValueError, UnicodeError, pd.errors.ParserError) as error:
        raise DatasetError(f'Cannot read CSV {path}: {type(error).__name__}') from error
    if name == 'business_accounts.csv' and 'business_name' not in frame and 'brand_name' in frame:
        frame = frame.rename(columns={'brand_name': 'business_name'})
    missing = set(columns) - set(frame.columns)
    if missing:
        raise DatasetError(f'{path.name}: missing columns: {", ".join(sorted(missing))}')
    for column in frame.columns:
        frame.loc[frame[column].eq(''), column] = np.nan
    keys = KEYS.get(name, [])
    if name == 'message_history.csv' and 'source' in frame:
        frame['source'] = frame['source'].fillna('history')
        keys = ['source', *keys]
    for column in keys:
        if frame[column].isna().any() or frame[column].str.strip().eq('').any():
            raise DatasetError(f'{path.name}: {column} must not be blank')
    if keys and frame.duplicated(keys).any():
        raise DatasetError(f'{path.name}: duplicate key ({", ".join(keys)})')
    for column in (FLAGS | COUNTS) & set(frame.columns):
        values = pd.to_numeric(frame[column], errors='coerce')
        if values.isna().any() or not np.isfinite(values).all() or (values < 0).any() or (values >= 2**63).any() or (values % 1 != 0).any():
            raise DatasetError(f'{path.name}: {column} must contain non-negative integers')
        if column in FLAGS and not values.isin([0, 1]).all():
            raise DatasetError(f'{path.name}: {column} must contain 0 or 1')
        frame[column] = values.astype('int64')
    if name in {'messages.csv', 'message_history.csv'}:
        if not frame['conversation_type'].isin(['personal', 'group', 'business']).all():
            raise DatasetError(f'{path.name}: invalid conversation_type')
        for _, row in frame.iterrows():
            timestamp = row['created_at']
            try:
                datetime.strptime(str(timestamp), '%Y-%m-%d %H:%M:%S' if len(str(timestamp)) > 16 else '%Y-%m-%d %H:%M')
            except ValueError as error:
                raise DatasetError(f'{path.name}: created_at must be YYYY-MM-DD HH:MM[:SS]') from error
            context = {'personal': 'sender_user_id', 'group': 'group_id', 'business': 'business_id'}[row['conversation_type']]
            if pd.isna(row[context]) or str(row[context]).strip().lower() == 'none':
                raise DatasetError(f'{path.name}: {context} is required for this conversation_type')
    if name == 'users.csv':
        for value in frame['do_not_disturb_window'].dropna():
            if value.lower() == 'none':
                continue
            try:
                start, end = value.split('-')
                datetime.strptime(start, '%H:%M')
                datetime.strptime(end, '%H:%M')
            except ValueError as error:
                raise DatasetError('users.csv: do_not_disturb_window must be HH:MM-HH:MM or blank') from error
    if name in {'ground_truth.csv', 'output.csv'}:
        for column, choices in [('action', ACTIONS), ('message_type', MESSAGE_TYPES)]:
            values = frame[column] if name == 'ground_truth.csv' else frame[column].dropna()
            if not values.isin(choices).all():
                raise DatasetError(f'{path.name}: invalid {column}')
    return frame


def inspect_dataset(directory=None):
    directory = Path(directory) if directory is not None else DATA_DIR
    missing, errors, tables = [], [], {}
    frames = {}
    for name in SCHEMAS:
        path = directory / name
        if not path.exists():
            if name in REQUIRED_TABLES:
                missing.append(name)
            continue
        try:
            frames[name] = read_csv_table(path, required=True)
            tables[name] = len(frames[name])
        except DatasetError as error:
            errors.append(str(error))
    for name in ['users.csv', 'messages.csv']:
        if name in frames and frames[name].empty:
            errors.append(f'{name}: at least one row is required for a usable dataset')
    if not missing and not errors:
        users = set(frames['users.csv']['user_id'])
        for name in ['messages.csv', 'message_history.csv', 'message_events.csv', 'group_members.csv', 'user_business_history.csv']:
            if not set(frames[name]['user_id']).issubset(users):
                errors.append(f'{name}: unknown recipient user_id')
        history = set(zip(frames['message_history.csv']['user_id'], frames['message_history.csv']['message_id']))
        events = set(zip(frames['message_events.csv']['user_id'], frames['message_events.csv']['message_id']))
        if not events.issubset(history):
            errors.append('message_events.csv: reactions reference missing history')
    return {'ready': not missing and not errors, 'data_dir': str(directory), 'offline_mode': OFFLINE,
            'missing': missing, 'errors': errors, 'tables': tables}


def publish_dataset(tables, directory=None, *, kind='synthetic-demo'):
    """Validate in a temporary sibling, then publish without replacing user data."""
    if set(tables) - set(SCHEMAS):
        raise DatasetError('Cannot publish unknown table names')
    target = (Path(directory) if directory is not None else DATA_DIR).resolve()
    expected_inputs = {name: hashlib.sha256(frame.to_csv(index=False, lineterminator='\n').encode('utf-8')).hexdigest()
                       for name, frame in tables.items() if name != 'output.csv'}
    manifest_path = target / 'dataset_manifest.json'
    if target.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
            hashes = manifest['input_hashes']
            unchanged = (manifest['kind'] == kind and manifest['schema_version'] == 1 and isinstance(manifest.get('tables'), dict) and
                         isinstance(hashes, dict) and hashes == expected_inputs and
                         all(hashlib.sha256((target / name).read_bytes()).hexdigest() == digest for name, digest in hashes.items()))
        except (OSError, ValueError, KeyError, TypeError):
            unchanged = False
        if unchanged:
            return {'status': 'unchanged', 'data_dir': str(target), 'tables': manifest['tables']}
        raise DatasetError(f'Refusing to replace existing or edited data at {target}; choose a new MESSAGE_ROUTER_DATA_DIR')
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='.message-router-data-', dir=target.parent) as temporary:
            staged = Path(temporary) / 'dataset'
            staged.mkdir()
            for name, frame in tables.items():
                if name not in SCHEMAS:
                    raise DatasetError(f'Unknown table: {name}')
                frame.to_csv(staged / name, index=False, lineterminator='\n')
            status = inspect_dataset(staged)
            if not status['ready']:
                raise DatasetError('Invalid generated dataset: ' + '; '.join(status['missing'] + status['errors']))
            manifest = {'schema_version': 1, 'kind': kind, 'tables': status['tables'],
                        'input_hashes': {name: hashlib.sha256((staged / name).read_bytes()).hexdigest()
                                         for name in tables if name != 'output.csv'}}
            (staged / 'dataset_manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
            os.rename(staged, target)
    except OSError as error:
        raise DatasetError(f'Cannot publish dataset at {target}: {type(error).__name__}') from error
    return {'status': 'created', 'data_dir': str(target), 'tables': status['tables']}


def bootstrap_demo(directory=None):
    try:
        bundle = json.loads((ROOT_DIR / 'demo_data.json').read_text(encoding='utf-8'))
        if bundle['schema_version'] != 1:
            raise DatasetError('Unsupported demo schema version')
        tables = {name: pd.DataFrame(records, columns=SCHEMAS[name]) for name, records in bundle['tables'].items()}
        for name in ['images.csv', 'voice_notes.csv']:
            tables.setdefault(name, pd.DataFrame(columns=SCHEMAS[name]))
        tables['output.csv'] = pd.DataFrame([
            {'message_id': identifier, **{column: '' for column in OUTPUT_COLUMNS[1:]}}
            for identifier in tables['messages.csv']['message_id']], columns=OUTPUT_COLUMNS)
    except (OSError, ValueError, KeyError, TypeError) as error:
        if isinstance(error, DatasetError):
            raise
        raise DatasetError(f'Cannot load bundled demo: {type(error).__name__}') from error
    return publish_dataset(tables, directory)


def cli(argv=None):
    parser = argparse.ArgumentParser(description='Initialize or validate the configured Message Router CSV dataset')
    parser.add_argument('command', choices=['bootstrap', 'validate'])
    arguments = parser.parse_args(argv)
    try:
        result = bootstrap_demo() if arguments.command == 'bootstrap' else inspect_dataset()
        print(json.dumps(result, indent=2))
        return 0 if arguments.command == 'bootstrap' or result['ready'] else 2
    except DatasetError as error:
        parser.exit(2, f'Message Router dataset: {error}\n')


if __name__ == '__main__':
    raise SystemExit(cli())
