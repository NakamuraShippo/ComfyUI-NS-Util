"""
SimpleLLM - A ComfyUI custom node as alternative to Griptape
Provides LLM integration, image analysis, and text processing capabilities
Version: 1.2.0 - Integrated for utilnode
"""

import os
import json
import requests
import base64
import hashlib
from typing import Dict, List, Tuple, Any, Optional
from io import BytesIO
from pathlib import Path

# ComfyUIから必要なモジュールをインポート
try:
    from PIL import Image
    import numpy as np
    import torch
    HAS_COMFYUI = True
except ImportError as e:
    print(f"Warning: Failed to import ComfyUI modules: {e}")
    HAS_COMFYUI = False
    Image = None
    np = None
    torch = None

# WEB_DIRECTORY設定
WEB_DIRECTORY = "./web"

# ============================================
# Base Classes
# ============================================

class BaseDriver:
    """LLMドライバーの基底クラス"""
    API_KEY_ENV = ""
    
    def __init__(self, api_key: str = None, **kwargs):
        self.api_key = api_key or os.getenv(self.API_KEY_ENV, "")
        self.config = kwargs
    
    def complete(self, prompt: str, **kwargs) -> str:
        """テキスト生成のインターフェース"""
        raise NotImplementedError("Subclass must implement complete method")

class OpenAIDriver(BaseDriver):
    """OpenAI APIドライバー（requestsベース実装）"""
    API_KEY_ENV = "OPENAI_API_KEY"
    
    def complete(self, prompt: str, model: str = "gpt-3.5-turbo", **kwargs) -> str:
        """OpenAI APIを使用してテキスト生成"""
        if not self.api_key:
            return "Error: OpenAI API key not set. Please set OPENAI_API_KEY environment variable or provide api_key."
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        system_prompt = kwargs.get("system_prompt", "You are a helpful assistant.")
        
        data = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt}
            ],
            "temperature": kwargs.get("temperature", 0.7),
            "max_tokens": kwargs.get("max_tokens", 1000)
        }
        
        try:
            response = requests.post(
                "https://api.openai.com/v1/chat/completions",
                headers=headers,
                json=data,
                timeout=30
            )
            response.raise_for_status()
            result = response.json()
            return result["choices"][0]["message"]["content"]
        except Exception as e:
            return f"Error: {str(e)}"

class ClaudeDriver(BaseDriver):
    """Anthropic Claude APIドライバー"""
    API_KEY_ENV = "ANTHROPIC_API_KEY"
    
    def complete(self, prompt: str, model: str = "claude-3-sonnet-20240229", **kwargs) -> str:
        """Claude APIを使用してテキスト生成"""
        if not self.api_key:
            return "Error: Anthropic API key not set. Please set ANTHROPIC_API_KEY environment variable or provide api_key."
        
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json"
        }
        
        system_prompt = kwargs.get("system_prompt", "You are a helpful assistant.")
        
        data = {
            "model": model,
            "max_tokens": kwargs.get("max_tokens", 1000),
            "temperature": kwargs.get("temperature", 0.7),
            "system": system_prompt,
            "messages": [
                {"role": "user", "content": prompt}
            ]
        }
        
        try:
            response = requests.post(
                "https://api.anthropic.com/v1/messages",
                headers=headers,
                json=data,
                timeout=30
            )
            response.raise_for_status()
            result = response.json()
            return result["content"][0]["text"]
        except Exception as e:
            return f"Error: {str(e)}"

