import os
import json


def safe_save_json(data, path):
    tmp_path = path + ".tmp"
    with open(tmp_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4)
    os.replace(tmp_path, path)


def map_id_to_topic(topic_string: str) -> str:
    """
    Maps given topic ID to a topic string according to Llama guard-4 policy.
    https://www.llama.com/docs/model-cards-and-prompt-formats/llama-guard-4/
    """
    topic_mapping = {
        'S1': 'Violent Crimes',
        'S2': 'Non-Violent Crimes',
        'S3': 'Sex Crimes',
        'S4': 'Child Exploitation',
        'S5': 'Defamation',
        'S6': 'Specialized Advice',
        'S7': 'Privacy',
        'S8': 'Intellectual Property',
        'S9': 'Indiscriminate Weapons',
        'S10': 'Hate',
        'S11': 'Self-Harm',
        'S12': 'Sexual Content',
        'S13': 'Elections',
        'S14': 'Code Interpreter Abuse'
    }

    topic_ids = topic_string.split(',')
    if any(topic_id not in topic_mapping for topic_id in topic_ids):
        raise ValueError(f"Invalid topic ID in {topic_string}. Valid IDs are: {', '.join(topic_mapping.keys())}")

    return ', '.join(topic_mapping[topic_id] for topic_id in topic_ids if topic_id in topic_mapping)
    