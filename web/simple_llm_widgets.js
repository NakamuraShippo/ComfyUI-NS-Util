/**
 * SimpleLLM Widget Extensions for ComfyUI
 * Version: 1.2.0 - Integrated standalone version
 * Location: /web/simple_llm_widgets.js
 */

import { app } from "../scripts/app.js";
import { ComfyWidgets } from "../scripts/widgets.js";

// SimpleLLMノード用のカスタムウィジェット拡張
app.registerExtension({
    name: "SimpleLLM.Widgets",
    
    async beforeRegisterNodeDef(nodeType, nodeData, app) {
        // TextOutputノードの処理 - Multiline対応
        if (nodeData.name === "SimpleLLMTextOutput") {
            const onNodeCreated = nodeType.prototype.onNodeCreated;
            
            nodeType.prototype.onNodeCreated = function() {
                const ret = onNodeCreated ? onNodeCreated.apply(this, arguments) : undefined;
                
                // Multilineテキストウィジェットを作成
                const widget = ComfyWidgets.STRING(
                    this,
                    "output_text",
                    ["STRING", { multiline: true }],
                    app
                ).widget;
                
                // ウィジェットの設定
                widget.inputEl.readOnly = true;
                widget.inputEl.style.fontSize = "14px";
                widget.inputEl.style.fontFamily = "Consolas, 'Courier New', monospace";
                widget.inputEl.style.backgroundColor = "#f8f9fa";
                widget.inputEl.style.border = "1px solid #dee2e6";
                widget.inputEl.style.borderRadius = "4px";
                widget.inputEl.style.padding = "8px";
                widget.inputEl.style.minHeight = "200px";
                widget.inputEl.style.resize = "vertical";
                widget.inputEl.placeholder = "LLM output will appear here...";
                
                // ノードサイズを大きく設定
                this.setSize([500, 400]);
                
                return ret;
            };
            
            const onExecuted = nodeType.prototype.onExecuted;
            nodeType.prototype.onExecuted = function(message) {
                if (onExecuted) {
                    onExecuted.apply(this, arguments);
                }
                
                if (message && message.text) {
                    const textValue = Array.isArray(message.text) ? message.text[0] : message.text;
                    
                    const widget = this.widgets?.find(w => w.name === "output_text");
                    if (widget) {
                        widget.value = textValue || "";
                        if (widget.inputEl) {
                            widget.inputEl.value = textValue || "";
                            // 高さを自動調整
                            widget.inputEl.style.height = "auto";
                            widget.inputEl.style.height = Math.min(widget.inputEl.scrollHeight, 600) + "px";
                        }
                    }
                }
                
                app.graph.setDirtyCanvas(true, true);
            };
        }
        
        // StringViewerノードの処理 - Multiline対応
        if (nodeData.name === "SimpleLLMStringViewer") {
            const onNodeCreated = nodeType.prototype.onNodeCreated;
            
            nodeType.prototype.onNodeCreated = function() {
                const ret = onNodeCreated ? onNodeCreated.apply(this, arguments) : undefined;
                
                // Multilineテキストウィジェットを作成
                const widget = ComfyWidgets.STRING(
                    this,
                    "viewer_output",
                    ["STRING", { multiline: true }],
                    app
                ).widget;
                
                widget.inputEl.readOnly = true;
                widget.inputEl.style.opacity = "0.9";
                widget.inputEl.style.backgroundColor = "#f0f8ff";
                widget.inputEl.style.border = "1px solid #4a90e2";
                widget.inputEl.style.borderRadius = "4px";
                widget.inputEl.style.padding = "8px";
                widget.inputEl.style.minHeight = "150px";
                widget.inputEl.style.resize = "vertical";
                widget.inputEl.placeholder = "Text will appear here after execution...";
                
                // ノードサイズ調整
                this.setSize([450, 350]);
                
                return ret;
            };
            
            const onExecuted = nodeType.prototype.onExecuted;
            nodeType.prototype.onExecuted = function(message) {
                if (onExecuted) {
                    onExecuted.apply(this, arguments);
                }
                
                if (message && message.text) {
                    const textValue = Array.isArray(message.text) ? message.text[0] : message.text;
                    
                    const widget = this.widgets?.find(w => w.name === "viewer_output");
                    if (widget) {
                        widget.value = textValue || "";
                        if (widget.inputEl) {
                            widget.inputEl.value = textValue || "";
                            // 高さを自動調整
                            widget.inputEl.style.height = "auto";
                            widget.inputEl.style.height = Math.min(widget.inputEl.scrollHeight, 500) + "px";
                        }
                    }
                    
                    // ノードタイトルに文字数を表示
                    if (textValue && textValue.length > 0) {
                        this.title = `String Viewer (${textValue.length} chars)`;
                    }
                }
                
                app.graph.setDirtyCanvas(true, true);
            };
        }
        
        // DisplayTextノードの処理 - Multiline対応
        if (nodeData.name === "SimpleLLMDisplayText") {
            const onNodeCreated = nodeType.prototype.onNodeCreated;
            
            nodeType.prototype.onNodeCreated = function() {
                const ret = onNodeCreated ? onNodeCreated.apply(this, arguments) : undefined;
                
                // Multilineテキストウィジェットを作成
                const widget = ComfyWidgets.STRING(
                    this,
                    "display_output",
                    ["STRING", { multiline: true }],
                    app
                ).widget;
                
                widget.inputEl.readOnly = true;
                widget.inputEl.style.backgroundColor = "#e8f4f8";
                widget.inputEl.style.border = "2px solid #4a90e2";
                widget.inputEl.style.borderRadius = "4px";
                widget.inputEl.style.padding = "10px";
                widget.inputEl.style.fontSize = "13px";
                widget.inputEl.style.minHeight = "120px";
                widget.inputEl.style.resize = "vertical";
                
                // サイズ調整
                this.setSize([450, 300]);
                
                return ret;
            };
            
            const onExecuted = nodeType.prototype.onExecuted;
            nodeType.prototype.onExecuted = function(message) {
                if (onExecuted) {
                    onExecuted.apply(this, arguments);
                }
                
                if (message && message.text) {
                    const textValue = Array.isArray(message.text) ? message.text[0] : message.text;
                    
                    const widget = this.widgets?.find(w => w.name === "display_output");
                    if (widget) {
                        widget.value = textValue || "";
                        if (widget.inputEl) {
                            widget.inputEl.value = textValue || "";
                            // 高さを自動調整
                            widget.inputEl.style.height = "auto";
                            widget.inputEl.style.height = Math.min(widget.inputEl.scrollHeight, 400) + "px";
                        }
                    }
                }
                
                app.graph.setDirtyCanvas(true, true);
            };
        }
        
        // LLM設定ノードに検証ボタンを追加
        if (nodeData.name === "SimpleLLMConfigOllama") {
            const onNodeCreated = nodeType.prototype.onNodeCreated;
            
            nodeType.prototype.onNodeCreated = function() {
                const ret = onNodeCreated ? onNodeCreated.apply(this, arguments) : undefined;
                
                // モデル検証ボタン
                const button = this.addWidget("button", "Check Models", null, () => {
                    const baseUrlWidget = this.widgets.find(w => w.name === "base_url");
                    const url = baseUrlWidget ? baseUrlWidget.value : "http://localhost:11434";
                    
                    fetch(`${url}/api/tags`)
                        .then(response => response.json())
                        .then(data => {
                            const models = data.models || [];
                            if (models.length > 0) {
                                const modelNames = models.map(m => m.name).join("\n");
                                alert(`Available Ollama models:\n${modelNames}`);
                            } else {
                                alert("No models found. Install models with: ollama pull <model>");
                            }
                        })
                        .catch(error => {
                            alert("Cannot connect to Ollama. Make sure it's running with: ollama serve");
                        });
                });
                
                return ret;
            };
        }
        
        // API Key検証ボタンを各設定ノードに追加
        const apiConfigNodes = ["SimpleLLMConfigOpenAI", "SimpleLLMConfigClaude", "SimpleLLMConfigGemini"];
        if (apiConfigNodes.includes(nodeData.name)) {
            const onNodeCreated = nodeType.prototype.onNodeCreated;
            
            nodeType.prototype.onNodeCreated = function() {
                const ret = onNodeCreated ? onNodeCreated.apply(this, arguments) : undefined;
                
                const providerName = nodeData.name.replace("SimpleLLMConfig", "");
                
                const button = this.addWidget("button", "Validate API Key", null, () => {
                    const apiKeyWidget = this.widgets.find(w => w.name === "api_key");
                    if (apiKeyWidget && apiKeyWidget.value) {
                        alert(`${providerName} API key is set. Validation will occur on first use.`);
                    } else {
                        const envVarMap = {
                            "OpenAI": "OPENAI_API_KEY",
                            "Claude": "ANTHROPIC_API_KEY",
                            "Gemini": "GOOGLE_API_KEY"
                        };
                        const envVar = envVarMap[providerName];
                        alert(`No API key provided. Set ${envVar} environment variable or enter key above.`);
                    }
                });
                
                return ret;
            };
        }
    },
    
    // ノード実行後の共通処理
    async afterExecuted(nodeId, nodeData) {
        const node = app.graph.getNodeById(nodeId);
        if (!node) return;
        
        // SimpleLLMノードの場合、強制的にUIを更新
        if (node.type && node.type.startsWith("SimpleLLM")) {
            app.graph.setDirtyCanvas(true, true);
        }
    }
});