class GeminiDriver(BaseDriver):
    """Google Gemini APIドライバー"""
    API_KEY_ENV = "GOOGLE_API_KEY"
    
    def complete(self, prompt: str, model: str = "gemini-pro", **kwargs) -> str:
        """Gemini APIを使用してテキスト生成"""
        if not self.api_key:
            return "Error: Google API key not set. Please set GOOGLE_API_KEY environment variable or provide api_key."
        
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={self.api_key}"
        
        headers = {
            "Content-Type": "application/json"
        }
        
        system_prompt = kwargs.get("system_prompt", "")
        full_prompt = f"{system_prompt}\n\n{prompt}" if system_prompt else prompt
        
        data = {
            "contents": [
                {
                    "parts": [
                        {"text": full_prompt}
                    ]
                }
            ],
            "generationConfig": {
                "temperature": kwargs.get("temperature", 0.7),
                "maxOutputTokens": kwargs.get("max_tokens", 1000),
            }
        }
        
        try:
            response = requests.post(
                url,
                headers=headers,
                json=data,
                timeout=30
            )
            response.raise_for_status()
            result = response.json()
            return result["candidates"][0]["content"]["parts"][0]["text"]
        except Exception as e:
            return f"Error: {str(e)}"

class OllamaDriver(BaseDriver):
    """Ollama用のローカルLLMドライバー"""
    
    def __init__(self, base_url: str = "http://localhost:11434", **kwargs):
        super().__init__(**kwargs)
        self.base_url = base_url.rstrip('/')
    
    def complete(self, prompt: str, model: str = "llama3", **kwargs) -> str:
        """Ollama APIを使用してテキスト生成"""
        try:
            # モデルが利用可能か確認
            list_response = requests.get(f"{self.base_url}/api/tags", timeout=5)
            if list_response.status_code == 200:
                available_models = [m.get("name", "") for m in list_response.json().get("models", [])]
                if model not in available_models and available_models:
                    return f"Error: Model '{model}' not found. Available models: {', '.join(available_models)}"
            
            system_prompt = kwargs.get("system_prompt", "")
            if system_prompt:
                full_prompt = f"{system_prompt}\n\n{prompt}"
            else:
                full_prompt = prompt
            
            response = requests.post(
                f"{self.base_url}/api/generate",
                json={
                    "model": model,
                    "prompt": full_prompt,
                    "stream": False,
                    "options": {
                        "temperature": kwargs.get("temperature", 0.7)
                    }
                },
                timeout=60
            )
            response.raise_for_status()
            result = response.json()
            return result.get("response", "No response from model")
        except Exception as e:
            return f"Error: {str(e)}"

# ============================================
# Input/Output Nodes
# ============================================

class SimpleLLMTextInput:
    """テキスト入力ノード"""
    
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "text": ("STRING", {
                    "default": "",
                    "multiline": True
                }),
            }
        }
    
    RETURN_TYPES = ("STRING",)
    FUNCTION = "output_text"
    CATEGORY = "NS/LLM/Input"
    
    def output_text(self, text):
        return (text,)

# ============================================
# Agent Configuration Nodes
# ============================================

class SimpleLLMConfigOpenAI:
    """OpenAI設定ノード"""
    
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "model": (["gpt-4o-mini", "gpt-4o", "gpt-4-turbo", "gpt-4", "gpt-3.5-turbo"], {"default": "gpt-3.5-turbo"}),
                "temperature": ("FLOAT", {"default": 0.7, "min": 0.0, "max": 2.0, "step": 0.1}),
                "max_tokens": ("INT", {"default": 1000, "min": 1, "max": 4000}),
            },
            "optional": {
                "api_key": ("STRING", {"default": "", "multiline": False}),
            }
        }
    
    RETURN_TYPES = ("LLM_CONFIG",)
    FUNCTION = "create_config"
    CATEGORY = "NS/LLM/Config"
    
    def create_config(self, model, temperature, max_tokens, api_key=""):
        config = {
            "driver": "openai",
            "model": model,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "api_key": api_key or os.getenv("OPENAI_API_KEY", "")
        }
        return (config,)

class SimpleLLMConfigClaude:
    """Claude設定ノード"""
    
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "model": ([
                    "claude-3-opus-20240229",
                    "claude-3-sonnet-20240229", 
                    "claude-3-haiku-20240307",
                    "claude-2.1",
                    "claude-2.0"
                ], {"default": "claude-3-sonnet-20240229"}),
                "temperature": ("FLOAT", {"default": 0.7, "min": 0.0, "max": 1.0, "step": 0.1}),
                "max_tokens": ("INT", {"default": 1000, "min": 1, "max": 4000}),
            },
            "optional": {
                "api_key": ("STRING", {"default": "", "multiline": False}),
            }
        }
    
    RETURN_TYPES = ("LLM_CONFIG",)
    FUNCTION = "create_config"
    CATEGORY = "NS/LLM/Config"
    
    def create_config(self, model, temperature, max_tokens, api_key=""):
        config = {
            "driver": "claude",
            "model": model,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "api_key": api_key or os.getenv("ANTHROPIC_API_KEY", "")
        }
        return (config,)

