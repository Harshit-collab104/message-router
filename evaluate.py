"""Evaluate the configured local corpus, using the existing heuristic router."""

import argparse
from dataset_store import DATA_DIR, OFFLINE, DatasetError, read_csv_table
from main import predict_heuristic


def main(*, offline=None):
    offline = OFFLINE or bool(offline)
    messages = read_csv_table(DATA_DIR / 'messages.csv', required=True)
    truth = read_csv_table(DATA_DIR / 'ground_truth.csv', required=True)
    if messages.empty:
        raise DatasetError('messages.csv: evaluation requires at least one row')
    if set(messages['message_id']) != set(truth['message_id']):
        raise DatasetError('ground_truth.csv: message IDs must exactly match messages.csv')
    labels = truth.set_index('message_id').to_dict(orient='index')
    correct_action = correct_type = 0
    for _, row in messages.iterrows():
        row['_offline'] = offline
        action, kind, *_ = predict_heuristic(row)
        expected = labels[row['message_id']]
        correct_action += int(action == expected['action'])
        correct_type += int(kind == expected['message_type'])
    result = {'total': len(messages), 'correct_action': correct_action, 'correct_type': correct_type}
    print(f"Action Accuracy: {correct_action} / {len(messages)} ({correct_action / len(messages) * 100:.2f}%)")
    print(f"Type Accuracy: {correct_type} / {len(messages)} ({correct_type / len(messages) * 100:.2f}%)")
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Evaluate messages.csv against ground_truth.csv in the configured data directory')
    parser.add_argument('--offline', action='store_true', default=None)
    arguments = parser.parse_args()
    try:
        main(offline=arguments.offline)
    except (DatasetError, ValueError, OSError) as error:
        parser.exit(2, f'Message Router evaluation: {error}\n')
