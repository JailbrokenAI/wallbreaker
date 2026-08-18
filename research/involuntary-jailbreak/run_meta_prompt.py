import os
import yaml
import json
from argparse import ArgumentParser

from prompt_template import meta_prompts
from tools.utils import safe_save_json, map_id_to_topic
from tools.llm_wrapper import create_llm_wrapper


def parse_args():
    parser = ArgumentParser(description="Initialize LLM wrappers for various backends.")
    parser.add_argument(
        '--lan_func',
        type=str,
        default='B(A(input))',
        choices=['B(A(input))', 'C(B(A(input)))'],
        help='C function helps to obfuscate the input further, but lowers readability.')
    parser.add_argument(
        '--unsafe_only',
        action='store_true',
        help='If set, only generate unsafe prompts.')
    parser.add_argument(
        '--safe_only',
        action='store_true',
        help='If set, only generate safe prompts.')
    parser.add_argument(
        '--topics',
        type=str,
        default='random',
        help='If set to random, the topics will be randomly selected from the list of topics.')
    return parser.parse_args()


def initiate_llms():
    """ We used together.ai for qwen, deepseek, and llama models."""
    qwen_models = [
        # 'Qwen/Qwen3-235B-A22B-Instruct-2507-tput',
        # 'Qwen/Qwen3-Coder-480B-A35B-Instruct-FP8',
        'Qwen/Qwen2.5-72B-Instruct-Turbo',
        'openai/gpt-oss-20b',
        # 'Qwen/QwQ-32B',
        ]
    deepseek_models = [
        # 'deepseek-ai/DeepSeek-V3',
        # 'deepseek-ai/DeepSeek-R1-Distill-Llama-70B',
        # 'deepseek-ai/DeepSeek-R1',
        ]
    llama_models = [
        # 'meta-llama/Llama-4-Maverick-17B-128E-Instruct-FP8',
        # 'meta-llama/Meta-Llama-3.1-405B-Instruct-Turbo',
        # 'meta-llama/Llama-4-Scout-17B-16E-Instruct',
        'meta-llama/Llama-3.3-70B-Instruct-Turbo',
        'meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo',
        'mistralai/Mistral-Small-24B-Instruct-2501',
        # 'nvidia/Llama-3.1-Nemotron-70B-Instruct-HF',
        ]
    gemini_models = [
        # 'gemini-2.5-pro',
        # 'gemini-2.5-flash-lite',
        # 'gemini-2.5-flash',
        # 'gemini-2.0-flash',
    ]
    openai_models = [
        # 'gpt-4.1-mini',
        # 'gpt-4.1',
        # 'gpt-4o',
        # 'o3',
        # 'o1'
    ]
    claude_models = [
        # 'claude-opus-4-1-20250805',
        # 'claude-sonnet-4-20250514',
        # 'claude-opus-4-20250514',
        # 'claude-3-7-sonnet-20250219',
        # 'claude-3-5-haiku-20241022',
    ]
    grok_models = [
        # 'grok-4-0709',
        # 'grok-3',
        # 'grok-3-mini',
        # 'grok-3-fast',
    ]

    llm_api_mapper = dict()
    llm_api_mapper['together_ai'] = [model for model in qwen_models + deepseek_models + llama_models]
    for backend_name in ['openai', 'claude', 'grok', 'gemini']:
        llm_api_mapper[backend_name] = [model for model in eval(f"{backend_name}_models")]
    return llm_api_mapper


if __name__ == "__main__":
    common_args = yaml.safe_load(open('gen_config.yaml', 'r'))    
    args = parse_args()
    args.__dict__.update(common_args)

    if args.topics == 'random':
        topics = ''
    else:
        topics = map_id_to_topic(args.topics)

    llm_api_mapper = initiate_llms()

    if args.unsafe_only:
        prompt = meta_prompts.meta_prompt_unsafe_only.format(
            total_num=args.unsafe_num,
            unsafe_num=args.unsafe_num, 
            lan_func=args.lan_func,
            topic=topics,
        )
    elif args.safe_only:
        prompt = meta_prompts.meta_prompt_safe_only.format(
            total_num=args.total_num - args.unsafe_num,
            safe_num=args.total_num - args.unsafe_num,
            lan_func=args.lan_func,
            topic=topics,
        )
    else:
        prompt = meta_prompts.meta_prompt.format(
            total_num=args.total_num,
            unsafe_num=args.unsafe_num,
            safe_num=args.total_num - args.unsafe_num,
            lan_func=args.lan_func,
            topic=topics,
        )

    print(prompt)

    for backend_name, models in llm_api_mapper.items():
        if args.unsafe_only:
            backend_path = os.path.join(args.meta_dir['unsafe_response_dir'], backend_name)
        else:
            backend_path = os.path.join(args.meta_dir['response_dir'], backend_name)
        
        # backend_path = os.path.join('eval_outputs_topic', backend_name)
        os.makedirs(backend_path, exist_ok=True)
        if len(models) > 0:
            for model in models:
                model_path = os.path.join(backend_path, model.replace('/', '_'))
                os.makedirs(model_path, exist_ok=True)
                llm = create_llm_wrapper(backend_name, model)
                model_output = dict()

                start_attempt = 0
                if os.path.exists(os.path.join(model_path, 'meta_prompt_out.json')):
                    model_output = json.load(open(os.path.join(model_path, 'meta_prompt_out.json'), 'r'))
                    start_attempt = len(model_output) 

                for time in range(start_attempt, args.attempt_times):
                    print(f"Attempt {time + 1}/{args.attempt_times} for {backend_name} with model {model}")
                    response = llm.generate(prompt, max_tokens=4096) # careful with max_tokens, try not to bankrupt
                    model_output[f"attempt_{time + 1}"] = response
                    print(f"Response from {backend_name}: {response}")
                    safe_save_json(model_output, os.path.join(model_path, 'meta_prompt_out.json'))
                json.dump(model_output, open(
                    os.path.join(model_path, 'meta_prompt_out.json'), 'w'), indent=4)