class SimpleLLMConfigGemini:
    """Gemini設定ノード"""
    
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "model": ([
                    "gemini-pro",
                    "gemini-pro-vision",
                    "gemini-1.5-pro-latest",
                    "gemini-1.5-flash-latest"
                ], {"default": "gemini-pro"}),
                "temperature": ("FLOAT", {"default": 0.7, "min": 0.0, "max": 1.0, "step": 0.1}),
                "max_tokens": ("INT", {"default": 1000, "min": 1, "max": 8192}),
            },
            "optional": {
                "api_key": ("STRING", {"default": "", "multiline": False}),
            }
        }
    
    RETURN_TYPES = ("LLM_CONFIG",)
    FUNCTION = "create_config"
    CATEGORY = "NS/LLM/Config"
    
    def create_config(self, model, temperature, max_tokens, api_key=""):
        config = {
            "driver": "gemini",
            "model": model,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "api_key": api_key or os.getenv("GOOGLE_API_KEY", "")
        }
        return (config,)

class SimpleLLMConfigOllama:
    """Ollama設定ノード"""
    
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "model": ("STRING", {"default": "llama3", "multiline": False}),
                "base_url": ("STRING", {"default": "http://localhost:11434", "multiline": False}),
                "temperature": ("FLOAT", {"default": 0.7, "min": 0.0, "max": 2.0, "step": 0.1}),
            }
        }
    
    RETURN_TYPES = ("LLM_CONFIG",)
    FUNCTION = "create_config"
    CATEGORY = "NS/LLM/Config"
    
    def create_config(self, model, base_url, temperature):
        config = {
            "driver": "ollama",
            "model": model,
            "base_url": base_url,
            "temperature": temperature
        }
        return (config,)

# ============================================
# Agent Nodes
# ============================================

class SimpleLLMAgent:
    """基本的なLLMエージェント"""
    
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "config": ("LLM_CONFIG",),
                "system_prompt": ("STRING", {
                    "default": "You are a helpful AI assistant.",
                    "multiline": True
                }),
            }
        }
    
    RETURN_TYPES = ("AGENT",)
    FUNCTION = "create_agent"
    CATEGORY = "NS/LLM/Agent"
    
    def create_agent(self, config, system_prompt):
        agent = {
            "config": config,
            "system_prompt": system_prompt,
            "history": []
        }
        return (agent,)

class SimpleLLMRunPrompt:
    """プロンプトを実行"""
    
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "agent": ("AGENT",),
                "prompt": ("STRING", {"multiline": True}),
            }
        }
    
    RETURN_TYPES = ("STRING",)
    FUNCTION = "run_prompt"
    CATEGORY = "NS/LLM/Run"
    OUTPUT_NODE = False
    
    def run_prompt(self, agent, prompt):
        config = agent["config"]
        
        print(f"[SimpleLLM] Running prompt with {config.get('driver', 'unknown')} driver")
        print(f"[SimpleLLM] Model: {config.get('model', 'unknown')}")
        print(f"[SimpleLLM] Prompt: {prompt[:100]}...")
        
        # ドライバーの選択
        driver = None
        if config["driver"] == "openai":
            driver = OpenAIDriver(api_key=config.get("api_key"))
        elif config["driver"] == "claude":
            driver = ClaudeDriver(api_key=config.get("api_key"))
        elif config["driver"] == "gemini":
            driver = GeminiDriver(api_key=config.get("api_key"))
        elif config["driver"] == "ollama":
            driver = OllamaDriver(base_url=config.get("base_url", "http://localhost:11434"))
        else:
            error_msg = f"Error: Unknown driver '{config['driver']}'"
            print(f"[SimpleLLM] {error_msg}")
            return (error_msg,)
        
        # 実行
        response = driver.complete(
            prompt,
            model=config["model"],
            system_prompt=agent["system_prompt"],
            temperature=config.get("temperature", 0.7),
            max_tokens=config.get("max_tokens", 1000)
        )
        
        print(f"[SimpleLLM] Response received: {response[:200]}...")
        
        return (str(response),)

