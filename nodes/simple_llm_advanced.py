"""
SimpleLLM Advanced Nodes - 拡張機能
Version: 1.1.0 - Integrated standalone version
"""

import os
import json
import hashlib
from typing import Dict, List, Tuple, Any, Optional
from pathlib import Path

try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False
    np = None

# ============================================
# RAG Nodes
# ============================================

class SimpleLLMVectorStore:
    """ベクトルストアの作成"""
    
    def __init__(self):
        self.documents = {}
        self.embeddings = {}
    
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "name": ("STRING", {"default": "my_store", "multiline": False}),
            }
        }
    
    RETURN_TYPES = ("VECTOR_STORE",)
    FUNCTION = "create_store"
    CATEGORY = "NS/LLM/RAG"
    
    def create_store(self, name):
        store = {
            "name": name,
            "documents": {},
            "embeddings": {},
            "metadata": {},
            "created_at": ""
        }
        return (store,)

class SimpleLLMAddDocument:
    """ドキュメントをベクトルストアに追加"""
    
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "vector_store": ("VECTOR_STORE",),
                "document": ("STRING", {"multiline": True}),
                "doc_id": ("STRING", {"default": "doc_1", "multiline": False}),
            },
            "optional": {
                "metadata": ("STRING", {"default": "{}", "multiline": False}),
            }
        }
    
    RETURN_TYPES = ("VECTOR_STORE",)
    FUNCTION = "add_document"
    CATEGORY = "NS/LLM/RAG"
    
    def add_document(self, vector_store, document, doc_id, metadata="{}"):
        store = dict(vector_store)
        store["documents"] = dict(store.get("documents", {}))
        store["embeddings"] = dict(store.get("embeddings", {}))
        store["metadata"] = dict(store.get("metadata", {}))
        
        store["documents"][doc_id] = document
        embedding = hashlib.md5(document.encode()).hexdigest()
        store["embeddings"][doc_id] = embedding
        
        try:
            meta = json.loads(metadata)
        except:
            meta = {}
        store["metadata"][doc_id] = meta
        
        print(f"Added document '{doc_id}' to vector store '{store['name']}'")
        
        return (store,)

class SimpleLLMRAGQuery:
    """RAGを使用したクエリ実行"""
    
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "agent": ("AGENT",),
                "vector_store": ("VECTOR_STORE",),
                "query": ("STRING", {"multiline": True}),
                "top_k": ("INT", {"default": 3, "min": 1, "max": 10}),
            }
        }
    
    RETURN_TYPES = ("STRING",)
    FUNCTION = "query_rag"
    CATEGORY = "NS/LLM/RAG"
    
    def query_rag(self, agent, vector_store, query, top_k):
        docs = list(vector_store.get("documents", {}).values())[:top_k]
        
        if not docs:
            return ("No documents found in vector store.",)
        
        context = "\n\n".join([f"Document {i+1}:\n{doc}" for i, doc in enumerate(docs)])
        
        rag_prompt = f"""Based on the following context, answer the query.

Context:
{context}

Query: {query}

Answer:"""
        
        return (rag_prompt,)

# ============================================
# Chain of Thought
# ============================================

class SimpleLLMChainOfThought:
    """Chain of Thought推論を実行"""
    
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "agent": ("AGENT",),
                "problem": ("STRING", {"multiline": True}),
                "steps": ("INT", {"default": 3, "min": 1, "max": 10}),
            }
        }
    
    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("reasoning", "answer")
    FUNCTION = "chain_of_thought"
    CATEGORY = "NS/LLM/Advanced"
    
    def chain_of_thought(self, agent, problem, steps):
        cot_prompt = f"""Solve this problem step by step.

Problem: {problem}

Let's think through this in {steps} steps:
"""
        
        for i in range(1, steps + 1):
            cot_prompt += f"\nStep {i}: [Describe step {i} of your reasoning]"
        
        cot_prompt += "\n\nFinal Answer: [Your conclusive answer based on the above reasoning]"
        
        reasoning = f"Chain of Thought reasoning for: {problem}\n"
        reasoning += f"Using {steps} reasoning steps.\n"
        reasoning += "Note: Actual reasoning requires LLM execution."
        
        answer = "Final answer would appear here after LLM processing."
        
        return (reasoning, answer)

# ============================================
# Memory Management
# ============================================

class SimpleLLMMemoryBank:
    """エージェントのメモリバンク"""
    
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "name": ("STRING", {"default": "main_memory", "multiline": False}),
                "capacity": ("INT", {"default": 10, "min": 1, "max": 100}),
            }
        }
    
    RETURN_TYPES = ("MEMORY_BANK",)
    FUNCTION = "create_memory"
    CATEGORY = "NS/LLM/Memory"
    
    def create_memory(self, name, capacity):
        memory = {
            "name": name,
            "capacity": capacity,
            "memories": [],
            "current_size": 0
        }
        return (memory,)

