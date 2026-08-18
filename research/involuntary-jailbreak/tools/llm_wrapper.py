import os
import sys
import json
import importlib.util
from abc import ABC, abstractmethod
from typing import List, Dict, Union, Callable, Optional, Any, Tuple

import torch
from transformers import AutoTokenizer, AutoModelForCausalLM

from . import api_keys


class BaseLLMWrapper(ABC):
    def __init__(self, model_name: str):
        self.model_name = model_name

    @abstractmethod
    def generate(self, prompt: str, max_tokens: int = 1024) -> Union[str, int]:
        pass


class OpenAIWrapper(BaseLLMWrapper):
    def __init__(self, model_name: str, api_base: str = None):
        super().__init__(model_name)
        import openai

        if api_base:
            openai.api_base = api_base
        self.client = openai
        self.client.api_key = api_keys.openai

    def generate(self, prompt: str, max_tokens: int = 512) -> str:
        if 'o1' in self.model_name or 'o3' in self.model_name:
            response = self.client.chat.completions.create(
                model=self.model_name,
                messages=[{"role": "user", "content": prompt}],
                max_completion_tokens=1024,
                stream=False
            )
        else:
            response = self.client.chat.completions.create(
                model=self.model_name,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=max_tokens,
                stream=False
            )
        return response.choices[0].message.content


class TogetherWrapper(BaseLLMWrapper):
    def __init__(self, model_name: str):
        super().__init__(model_name)
        from together import Together
        os.environ["TOGETHER_API_KEY"]=api_keys.together_ai

        self.client = Together()

    def generate(self, prompt: str, max_tokens: int = 1024) -> str:
        response = self.client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model=self.model_name,
            max_tokens=max_tokens,
            stream=False
        )
        return response.choices[0].message.content


class GeminiWrapper(BaseLLMWrapper):
    def __init__(self, model_name: str):
        super().__init__(model_name)
        from google import genai
        os.environ["GEMINI_API_KEY"] = api_keys.gemini

        self.client = genai.Client()

    def generate(self, prompt: str, max_tokens: int = 1024) -> str:
        response = self.client.models.generate_content(
            model=self.model_name,
            contents=prompt,
        )
        return response.text


class ClaudeWrapper(BaseLLMWrapper):
    def __init__(self, model_name: str):
        super().__init__(model_name)
        from anthropic import Anthropic

        os.environ["ANTHROPIC_API_KEY"] = api_keys.claude

        self.client = Anthropic()

    def generate(self, prompt: str, max_tokens: int = 1024) -> str: 
        response = self.client.messages.create(
            model=self.model_name,
            max_tokens=max_tokens,
            temperature=0.7,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": prompt
                    }
                ]
            }],
        )
        return response.content[0].text


class GrokWrapper(BaseLLMWrapper):
    def __init__(self, model_name: str):
        super().__init__(model_name)
        from xai_sdk import Client

        os.environ["XAI_API_KEY"] = api_keys.grok
        self.client =  Client(
            api_key=os.getenv("XAI_API_KEY"),
            timeout=3600,  # Override default timeout with longer timeout for reasoning models
            )
        self.chat = self.client.chat.create(model=model_name)

    def generate(self, prompt: str, max_tokens: int = 1024) -> str:
        from xai_sdk.chat import user
        self.chat.append(user(prompt))
        response = self.chat.sample()
        return response.content


class HuggingFaceWrapper(BaseLLMWrapper):
    def __init__(self, model_name: str):
        super().__init__(model_name)
        token = api_keys.huggingface if api_keys.huggingface else None
        self.model = AutoModelForCausalLM.from_pretrained(
            model_name, 
            torch_dtype=torch.float16, 
            device_map="auto",
            use_auth_token=token,
            trust_remote_code=True
            )
        self.tokenizer = AutoTokenizer.from_pretrained(
            model_name, 
            use_auth_token=token,
            trust_remote_code=True
            )

    def generate(self, prompt: str, max_tokens: int = 512) -> Union[str, int]:
        inputs = self.tokenizer.apply_chat_template(
            prompt, 
            return_tensors="pt", 
            return_dict=True, 
            add_generation_prompt=True)
        inputs['input_ids'] = inputs['input_ids'].to(self.model.device)
        inputs['attention_mask'] = inputs['attention_mask'].to(self.model.device)
        outputs = self.model.generate(**inputs, max_new_tokens=max_tokens)
        result = self.tokenizer.decode(outputs[0][len(inputs['input_ids'][0]):], skip_special_tokens=True)
        return result


def create_llm_wrapper(backend: str, model_name: str, **kwargs) -> BaseLLMWrapper:
    """Factory function to create appropriate LLM wrapper based on backend."""
    backends = {
        'openai': OpenAIWrapper,
        'together_ai': TogetherWrapper,
        'gemini': GeminiWrapper,
        'claude': ClaudeWrapper,
        'grok': GrokWrapper,
        'huggingface': HuggingFaceWrapper
    }
    
    if backend not in backends:
        raise ValueError(f"Unsupported backend: {backend}. Choose from {list(backends.keys())}")
    
    return backends[backend](model_name, **kwargs)