// ノードカラーテーマ（NSカテゴリに統合）
app.registerExtension({
    name: "SimpleLLM.Theme",
    
    async setup() {
        // NSカテゴリのLLMサブカテゴリ用カラー設定
        const theme = {
            "NS/LLM": { bgcolor: "#4a90e2", fgcolor: "#ffffff" },
            "NS/LLM/Config": { bgcolor: "#5a9fd4", fgcolor: "#ffffff" },
            "NS/LLM/Agent": { bgcolor: "#7b68ee", fgcolor: "#ffffff" },
            "NS/LLM/Run": { bgcolor: "#32cd32", fgcolor: "#000000" },
            "NS/LLM/Input": { bgcolor: "#87ceeb", fgcolor: "#000000" },
            "NS/LLM/Output": { bgcolor: "#ff69b4", fgcolor: "#ffffff" },
            "NS/LLM/Text": { bgcolor: "#ffa500", fgcolor: "#000000" },
            "NS/LLM/RAG": { bgcolor: "#cd5c5c", fgcolor: "#ffffff" },
            "NS/LLM/Advanced": { bgcolor: "#ff1493", fgcolor: "#ffffff" },
            "NS/LLM/Memory": { bgcolor: "#daa520", fgcolor: "#000000" },
            "NS/LLM/Tools": { bgcolor: "#20b2aa", fgcolor: "#ffffff" },
            "NS/LLM/Utils": { bgcolor: "#8b7355", fgcolor: "#ffffff" }
        };
        
        // LiteGraphにカラーを登録
        if (window.LGraphCanvas) {
            Object.entries(theme).forEach(([category, colors]) => {
                if (!window.LGraphCanvas.node_colors) {
                    window.LGraphCanvas.node_colors = {};
                }
                window.LGraphCanvas.node_colors[category] = colors;
            });
        }
    }
});

console.log("[SimpleLLM] Widget extensions loaded successfully for NS category");