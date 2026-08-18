# Involuntary Jailbreak

Official implementation of [Involuntary Jailbreak](https://arxiv.org/abs/2508.13246).

Implementing this method using APIs is quite simple and can be done in just a few steps.

---

## ✅ Successfully Tested LLMs

### Google Gemini
- Gemini 3 Pro
- Gemini 2.5 Pro, Flash, Flash Lite
- Gemini 2.0 Flash

### Anthropic Claude
- Sonnet 4.5, Sonnet 4
- Opus 4.1, Opus 4
- Sonnet 3.7

### xAI Grok
- Grok 4.1, Grok 4
- Grok 3, Grok 3 Fast, Grok 3 Mini

### OpenAI
- GPT-4.1
- GPT-4o
- gpt-oss

### Meta Llama
- Llama 4-Maverick-17B
- Llama 3.1-405B, Llama 3.3-70B

### DeepSeek
- DeepSeek R1
- DeepSeek V3

### Alibaba Qwen
- Qwen3-Coder-480B-A35B, Qwen3-235B-A22B
- Qwen2.5-72B

---

## 🚀 Quick Start

Copy and test the method using our [prompt template](prompt.txt).
If find being blocked, removing line 9 can lead to the same jailbreak attack.

> **⚠️ Note**: My OpenAI account got banned due to successful trials, so please be careful when testing using chatGPT website (API should be fine).

---

## ⚖️ Disclaimer

The jailbreaking methods described in this paper are solely intended for responsible AI safety research and the development of more robust, secure AI systems.

### We aim to:
- Help researchers and developers identify vulnerabilities and strengthen defenses.
- Enable the AI community to proactively mitigate risks before malicious exploitation.
- Foster responsible innovation in AI security.

### We urge all readers and users to:
- Any misuse for harmful, unethical, or unauthorized purposes is strictly prohibited.
- Adhere to ethical guidelines and respect platform terms of service.
- Use this knowledge responsibly to advance safe and beneficial AI technologies.
---

## 🔧 API Batching Setup

### Preparation

1. Create an `api_key.py` file under the `tools` directory
2. Add your API keys to the file
3. Configure settings in [gen_config.yaml](gen_config.yaml)

> **Note**: This implementation uses [together.ai](https://www.together.ai/) for open-source models. You can substitute your own API keys for proprietary LLMs like OpenAI GPT-4.1 and Grok 4.

### Generate Responses

Review `run_meta_prompt.py` and uncomment the model you want to test before running:
```bash
python run_meta_prompt.py
```

### Evaluate with Llama Guard-4

Run the judge evaluation (using together.ai):
```bash
python run_judge.py
```

---

## Citation

If you find this work useful, please cite our paper:
```bibtex
@misc{involuntary,
  title={Involuntary Jailbreak}, 
  author={Yangyang Guo and Yangyan Li and Mohan Kankanhalli},
  year={2025},
  eprint={2508.13246},
  archivePrefix={arXiv},
}
```

---

## Acknowledgements

Special thanks to [together.ai](https://www.together.ai/) for providing API access to open-source models. For proprietary LLMs like OpenAI GPT-4.1 and Grok 4, please visit their respective API websites for more information.