# ============================================
# Text Processing Nodes
# ============================================

class SimpleLLMMergeText:
    """複数のテキストを結合"""
    
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "text1": ("STRING", {"multiline": True}),
                "separator": ("STRING", {"default": "\n", "multiline": False}),
            },
            "optional": {
                "text2": ("STRING", {"multiline": True, "default": "", "forceInput": False}),
                "text3": ("STRING", {"multiline": True, "default": "", "forceInput": False}),
                "text4": ("STRING", {"multiline": True, "default": "", "forceInput": False}),
            }
        }
    
    RETURN_TYPES = ("STRING",)
    FUNCTION = "merge_text"
    CATEGORY = "NS/LLM/Text"
    OUTPUT_NODE = False
    
    def merge_text(self, text1, separator, text2="", text3="", text4=""):
        text1 = str(text1) if text1 is not None else ""
        text2 = str(text2) if text2 is not None else ""
        text3 = str(text3) if text3 is not None else ""
        text4 = str(text4) if text4 is not None else ""
        separator = str(separator) if separator is not None else "\n"
        
        texts = [t for t in [text1, text2, text3, text4] if t]
        merged = separator.join(texts)
        
        print(f"[SimpleLLM MergeText] Merged {len(texts)} texts, total length: {len(merged)}")
        
        return (merged,)

class SimpleLLMDisplayText:
    """テキストを表示"""
    
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "text": ("STRING", {"forceInput": True}),
            }
        }
    
    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("text",)
    OUTPUT_NODE = True
    FUNCTION = "display_text"
    CATEGORY = "NS/LLM/Output"
    
    def display_text(self, text):
        if text is None:
            text = ""
        else:
            text = str(text)
        
        print("\n" + "="*50)
        print("SimpleLLM Display Text:")
        print("-"*50)
        display_text = text[:500] if len(text) > 500 else text
        print(display_text)
        if len(text) > 500:
            print(f"... (truncated, total length: {len(text)} characters)")
        print("="*50 + "\n")
        
        return {"ui": {"text": [text]}, "result": (text,)}

class SimpleLLMStringViewer:
    """String内容を確認・パススルー"""
    
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "text": ("STRING", {"forceInput": True}),
                "prefix": ("STRING", {"default": "", "multiline": False}),
                "suffix": ("STRING", {"default": "", "multiline": False}),
            }
        }
    
    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("text",)
    OUTPUT_NODE = True
    FUNCTION = "view_string"
    CATEGORY = "NS/LLM/Output"
    
    def view_string(self, text, prefix="", suffix=""):
        if text is None:
            text = ""
        else:
            text = str(text)
        
        if prefix:
            text = str(prefix) + text
        if suffix:
            text = text + str(suffix)
        
        print(f"[SimpleLLM StringViewer] Received text: {text[:200]}...")
        print(f"[SimpleLLM StringViewer] Text length: {len(text)} chars")
        
        display_text = text
        if len(text) > 1000:
            display_text = text[:997] + "..."
        
        return {"ui": {"text": [display_text]}, "result": (text,)}
    
    @classmethod
    def IS_CHANGED(cls, text, prefix="", suffix=""):
        combined = str(text) + str(prefix) + str(suffix)
        return hashlib.md5(combined.encode()).hexdigest()

class SimpleLLMTextOutput:
    """最もシンプルなテキスト出力ノード"""
    
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "text": ("STRING", {"forceInput": True}),
            }
        }
    
    RETURN_TYPES = ()
    OUTPUT_NODE = True
    FUNCTION = "output_text"
    CATEGORY = "NS/LLM/Output"
    
    def output_text(self, text):
        text = str(text) if text is not None else ""
        print(f"[SimpleLLM TextOutput] Displaying: {text[:100]}...")
        return {"ui": {"text": [text]}}