class SimpleLLMAddMemory:
    """メモリバンクに記憶を追加"""
    
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "memory_bank": ("MEMORY_BANK",),
                "memory_content": ("STRING", {"multiline": True}),
                "importance": ("FLOAT", {"default": 0.5, "min": 0.0, "max": 1.0, "step": 0.1}),
            }
        }
    
    RETURN_TYPES = ("MEMORY_BANK",)
    FUNCTION = "add_memory"
    CATEGORY = "NS/LLM/Memory"
    
    def add_memory(self, memory_bank, memory_content, importance):
        bank = dict(memory_bank)
        bank["memories"] = list(bank.get("memories", []))
        
        new_memory = {
            "content": memory_content,
            "importance": importance,
            "timestamp": ""
        }
        
        bank["memories"].append(new_memory)
        
        # 容量制限を適用
        if len(bank["memories"]) > bank["capacity"]:
            bank["memories"].sort(key=lambda x: x["importance"], reverse=True)
            bank["memories"] = bank["memories"][:bank["capacity"]]
        
        bank["current_size"] = len(bank["memories"])
        
        return (bank,)

# ============================================
# Tool Conversion
# ============================================

class SimpleLLMAgentToTool:
    """エージェントをツールに変換"""
    
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "agent": ("AGENT",),
                "tool_name": ("STRING", {"default": "agent_tool", "multiline": False}),
                "tool_description": ("STRING", {
                    "default": "An AI agent that can answer questions",
                    "multiline": True
                }),
            }
        }
    
    RETURN_TYPES = ("TOOL",)
    FUNCTION = "convert_to_tool"
    CATEGORY = "NS/LLM/Tools"
    
    def convert_to_tool(self, agent, tool_name, tool_description):
        tool = {
            "name": tool_name,
            "description": tool_description,
            "type": "agent",
            "agent": agent,
            "parameters": {
                "query": {"type": "string", "description": "The query to send to the agent"}
            }
        }
        return (tool,)

# ============================================
# Advanced Agent Types
# ============================================

class SimpleLLMAgentWithRules:
    """ルールセット付きエージェント"""
    
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "config": ("LLM_CONFIG",),
                "system_prompt": ("STRING", {"multiline": True}),
                "rules": ("STRING", {
                    "default": "1. Be helpful and accurate\n2. Avoid harmful content\n3. Stay on topic",
                    "multiline": True
                }),
            }
        }
    
    RETURN_TYPES = ("AGENT",)
    FUNCTION = "create_agent"
    CATEGORY = "NS/LLM/Agent"
    
    def create_agent(self, config, system_prompt, rules):
        # ルールをシステムプロンプトに統合
        rules_list = rules.split('\n')
        rules_text = "\n".join([f"- {rule}" for rule in rules_list if rule.strip()])
        enhanced_prompt = f"{system_prompt}\n\nYou must follow these rules:\n{rules_text}"
        
        agent = {
            "config": config,
            "system_prompt": enhanced_prompt,
            "rules": rules_list,
            "history": []
        }
        return (agent,)

# ============================================
# Node Class Mappings - 自己完結型エクスポート
# ============================================

NODE_CLASS_MAPPINGS = {
    # RAG
    "SimpleLLMVectorStore": SimpleLLMVectorStore,
    "SimpleLLMAddDocument": SimpleLLMAddDocument,
    "SimpleLLMRAGQuery": SimpleLLMRAGQuery,
    
    # Advanced
    "SimpleLLMChainOfThought": SimpleLLMChainOfThought,
    
    # Memory
    "SimpleLLMMemoryBank": SimpleLLMMemoryBank,
    "SimpleLLMAddMemory": SimpleLLMAddMemory,
    
    # Tools
    "SimpleLLMAgentToTool": SimpleLLMAgentToTool,
    
    # Advanced Agent
    "SimpleLLMAgentWithRules": SimpleLLMAgentWithRules,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    # RAG
    "SimpleLLMVectorStore": "Simple LLM: Vector Store",
    "SimpleLLMAddDocument": "Simple LLM: Add Document",
    "SimpleLLMRAGQuery": "Simple LLM: RAG Query",
    
    # Advanced
    "SimpleLLMChainOfThought": "Simple LLM: Chain of Thought",
    
    # Memory
    "SimpleLLMMemoryBank": "Simple LLM: Memory Bank",
    "SimpleLLMAddMemory": "Simple LLM: Add Memory",
    
    # Tools
    "SimpleLLMAgentToTool": "Simple LLM: Agent to Tool",
    
    # Advanced Agent
    "SimpleLLMAgentWithRules": "Simple LLM: Agent with Rules",
}

# 起動時の情報表示
print("SimpleLLM Advanced Nodes Loaded")
print(f"Added {len(NODE_CLASS_MAPPINGS)} advanced nodes to NS/LLM category")