# ============================================
# Workflow Management
# ============================================

class SimpleLLMLoadWorkflow:
    """保存されたワークフローをロード"""
    
    @classmethod
    def INPUT_TYPES(cls):
        # nodes/LLMフォルダ内のJSONファイルを検索
        llm_dir = Path(__file__).parent / "LLM"
        llm_dir.mkdir(exist_ok=True)
        
        json_files = [f.name for f in llm_dir.glob("*.json")]
        if not json_files:
            json_files = ["no_workflows_found.json"]
        
        return {
            "required": {
                "workflow": (json_files, {"default": json_files[0] if json_files else ""}),
            }
        }
    
    RETURN_TYPES = ("STRING",)
    FUNCTION = "load_workflow"
    CATEGORY = "NS/LLM/Utils"
    
    def load_workflow(self, workflow):
        llm_dir = Path(__file__).parent / "LLM"
        workflow_path = llm_dir / workflow
        
        if workflow_path.exists():
            with open(workflow_path, 'r', encoding='utf-8') as f:
                content = f.read()
            return (f"Loaded workflow: {workflow}",)
        else:
            return (f"Workflow not found: {workflow}",)

# ============================================
# Node Class Mappings - 自己完結型エクスポート
# ============================================

NODE_CLASS_MAPPINGS = {
    # Input/Output
    "SimpleLLMTextInput": SimpleLLMTextInput,
    "SimpleLLMTextOutput": SimpleLLMTextOutput,
    "SimpleLLMDisplayText": SimpleLLMDisplayText,
    "SimpleLLMStringViewer": SimpleLLMStringViewer,
    
    # Config
    "SimpleLLMConfigOpenAI": SimpleLLMConfigOpenAI,
    "SimpleLLMConfigClaude": SimpleLLMConfigClaude,
    "SimpleLLMConfigGemini": SimpleLLMConfigGemini,
    "SimpleLLMConfigOllama": SimpleLLMConfigOllama,
    
    # Agent
    "SimpleLLMAgent": SimpleLLMAgent,
    "SimpleLLMRunPrompt": SimpleLLMRunPrompt,
    
    # Text Processing
    "SimpleLLMMergeText": SimpleLLMMergeText,
    
    # Utils
    "SimpleLLMLoadWorkflow": SimpleLLMLoadWorkflow,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    # Input/Output
    "SimpleLLMTextInput": "Simple LLM: Text Input",
    "SimpleLLMTextOutput": "Simple LLM: Text Output",
    "SimpleLLMDisplayText": "Simple LLM: Display Text",
    "SimpleLLMStringViewer": "Simple LLM: String Viewer",
    
    # Config
    "SimpleLLMConfigOpenAI": "Simple LLM Config: OpenAI",
    "SimpleLLMConfigClaude": "Simple LLM Config: Claude",
    "SimpleLLMConfigGemini": "Simple LLM Config: Gemini",
    "SimpleLLMConfigOllama": "Simple LLM Config: Ollama",
    
    # Agent
    "SimpleLLMAgent": "Simple LLM Agent",
    "SimpleLLMRunPrompt": "Simple LLM Run: Prompt",
    
    # Text Processing
    "SimpleLLMMergeText": "Simple LLM: Merge Text",
    
    # Utils
    "SimpleLLMLoadWorkflow": "Simple LLM: Load Workflow",
}

# 起動時の情報表示
print("=" * 60)
print("SimpleLLM Nodes Loaded Successfully")
print("=" * 60)
print(f"Loaded {len(NODE_CLASS_MAPPINGS)} nodes in NS/LLM category")
print("Available LLM Providers:")
print("  - OpenAI GPT (gpt-3.5-turbo, gpt-4, gpt-4-turbo)")
print("  - Anthropic Claude (claude-2, claude-3)")
print("  - Google Gemini (gemini-pro, gemini-1.5)")
print("  - Ollama (local models)")
print("=" * 60)