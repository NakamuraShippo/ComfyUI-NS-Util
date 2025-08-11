import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

const TEXTAREA_H = 60;

// グローバル変数として追加
let isLoadingWorkflow = false;

// NS-FlexPreset Extension
app.registerExtension({
    name: "NS.FlexPreset",
    
    // Type validation regexes
    TYPE_REGEX: {
        'int': /^-?[0-9]+$/,
        'float': /^-?[0-9]*\.?[0-9]+$/,
        'string': /.*/
    },
    
    async setup() {
        // ワークフローロード開始・終了を検知
        api.addEventListener("execution_start", () => {
            isLoadingWorkflow = false;
        });
        
        api.addEventListener("graphChanged", () => {
            isLoadingWorkflow = false;
        });
        
        // Listen for enum updates from backend
        api.addEventListener("ns_flexpreset_enum", (event) => {
            const data = event.detail;
            updateNodeEnums(data);
        });
        
        // Listen for widget updates
        api.addEventListener("ns_flexpreset_set_widgets", (event) => {
            const data = event.detail;
            updateNodeWidgets(data);
        });
        // Canvas transform時のtextarea位置更新
        if (app.canvas && app.canvas.canvas) {
            app.canvas.canvas.addEventListener('wheel', () => {
                updateTextareaPositions();
            });
            
            app.canvas.canvas.addEventListener('mousedown', () => {
                updateTextareaPositions();
            });
            
            app.canvas.canvas.addEventListener('mousemove', (e) => {
                if (e.buttons === 1) {  // ドラッグ中
                    updateTextareaPositions();
                }
            });
        }
    },

    async nodeCreated(node) {
        if (node.comfyClass !== "NS-FlexPreset") return;
        
        // Store original widgets
        node._nsFlexPresetWidgets = {
            select_yaml: null,
            select_preset: null,
            input_preset_name: null,
            value_panels: [],
            bottom_separator: null,
            select_value: null,
            btn_add_value: null,
            btn_del_value: null,
            outputs_signature: "",
            user_resized: false,
            textareas: [],
            panel_order: []  // ★追加: panel_orderを初期化
        };
        
        // Find existing widgets
        for (const widget of node.widgets) {
            if (widget.name === "select_yaml") {
                node._nsFlexPresetWidgets.select_yaml = widget;
            } else if (widget.name === "select_preset") {
                node._nsFlexPresetWidgets.select_preset = widget;
            } else if (widget.name === "input_preset_name") {
                node._nsFlexPresetWidgets.input_preset_name = widget;
            }
        }
        
        // Setup widget change handlers
        setupWidgetHandlers(node);
        
        // Add custom widgets after existing ones
        addCustomWidgets(node);
        
        // Store reference for updates
        node._nsFlexPresetNode = true;
        
        // Track user resize
        const originalOnResize = node.onResize;
        node.onResize = function(size) {
            node._nsFlexPresetWidgets.user_resized = true;
            if (originalOnResize) {
                originalOnResize.call(this, size);
            }
        };
        
        // Override node removal to clean up textareas
        const originalOnRemoved = node.onRemoved;
        node.onRemoved = function() {
            cleanupNodeTextareas(this);
            if (originalOnRemoved) {
                originalOnRemoved.call(this);
            }
        };
        
        // Initial data load
        if (node._nsFlexPresetWidgets.select_yaml && node._nsFlexPresetWidgets.select_yaml.value) {
            loadPromptData(node);
        }
    },

    // ワークフローロード時の処理を追加
    async loadedGraphNode(node) {
        if (node.comfyClass !== "NS-FlexPreset") return;
        
        // ワークフローロード中フラグを設定
        isLoadingWorkflow = true;
        
        // 接続情報を詳細に保存
        const savedConnections = [];
        
        if (node.outputs && node.outputs.length > 0) {
            for (let i = 0; i < node.outputs.length; i++) {
                const output = node.outputs[i];
                if (output && output.links && output.links.length > 0) {
                    // 各リンクの詳細情報を保存
                    for (const linkId of output.links) {
                        const link = app.graph.links[linkId];
                        if (link) {
                            savedConnections.push({
                                outputIndex: i,
                                outputName: output.name,
                                outputType: output.type,
                                linkId: linkId,
                                link: link,  // リンクオブジェクト全体を保存
                                target_id: link.target_id,
                                target_slot: link.target_slot
                            });
                        }
                    }
                }
            }
        }
        
        // 接続情報を一時的に保存
        node._savedWorkflowConnections = savedConnections;
            
        // ワークフローロード完了後、値が設定されているかチェック
        if (node._nsFlexPresetWidgets && 
            node._nsFlexPresetWidgets.select_yaml && 
            node._nsFlexPresetWidgets.select_yaml.value) {
            
            const yamlValue = node._nsFlexPresetWidgets.select_yaml.value;
            const titleValue = node._nsFlexPresetWidgets.input_preset_name?.value || 
                            node._nsFlexPresetWidgets.select_preset?.value;
            
            if (yamlValue && titleValue) {
                // ワークフローロード中の特別フラグ
                node._skipOutputUpdate = true;
                
                try {
                    // バックエンドに動的出力の更新を要求
                    const response = await api.fetchApi("/ns_flexpreset/get_prompt", {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({
                            yaml: yamlValue,
                            title: titleValue,
                            node_id: node.id,
                            init_outputs: true
                        })
                    });
                    
                    // レスポンスを待ってから処理を続行
                    if (response.ok) {
                        // WebSocketイベントを待つ
                        await new Promise(resolve => setTimeout(resolve, 100));
                    }
                } catch (error) {
                    console.error("Error initializing outputs:", error);
                }
                
                // データロードと接続復元を実行
                setTimeout(() => {
                    console.log("Loading preset data on workflow load:", {
                        yaml: yamlValue,
                        title: titleValue,
                        savedConnections: savedConnections.length
                    });
                    
                    // ノードの出力を強制的に更新
                    updateNodeOutputs(node, true);
                    
                    // さらに遅延して接続を復元
                    setTimeout(() => {
                        node._skipOutputUpdate = false;
                        restoreWorkflowConnections(node);
                        isLoadingWorkflow = false;
                    }, 300);
                }, 200);  // 少し遅延を増やす
            } else {
                isLoadingWorkflow = false;
            }
        } else {
            isLoadingWorkflow = false;
        }
    },

    async beforeRegisterNodeDef(nodeType, nodeData, app) {
        if (nodeData.name === "NS-FlexPreset") {
            // Store original onExecuted if exists
            const onExecuted = nodeType.prototype.onExecuted;
            
            nodeType.prototype.onExecuted = function(message) {
                // Update dynamic outputs
                updateNodeOutputs(this, true);
                
                // Call original if exists
                if (onExecuted) {
                    onExecuted.apply(this, arguments);
                }
            };
        }
    }
});

function updateTextareaPositions() {
    const nodes = app.graph._nodes.filter(n => n._nsFlexPresetNode);
    
    for (const node of nodes) {
        if (node._nsFlexPresetWidgets && node._nsFlexPresetWidgets.value_panels) {
            // Force all widgets to redraw
            app.graph.setDirtyCanvas(true, true);
        }
    }
}

function restoreWorkflowConnections(node) {
    if (!node._savedWorkflowConnections || node._savedWorkflowConnections.length === 0) {
        return;
    }
    
    const savedConnections = node._savedWorkflowConnections;
    delete node._savedWorkflowConnections;
    
    console.log("Restoring connections:", savedConnections.length);
    
    // 保存した接続を復元
    for (const conn of savedConnections) {
        // 出力名で一致するものを探す
        let outputIndex = -1;
        for (let i = 0; i < node.outputs.length; i++) {
            if (node.outputs[i].name === conn.outputName) {
                outputIndex = i;
                break;
            }
        }
        
        // 名前で見つからない場合、インデックスとタイプで確認
        if (outputIndex === -1 && conn.outputIndex < node.outputs.length) {
            if (node.outputs[conn.outputIndex].type === conn.outputType) {
                outputIndex = conn.outputIndex;
            }
        }
        
        // 接続を復元
        if (outputIndex >= 0 && conn.link) {
            try {
                // 既存の接続を確認
                const targetNode = app.graph._nodes.find(n => n.id === conn.target_id);
                if (targetNode && targetNode.inputs && targetNode.inputs[conn.target_slot]) {
                    // 新しい接続を作成
                    node.connect(outputIndex, conn.target_id, conn.target_slot);
                    console.log(`Restored connection: ${node.outputs[outputIndex].name} -> ${targetNode.title}`);
                }
            } catch (e) {
                console.warn("Failed to restore connection:", e);
            }
        }
    }
    
    // グラフを更新
    app.graph.setDirtyCanvas(true);
}

// Cleanup all textareas for a node
function cleanupNodeTextareas(node) {
    if (node._nsFlexPresetWidgets && node._nsFlexPresetWidgets.textareas) {
        for (const textarea of node._nsFlexPresetWidgets.textareas) {
            if (textarea && textarea.parentNode) {
                textarea.parentNode.removeChild(textarea);
            }
        }
        node._nsFlexPresetWidgets.textareas = [];
    }
    
    // Also cleanup from panels
    if (node._nsFlexPresetWidgets && node._nsFlexPresetWidgets.value_panels) {
        for (const panel of node._nsFlexPresetWidgets.value_panels) {
            for (const widget of panel.widgets) {
                if (widget.textarea && widget.textarea.parentNode) {
                    widget.textarea.parentNode.removeChild(widget.textarea);
                }
            }
        }
    }
}

// Validate value type
function validateValueType(type, value) {
    const regex = {
        'int': /^-?[0-9]+$/,
        'float': /^-?[0-9]*\.?[0-9]+$/,
        'string': /.*/
    };
    
    if (!regex[type]) return false;
    return regex[type].test(String(value));
}

function setupWidgetHandlers(node) {
    // Handle YAML selection change
    if (node._nsFlexPresetWidgets.select_yaml) {
        const origCallback = node._nsFlexPresetWidgets.select_yaml.callback;
        node._nsFlexPresetWidgets.select_yaml.callback = async function(v) {
            if (origCallback) origCallback.call(this, v);
            
            // Set waiting flag and disable select_preset
            node.__waitingEnum = true;
            if (node._nsFlexPresetWidgets.select_preset) {
                node._nsFlexPresetWidgets.select_preset.disabled = true;
            }
            
            // Reload YAML data from backend
            try {
                await api.fetchApi("/ns_flexpreset/reload_yamls", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" }
                });
            } catch (error) {
                console.error("Error reloading YAMLs:", error);
                // Clear waiting flag on error
                node.__waitingEnum = false;
                if (node._nsFlexPresetWidgets.select_preset) {
                    node._nsFlexPresetWidgets.select_preset.disabled = false;
                }
            }
            
            // Don't update title options here - let websocket event handle it
            
            // Load data for current title
            loadPromptData(node);
        };
    }
    
    // Handle title selection change (bidirectional sync)
    if (node._nsFlexPresetWidgets.select_preset) {
        const origCallback = node._nsFlexPresetWidgets.select_preset.callback;
        node._nsFlexPresetWidgets.select_preset.callback = function(v) {
            if (origCallback) origCallback.call(this, v);
            
            // ★追加: プリセット切り替え時にpanel_orderをクリア
            node._nsFlexPresetWidgets.panel_order = [];
            
            // Update input_preset_name to match selection
            if (node._nsFlexPresetWidgets.input_preset_name && node._nsFlexPresetWidgets.input_preset_name.value !== v) {
                node._nsFlexPresetWidgets.input_preset_name.value = v;
            }
            
            // Load prompt data
            loadPromptData(node);
        };
    }
    
    // Handle input title change (bidirectional sync)
    if (node._nsFlexPresetWidgets.input_preset_name) {
        const origCallback = node._nsFlexPresetWidgets.input_preset_name.callback;
        node._nsFlexPresetWidgets.input_preset_name.callback = function(v) {
            if (origCallback) origCallback.call(this, v);
            
            // ★追加: プリセット切り替え時にpanel_orderをクリア
            node._nsFlexPresetWidgets.panel_order = [];
            
            // Update select_preset if the value exists in options
            if (node._nsFlexPresetWidgets.select_preset) {
                const options = node._nsFlexPresetWidgets.select_preset.options.values;
                if (options.includes(v)) {
                    node._nsFlexPresetWidgets.select_preset.value = v;
                } else {
                    // Add to options if not exists
                    updateTitleOptions(node, null, v);
                }
            }
            
            // Load or create data for new title
            loadPromptData(node);
        };
    }
}

function addCustomWidgets(node) {
    // Add bottom separator for value panels
    const bottomSeparator = node.addCustomWidget({
        name: "bottom_separator",
        draw: function(ctx, node, widget_width, y, H) {
            const margin = 15;
            const lineY = y + 5;
            
            // Set style
            ctx.strokeStyle = "#444";
            ctx.lineWidth = 1;
            ctx.setLineDash([5, 3]);
            
            // Draw full dashed line
            ctx.beginPath();
            ctx.moveTo(margin, lineY);
            ctx.lineTo(widget_width - margin, lineY);
            ctx.stroke();
            
            // Reset line dash
            ctx.setLineDash([]);
            
            return 15;  // Widget height
        },
        computeSize: function() { return [0, 15]; },
        serialize: false
    });
    node._nsFlexPresetWidgets.bottom_separator = bottomSeparator;
    
    // Add value selector
    const selectValue = node.addWidget(
        "combo",
        "select_value",
        "",
        (v) => {
            // Update delete button label
            if (node._nsFlexPresetWidgets.btn_del_value) {
                node._nsFlexPresetWidgets.btn_del_value.name = v ? `Delete [${v}]` : "Delete Value";
            }
        },
        { values: [""], serialize: false }
    );
    node._nsFlexPresetWidgets.select_value = selectValue;
    
    // Add buttons
    const btnAdd = node.addWidget(
        "button",
        "Add Value",
        null,
        () => { addValuePanel(node); },
        { serialize: false }
    );
    node._nsFlexPresetWidgets.btn_add_value = btnAdd;
    
    const btnDel = node.addWidget(
        "button", 
        "Delete Value",
        null,
        () => { deleteValue(node); },
        { serialize: false }
    );
    node._nsFlexPresetWidgets.btn_del_value = btnDel;
}

function updateNodeEnums(data) {
    const nodes = app.graph._nodes.filter(n => n._nsFlexPresetNode);
    
    for (const node of nodes) {
        // Clear waiting flag and re-enable select_preset
        if (node.__waitingEnum) {
            node.__waitingEnum = false;
            if (node._nsFlexPresetWidgets.select_preset) {
                node._nsFlexPresetWidgets.select_preset.disabled = false;
            }
        }
        
        // Update YAML files
        if (node._nsFlexPresetWidgets.select_yaml && data.yaml_files) {
            node._nsFlexPresetWidgets.select_yaml.options.values = data.yaml_files;
            
            // Keep current value if still valid
            if (!data.yaml_files.includes(node._nsFlexPresetWidgets.select_yaml.value)) {
                node._nsFlexPresetWidgets.select_yaml.value = data.yaml_files[0] || "";
            }
        }
        
        // Update titles for current YAML
        updateTitleOptions(node, data);
        
        // Update value options
        updateValueOptions(node, data);
    }
}

function updateTitleOptions(node, enumData, newTitle) {
    if (!node._nsFlexPresetWidgets.select_preset) return;
    
    const yamlFile = node._nsFlexPresetWidgets.select_yaml?.value;
    if (!yamlFile) return;
    
    let titles = [""];
    
    if (enumData && enumData.titles_by_yaml && enumData.titles_by_yaml[yamlFile]) {
        titles = ["", ...enumData.titles_by_yaml[yamlFile]];
    }
    
    // Add new title if provided
    if (newTitle && !titles.includes(newTitle)) {
        titles.push(newTitle);
    }
    
    node._nsFlexPresetWidgets.select_preset.options.values = titles;
    
    // Keep current value if still valid
    if (!titles.includes(node._nsFlexPresetWidgets.select_preset.value)) {
        node._nsFlexPresetWidgets.select_preset.value = "";
    }
}

function updateValueOptions(node, enumData) {
    if (!node._nsFlexPresetWidgets.select_value) return;
    
    const yamlFile = node._nsFlexPresetWidgets.select_yaml?.value;
    const title = node._nsFlexPresetWidgets.input_preset_name?.value || node._nsFlexPresetWidgets.select_preset?.value;
    
    if (!yamlFile || !title) {
        node._nsFlexPresetWidgets.select_value.options.values = [""];
        node._nsFlexPresetWidgets.select_value.value = "";
        return;
    }
    
    const key = `${yamlFile}::${title}`;
    let values = [""];
    
    if (enumData && enumData.values_by_yaml_title && enumData.values_by_yaml_title[key]) {
        values = ["", ...enumData.values_by_yaml_title[key]];
    }
    
    node._nsFlexPresetWidgets.select_value.options.values = values;
    
    // Keep current value if still valid
    if (!values.includes(node._nsFlexPresetWidgets.select_value.value)) {
        node._nsFlexPresetWidgets.select_value.value = "";
    }
}

function updateNodeWidgets(data) {
    const nodes = app.graph._nodes.filter(n => n._nsFlexPresetNode);
    
    for (const node of nodes) {
        // Check if this update is for this specific node
        if (data.node_id && node.id !== data.node_id) {
            continue;
        }
        
        // ワークフローロード中でも、初期化時は出力を更新
        const isFullRefresh = data.refresh_outputs !== false && 
                            (!isLoadingWorkflow || data.outputs);
        
        // Clear existing value panels properly
        clearValuePanels(node);
        
        // ★追加: keys_orderがある場合はpanel_orderをリセット
        if (data.keys_order && data.keys_order.length > 0) {
            // 新しいプリセットの順序でpanel_orderを初期化
            node._nsFlexPresetWidgets.panel_order = data.keys_order.slice();
        }
        
        // Add value panels for each value
        if (data.values) {
            let keysToProcess = [];
            
            // Use keys_order from backend if available
            if (data.keys_order && data.keys_order.length > 0) {
                keysToProcess = data.keys_order;
            } else {
                // Fallback to object keys
                keysToProcess = Object.keys(data.values);
            }
            
            // Create panels in the determined order
            for (const key of keysToProcess) {
                if (key in data.values) {
                    createValuePanel(node, key, data.values[key]);
                }
            }
        }
        
        // ★修正: panel_orderを送信する前に、実際のパネル順序と同期
        node._nsFlexPresetWidgets.panel_order = node._nsFlexPresetWidgets.value_panels.map(p => p.key);
        
        // Send panel order after creating all panels
        sendPanelOrder(node);
        
        // If no title after deletion, select first available
        if (!data.title && node._nsFlexPresetWidgets.select_preset) {
            const titles = node._nsFlexPresetWidgets.select_preset.options.values;
            if (titles.length > 1) {
                node._nsFlexPresetWidgets.select_preset.value = titles[1];
                node._nsFlexPresetWidgets.input_preset_name.value = titles[1];
                loadPromptData(node);
            }
        }
        
        // 出力情報が含まれている場合は強制的に更新
        if (data.outputs && data.output_names) {
            // 出力を手動で設定
            while (node.outputs.length > 0) {
                node.removeOutput(0);
            }
            
            for (let i = 0; i < data.outputs.length; i++) {
                const outputType = data.outputs[i];
                const outputName = data.output_names[i];
                node.addOutput(outputName, outputType);
            }
            
            // グラフを更新
            app.graph.setDirtyCanvas(true);
        } else if (isFullRefresh) {
            // 通常の更新
            updateNodeOutputs(node, true);
        }
    }
}

// C3: Send panel order to backend
async function sendPanelOrder(node) {
    const panelOrder = node._nsFlexPresetWidgets.value_panels.map(p => p.key);
    
    try {
        await api.fetchApi("/ns_flexpreset/update_panel_order", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                panel_order: panelOrder,
                node_id: node.id
            })
        });
    } catch (error) {
        console.error("Error updating panel order:", error);
    }
}

function clearValuePanels(node) {
    // Remove existing value panel widgets
    const panelWidgets = node._nsFlexPresetWidgets.value_panels;
    
    for (const panel of panelWidgets) {
        for (const widget of panel.widgets) {
            // Clean up textarea if exists
            if (widget.textarea) {
                const idx = node._nsFlexPresetWidgets.textareas.indexOf(widget.textarea);
                if (idx >= 0) {
                    node._nsFlexPresetWidgets.textareas.splice(idx, 1);
                }
                if (widget.textarea.parentNode) {
                    widget.textarea.parentNode.removeChild(widget.textarea);
                }
            }
            
            const idx = node.widgets.indexOf(widget);
            if (idx >= 0) {
                node.widgets.splice(idx, 1);
            }
        }
    }
    
    node._nsFlexPresetWidgets.value_panels = [];
}

function createValuePanel(node, key, valueData, isNewValue = false) {
    const panel = {
        key: key,
        widgets: []
    };
    
    // Always append new panels at the end (before control widgets)
    let insertIdx;
    const bottomSeparatorIdx = node.widgets.findIndex(w => w.name === "bottom_separator");
    
    if (isNewValue) {
        // For new values added by user, insert at bottom of value panels
        if (bottomSeparatorIdx >= 0) {
            insertIdx = bottomSeparatorIdx;
        } else {
            // Fallback: 5 widgets from end (bottom_separator, select_value, btn_add, btn_del)
            insertIdx = Math.max(0, node.widgets.length - 4);
        }
    } else {
        // For existing values from YAML, also append at bottom to maintain order
        if (bottomSeparatorIdx >= 0) {
            insertIdx = bottomSeparatorIdx;
        } else {
            insertIdx = Math.max(0, node.widgets.length - 4);
        }
    }
    
    // Add separator with key name
    const separatorWidget = node.addCustomWidget({
        name: `separator_${key}`,
        draw: function(ctx, node, widget_width, y, H) {
            const margin = 15;
            // Get current key from panel
            const currentPanel = node._nsFlexPresetWidgets.value_panels.find(p => 
                p.widgets.includes(this)
            );
            const text = currentPanel ? currentPanel.key : key;
            
            // Set style
            ctx.strokeStyle = "#444";
            ctx.fillStyle = "#ccc";
            ctx.font = "bold 12px Arial";
            ctx.lineWidth = 1;
            
            // Measure text
            const textMetrics = ctx.measureText(text);
            const textWidth = textMetrics.width;
            const lineY = y + 15;
            
            // Draw left dashed line
            const leftLineEnd = (widget_width - textWidth) / 2 - 15;
            ctx.setLineDash([5, 3]);
            ctx.beginPath();
            ctx.moveTo(margin, lineY);
            ctx.lineTo(leftLineEnd, lineY);
            ctx.stroke();
            
            // Draw text
            const textX = (widget_width - textWidth) / 2;
            ctx.fillText(text, textX, lineY + 3);
            
            // Draw right dashed line
            const rightLineStart = (widget_width + textWidth) / 2 + 15;
            ctx.beginPath();
            ctx.moveTo(rightLineStart, lineY);
            ctx.lineTo(widget_width - margin, lineY);
            ctx.stroke();
            
            // Reset line dash
            ctx.setLineDash([]);
            
            return 25;  // Widget height with margin
        },
        computeSize: function() { return [0, 25]; },
        serialize: false
    });
    
    // Add key label (editable)
    const keyWidget = node.addWidget(
        "text",
        `Name`,
        key,
        (v) => { updateKeyName(node, key, v); },
        { serialize: false }
    );
    
    // Add type selector
    const typeWidget = node.addWidget(
        "combo",
        `Type`,
        valueData.type || "string",
        (v) => { updateValueType(node, key, v); },
        { values: ["int", "float", "string"], serialize: false }
    );
    
    // Add value input based on type
    let valueWidget;
    const currentValue = valueData.value || "";
    
    if (valueData.type === 'int') {
        // Use number widget with integer precision
        const intValue = parseInt(currentValue) || 0;
        valueWidget = node.addWidget(
            "number",
            `Value`,
            intValue,
            (v) => { 
                // Ensure integer value
                const intVal = Math.round(v);
                widget.value = intVal;  // Update widget display
                updateValueContent(node, key, intVal); 
            },
            { 
                precision: 0,
                step: 1,
                min: -999999,
                max: 999999
            }
        );
        // Store reference to widget for callback
        const widget = valueWidget;
    } else if (valueData.type === 'float') {
        // Use number widget with float precision (2 decimal places)
        const floatValue = parseFloat(currentValue) || 0.0;
        valueWidget = node.addWidget(
            "number",
            `Value`,
            floatValue,
            (v) => { 
                // Round to 2 decimal places
                const roundedVal = Math.round(v * 100) / 100;
                updateValueContent(node, key, roundedVal); 
            },
            { 
                precision: 2,
                step: 0.01,
                min: -999999.99,
                max: 999999.99
            }
        );
    } else {
        // Use custom textarea widget for string type
        valueWidget = node.addCustomWidget({
            name: `Value`,
            draw: function(ctx, node, widget_width, y, H) {
                const margin = 15;
                const textarea_height = 60;  // Fixed height for textarea
                
                // Draw label
                ctx.fillStyle = "#999";
                ctx.font = "12px Arial";
                ctx.fillText(this.name, margin, y + 12);
                
                // Create textarea if not exists
                if (!this.textarea) {
                    this.textarea = document.createElement("textarea");
                    this.textarea.className = "comfy-multiline-input";
                    // フォーカスが当たっていないときだけ同期する
                    if (document.activeElement !== this.textarea) {
                        this.textarea.value = this.value || "";
                    }
                    this.textarea.style.position = "absolute";
                    this.textarea.style.width = (widget_width - margin * 2) + "px";
                    this.textarea.style.height = textarea_height + "px";
                    this.textarea.style.resize = "vertical";
                    this.textarea.style.fontSize = "12px";
                    this.textarea.style.fontFamily = "monospace";
                    this.textarea.style.border = "1px solid #555";
                    this.textarea.style.borderRadius = "4px";
                    this.textarea.style.backgroundColor = "#1a1a1a";
                    this.textarea.style.color = "#ddd";
                    this.textarea.style.padding = "4px";
                    this.textarea.style.zIndex = "1";
                    this.textarea.style.pointerEvents = "auto";
                    
                    // Store key reference for callback
                    const storedKey = key;
                    const self = this;
                    
                    // Add event listeners
                    this.textarea.addEventListener("input", (e) => {
                        self.value = e.target.value;
                        if (self.callback) {
                            self.callback(self.value);
                        }
                    });
                    
                    this.textarea.addEventListener("focus", (e) => {
                        app.canvas.skip_events = true;
                    });
                    
                    this.textarea.addEventListener("blur", (e) => {
                        app.canvas.skip_events = false;
                    });
                    
                    this.textarea.addEventListener("mousedown", (e) => {
                        e.stopPropagation();
                    });
                    
                    // Append to canvas container instead of body
                    const canvasParent = app.canvas.canvas.parentElement;
                    canvasParent.appendChild(this.textarea);
                    
                    // Track textarea in node
                    if (!node._nsFlexPresetWidgets.textareas) {
                        node._nsFlexPresetWidgets.textareas = [];
                    }
                    node._nsFlexPresetWidgets.textareas.push(this.textarea);
                }
                
                // Update textarea position relative to canvas
                if (this.textarea) {
                    const canvas = app.canvas.canvas;
                    const rect = canvas.getBoundingClientRect();
                    const scaleX = app.canvas.ds.scale;
                    const scaleY = app.canvas.ds.scale;
                    
                    // Calculate absolute position
                    const nodeX = (node.pos[0] + app.canvas.ds.offset[0]) * scaleX;
                    const nodeY = (node.pos[1] + app.canvas.ds.offset[1]) * scaleY;
                    
                    this.textarea.style.left = (nodeX + margin * scaleX) + "px";
                    this.textarea.style.top = (nodeY + (y + 20) * scaleY) + "px";
                    this.textarea.style.width = ((widget_width - margin * 2) * scaleX) + "px";
                    this.textarea.style.height = (textarea_height * scaleY) + "px";
                    this.textarea.style.fontSize = (12 * scaleY) + "px";
                    
                    // Hide if too small
                    this.textarea.style.display = scaleX > 0.5 ? "block" : "none";
                }
                
                return 20 + textarea_height;  // Widget height
            },

            computeSize: function(width) {
                const textarea_height = 60;   // draw と同じ値
                return [width, 20 + textarea_height];
            },

            value: currentValue,
            callback: (v) => { updateValueContent(node, key, v); },
            serialize: false
        });
        
        valueWidget.name = `Value`;
        valueWidget.value = currentValue;
    }
    
    // Store widgets in panel (including separator)
    panel.widgets = [separatorWidget, keyWidget, typeWidget, valueWidget];
    
    // Move all four widgets to correct position as a group
    const addedWidgets = node.widgets.splice(-4);
    node.widgets.splice(insertIdx, 0, ...addedWidgets);
    
    node._nsFlexPresetWidgets.value_panels.push(panel);

    // ユーザーが手動リサイズしていない場合だけ自動リサイズ
    if (!node._nsFlexPresetWidgets.user_resized) {
        node.setSize(node.computeSize());
    }
}

// Add empty value panel
function addValuePanel(node) {
    const yamlFile = node._nsFlexPresetWidgets.select_yaml?.value;
    const title = node._nsFlexPresetWidgets.input_preset_name?.value || node._nsFlexPresetWidgets.select_preset?.value;
    
    if (!yamlFile || !title) {
        alert("Please select a YAML file and enter a title first");
        return;
    }
    
    // A10: Generate unique key name using timestamp
    const timestamp = Date.now();
    const newKey = `key_${timestamp}`;
    
    // Create panel with isNewValue=true to append at bottom
    createValuePanel(node, newKey, { type: 'string', value: '' }, true);
    
    // C3: Send updated panel order
    sendPanelOrder(node);
    
    // Save to backend - with flag to not refresh outputs
    saveValue(node, newKey, 'string', '', false);
}

async function loadPromptData(node) {
    const yamlFile = node._nsFlexPresetWidgets.select_yaml?.value;
    const title = node._nsFlexPresetWidgets.input_preset_name?.value || node._nsFlexPresetWidgets.select_preset?.value;
    
    // ★追加: プリセット変更時はpanel_orderをクリア
    node._nsFlexPresetWidgets.panel_order = [];
    
    if (!yamlFile || !title) {
        clearValuePanels(node);
        updateNodeOutputs(node, true);
        return;
    }
    
    try {
        // リトライロジックを追加
        let retries = 3;
        let response;
        
        while (retries > 0) {
            response = await api.fetchApi("/ns_flexpreset/get_prompt", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    yaml: yamlFile,
                    title: title,
                    node_id: node.id
                })
            });
            
            if (response.ok) {
                break;
            }
            
            retries--;
            if (retries > 0) {
                await new Promise(resolve => setTimeout(resolve, 500));
            }
        }
        
        if (!response.ok) {
            console.error("Failed to load prompt data after retries");
        }
    } catch (error) {
        console.error("Error loading prompt data:", error);
    }
}

async function saveValue(node, keyName, keyType, keyValue, updateOutputs = true) {
    const yamlFile = node._nsFlexPresetWidgets.select_yaml?.value;
    const title = node._nsFlexPresetWidgets.input_preset_name?.value || node._nsFlexPresetWidgets.select_preset?.value;
    
    if (!yamlFile || !title) return;
    
    try {
        const response = await api.fetchApi("/ns_flexpreset/value/update", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                yaml: yamlFile,
                title: title,
                key_name: keyName,
                key_type: keyType,
                key_value: String(keyValue),
                update_outputs: updateOutputs,  // Add flag
                node_id: node.id
            })
        });
        
        const result = await response.json();
        if (!result.success) {
            console.error("Failed to save value");
        }
    } catch (error) {
        console.error("Error saving value:", error);
    }
}

async function deleteValue(node) {
    const yamlFile = node._nsFlexPresetWidgets.select_yaml?.value;
    const title = node._nsFlexPresetWidgets.input_preset_name?.value || node._nsFlexPresetWidgets.select_preset?.value;
    const keyName = node._nsFlexPresetWidgets.select_value?.value;
    
    if (!yamlFile || !title || !keyName) {
        alert("Please select a value to delete");
        return;
    }
    
    if (!confirm(`Delete value "${keyName}"?`)) {
        return;
    }
    
    try {
        const response = await api.fetchApi("/ns_flexpreset/value/delete", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                yaml: yamlFile,
                title: title,
                key_name: keyName,
                node_id: node.id
            })
        });
        
        const result = await response.json();
        if (!result.success) {
            alert("Failed to delete value");
        } else {
            // Clear selection and wait for websocket update
            node._nsFlexPresetWidgets.select_value.value = "";
            // Don't call loadPromptData, wait for websocket update
            
            // C3: Update panel order after deletion
            // Remove the deleted panel from our local list
            const panelIdx = node._nsFlexPresetWidgets.value_panels.findIndex(p => p.key === keyName);
            if (panelIdx >= 0) {
                node._nsFlexPresetWidgets.value_panels.splice(panelIdx, 1);
                sendPanelOrder(node);
            }
            
            // Force refresh node graph
            app.graph.setDirtyCanvas(true);
        }
    } catch (error) {
        console.error("Error deleting value:", error);
        alert("Error deleting value");
    }
}

// Update key name
async function updateKeyName(node, oldKey, newKey) {
    if (!newKey || newKey === oldKey) return;
    
    const yamlFile = node._nsFlexPresetWidgets.select_yaml?.value;
    const title = node._nsFlexPresetWidgets.input_preset_name?.value || node._nsFlexPresetWidgets.select_preset?.value;
    
    if (!yamlFile || !title) return;
    
    // Store the current order before update
    const currentOrder = node._nsFlexPresetWidgets.value_panels.map(p => p.key);
    
    try {
        const response = await api.fetchApi("/ns_flexpreset/value/update_key", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                yaml: yamlFile,
                title: title,
                old_key: oldKey,
                new_key: newKey,
                node_id: node.id,
                panel_order: currentOrder.map(k => k === oldKey ? newKey : k)  // Update order with new key
            })
        });
        
        const result = await response.json();
        if (result.success) {
            // Update panel key reference
            const panel = node._nsFlexPresetWidgets.value_panels.find(p => p.key === oldKey);
            if (panel) {
                panel.key = newKey;
                
                // Update separator widget
                const separatorWidget = panel.widgets.find(w => w.name === `separator_${oldKey}`);
                if (separatorWidget) {
                    separatorWidget.name = `separator_${newKey}`;
                }
                
                // Force redraw to update separator
                app.graph.setDirtyCanvas(true);
            }
        }
    } catch (error) {
        console.error("Error updating key name:", error);
    }
}

async function updateValueType(node, key, newType) {
    // Find the panel and widgets
    const panel = node._nsFlexPresetWidgets.value_panels.find(p => p.key === key);
    if (!panel) return;
    
    const valueWidget = panel.widgets.find(w => w.name === "Value" || w.name.includes("Value"));
    if (!valueWidget) return;
    
    const yamlFile = node._nsFlexPresetWidgets.select_yaml?.value;
    const title = node._nsFlexPresetWidgets.input_preset_name?.value || node._nsFlexPresetWidgets.select_preset?.value;
    
    if (!yamlFile || !title) return;
    
    // Store current value
    let currentValue = String(valueWidget.value || "");
    
    // Store the output index of the changed type
    const outputIndex = node._nsFlexPresetWidgets.value_panels.indexOf(panel);
    
    // Clean up old widget if it has textarea
    if (valueWidget.textarea) {
        const idx = node._nsFlexPresetWidgets.textareas.indexOf(valueWidget.textarea);
        if (idx >= 0) {
            node._nsFlexPresetWidgets.textareas.splice(idx, 1);
        }
        if (valueWidget.textarea.parentNode) {
            valueWidget.textarea.parentNode.removeChild(valueWidget.textarea);
        }
    }
    
    // Auto-convert value without warning
    if (!validateValueType(newType, currentValue)) {
        // Auto-convert silently
        if (newType === 'int') {
            currentValue = String(Math.round(Number(currentValue)) || 0);
        } else if (newType === 'float') {
            currentValue = String(Math.round(Number(currentValue) * 100) / 100 || 0.0);
        }
    }
    
    // Store previous type for potential revert
    valueWidget.__previousType = panel.widgets.find(w => w.name === "Type")?.value || 'string';
    
    // Remove ALL old value widgets with matching name
    const valueWidgetName = `Value`;
    for (let i = node.widgets.length - 1; i >= 0; i--) {
        if (node.widgets[i] === valueWidget) {
            node.widgets.splice(i, 1);
            break;
        }
    }
    
    // Remove old widget reference from panel
    const valueWidgetPanelIdx = panel.widgets.indexOf(valueWidget);
    if (valueWidgetPanelIdx >= 0) {
        panel.widgets.splice(valueWidgetPanelIdx, 1);
    }
    
    // Find position to insert new widget (after Type widget)
    let insertIdx = -1;
    const existingTypeWidget = panel.widgets.find(w => w.name === "Type");
    if (existingTypeWidget) {
        insertIdx = node.widgets.indexOf(existingTypeWidget) + 1;
    }
    
    // Create new widget based on type
    let newValueWidget;
    if (newType === 'int') {
        // Use number widget with integer precision
        const intValue = parseInt(currentValue) || 0;
        newValueWidget = node.addWidget(
            "number",
            valueWidgetName,
            intValue,
            (v) => { 
                // Ensure integer value
                const intVal = Math.round(v);
                newValueWidget.value = intVal;  // Update widget display
                updateValueContent(node, key, intVal); 
            },
            { 
                precision: 0,
                step: 1,
                min: -999999,
                max: 999999
            }
        );
    } else if (newType === 'float') {
        // Use number widget with float precision (2 decimal places)
        const floatValue = parseFloat(currentValue) || 0.0;
        newValueWidget = node.addWidget(
            "number",
            valueWidgetName,
            Math.round(floatValue * 100) / 100,
            (v) => { 
                // Round to 2 decimal places
                const roundedVal = Math.round(v * 100) / 100;
                updateValueContent(node, key, roundedVal); 
            },
            { 
                precision: 2,
                step: 0.01,
                min: -999999.99,
                max: 999999.99
            }
        );
    } else {
        // Use custom textarea widget for string type
        newValueWidget = node.addCustomWidget({
            name: valueWidgetName,
            draw: function(ctx, node, widget_width, y, H) {
                const margin = 15;
                const textarea_height = 60;  // Fixed height for textarea
                
                // Draw label
                ctx.fillStyle = "#999";
                ctx.font = "12px Arial";
                ctx.fillText(this.name, margin, y + 12);
                
                // Create textarea if not exists
                if (!this.textarea) {
                    this.textarea = document.createElement("textarea");
                    this.textarea.className = "comfy-multiline-input";
                    // フォーカスが当たっていないときだけ同期する
                    if (document.activeElement !== this.textarea) {
                        this.textarea.value = this.value || "";
                    }
                    this.textarea.style.position = "absolute";
                    this.textarea.style.width = (widget_width - margin * 2) + "px";
                    this.textarea.style.height = textarea_height + "px";
                    this.textarea.style.resize = "vertical";
                    this.textarea.style.fontSize = "12px";
                    this.textarea.style.fontFamily = "monospace";
                    this.textarea.style.border = "1px solid #555";
                    this.textarea.style.borderRadius = "4px";
                    this.textarea.style.backgroundColor = "#1a1a1a";
                    this.textarea.style.color = "#ddd";
                    this.textarea.style.padding = "4px";
                    this.textarea.style.zIndex = "1";
                    this.textarea.style.pointerEvents = "auto";
                    
                    // Store key reference for callback
                    const storedKey = key;
                    const self = this;
                    
                    // Add event listeners
                    this.textarea.addEventListener("input", (e) => {
                        self.value = e.target.value;
                        if (self.callback) {
                            self.callback(self.value);
                        }
                    });
                    
                    this.textarea.addEventListener("focus", (e) => {
                        app.canvas.skip_events = true;
                    });
                    
                    this.textarea.addEventListener("blur", (e) => {
                        app.canvas.skip_events = false;
                    });
                    
                    this.textarea.addEventListener("mousedown", (e) => {
                        e.stopPropagation();
                    });
                    
                    // Append to canvas container instead of body
                    const canvasParent = app.canvas.canvas.parentElement;
                    canvasParent.appendChild(this.textarea);
                    
                    // Track textarea in node
                    if (!node._nsFlexPresetWidgets.textareas) {
                        node._nsFlexPresetWidgets.textareas = [];
                    }
                    node._nsFlexPresetWidgets.textareas.push(this.textarea);
                }
                
                // Update textarea position relative to canvas
                if (this.textarea) {
                    const canvas = app.canvas.canvas;
                    const rect = canvas.getBoundingClientRect();
                    const scaleX = app.canvas.ds.scale;
                    const scaleY = app.canvas.ds.scale;
                    
                    // Calculate absolute position
                    const nodeX = (node.pos[0] + app.canvas.ds.offset[0]) * scaleX;
                    const nodeY = (node.pos[1] + app.canvas.ds.offset[1]) * scaleY;
                    
                    this.textarea.style.left = (nodeX + margin * scaleX) + "px";
                    this.textarea.style.top = (nodeY + (y + 20) * scaleY) + "px";
                    this.textarea.style.width = ((widget_width - margin * 2) * scaleX) + "px";
                    this.textarea.style.height = (textarea_height * scaleY) + "px";
                    this.textarea.style.fontSize = (12 * scaleY) + "px";
                    
                    // Hide if too small
                    this.textarea.style.display = scaleX > 0.5 ? "block" : "none";
                }
                
                return 20 + textarea_height;  // Widget height
            },
            computeSize: function(width) {
                const textarea_height = 60;   // draw と同じ値
                return [width, 20 + textarea_height];
            },
            value: currentValue,
            callback: (v) => { updateValueContent(node, key, v); },
            serialize: false
        });
        
        newValueWidget.name = valueWidgetName;
        newValueWidget.value = currentValue;
    }
    
    // Insert at correct position or push to end
    if (insertIdx > 0 && insertIdx < node.widgets.length) {
        // Remove from end and insert at correct position
        const addedWidget = node.widgets.pop();
        node.widgets.splice(insertIdx, 0, addedWidget);
    }
    
    // Update panel reference with new widget
    panel.widgets.push(newValueWidget);
    
    // Update outputs for this specific change
    updateNodeOutputsForTypeChange(node, outputIndex, newType);
    
    // Update via API - type change should update outputs
    const typeWidget = panel.widgets.find(w => w.name === "Type");
    if (typeWidget) {
        typeWidget.value = newType;
    }
    await saveValue(node, key, newType, currentValue, true);
}

async function updateValueContent(node, key, newValue) {
    // Find the type widget for this key
    const panel = node._nsFlexPresetWidgets.value_panels.find(p => p.key === key);
    if (!panel) return;
    
    const typeWidget = panel.widgets.find(w => w.name === "Type");
    if (!typeWidget) return;
    
    const yamlFile = node._nsFlexPresetWidgets.select_yaml?.value;
    const title = node._nsFlexPresetWidgets.input_preset_name?.value || node._nsFlexPresetWidgets.select_preset?.value;
    
    if (!yamlFile || !title) return;
    
    // Convert to string for validation and storage
    let valueStr = String(newValue);
    
    // For int type, ensure integer value
    if (typeWidget.value === 'int') {
        const intVal = Math.round(Number(newValue));
        valueStr = String(intVal);
    } else if (typeWidget.value === 'float') {
        // Round to 2 decimal places
        const floatVal = Math.round(Number(newValue) * 100) / 100;
        valueStr = String(floatVal);
    }
    
    // Validate value against type
    if (!validateValueType(typeWidget.value, valueStr)) {
        // For numbers, this shouldn't happen anymore due to rounding
        console.warn(`NS-FlexPreset Warning: Value '${valueStr}' does not match type '${typeWidget.value}'`);
    }
    
    // Update via API - value update should NOT update outputs
    await saveValue(node, key, typeWidget.value, valueStr, false);
}

function updateNodeOutputsForTypeChange(node, changedIndex, newType) {
    // Only update the specific output that changed
    if (changedIndex >= 0 && changedIndex < node.outputs.length) {
        const panel = node._nsFlexPresetWidgets.value_panels[changedIndex];
        if (!panel) return;
        
        const outputName = `${panel.key}_${newType}`;
        let outputType = "STRING";
        
        if (newType === "int") {
            outputType = "INT";
        } else if (newType === "float") {
            outputType = "FLOAT";
        }
        
        // Store connections from this output
        const output = node.outputs[changedIndex];
        const connections = [];
        if (output && output.links) {
            for (const linkId of output.links) {
                const link = app.graph.links[linkId];
                if (link) {
                    connections.push({
                        target_id: link.target_id,
                        target_slot: link.target_slot
                    });
                }
            }
        }
        
        // Disconnect existing connections for this output only
        if (output && output.links) {
            while (output.links.length > 0) {
                const linkId = output.links[0];
                app.graph.removeLink(linkId);
            }
        }
        
        // Update the output
        node.outputs[changedIndex] = {
            name: outputName,
            type: outputType,
            links: [],
            label: outputName
        };
        
        // Force graph update
        if (app.graph) {
            app.graph.setDirtyCanvas(true);
        }
    }
}

function updateNodeOutputs(node, forceUpdate = false) {
    // ワークフローロード中の特別な処理
    if (node._skipOutputUpdate) {
        console.log("Skipping output update due to workflow load");
        return;
    }
    
    // ワークフローロード中でも、savedConnectionsがある場合は処理を続行
    const isWorkflowLoading = isLoadingWorkflow && node._savedWorkflowConnections;

    // Don't resize if user has manually resized
    const shouldResize = !node._nsFlexPresetWidgets.user_resized;
    
    // Compute current output signature
    const outputSignature = computeOutputSignature(node);
    
    // Check if signature changed
    if (!forceUpdate && outputSignature === node._nsFlexPresetWidgets.outputs_signature) {
        return;  // No change needed
    }
    
    // Store new signature
    node._nsFlexPresetWidgets.outputs_signature = outputSignature;
    
    // Store existing connections
    const existingConnections = [];
    for (let i = 0; i < node.outputs.length; i++) {
        const output = node.outputs[i];
        if (output && output.links && output.links.length > 0) {
            const linksCopy = [...output.links];
            for (const linkId of linksCopy) {
                const link = app.graph.links[linkId];
                if (link) {
                    existingConnections.push({
                        outputIndex: i,
                        outputName: output.name,
                        outputType: output.type,
                        linkId: linkId,
                        target_id: link.target_id,
                        target_slot: link.target_slot,
                        target_slot_name: app.graph._nodes[link.target_id]?.inputs[link.target_slot]?.name
                    });
                }
            }
        }
    }
    
    // Clear existing outputs
    while (node.outputs.length > 0) {
        node.removeOutput(0);
    }
    
    // Add new outputs based on value panels
    const panels = node._nsFlexPresetWidgets.value_panels;
    
    if (panels && panels.length > 0) {
        for (const panel of panels) {
            const typeWidget = panel.widgets.find(w => w.name === "Type");
            if (typeWidget) {
                const type = typeWidget.value;
                const outputName = `${panel.key}_${type}`;
                
                if (type === "int") {
                    node.addOutput(outputName, "INT");
                } else if (type === "float") {
                    node.addOutput(outputName, "FLOAT");
                } else {
                    node.addOutput(outputName, "STRING");
                }
            }
        }
    } else {
        // パネルがない場合のみデフォルト出力を追加
        node.addOutput("output", "STRING");
    }
    
    // Restore connections where possible
    for (const conn of existingConnections) {
        // Try to find matching output by name
        let newOutputIndex = -1;
        for (let i = 0; i < node.outputs.length; i++) {
            if (node.outputs[i].name === conn.outputName) {
                newOutputIndex = i;
                break;
            }
        }
        
        // If exact match not found, try to match by index if same type
        if (newOutputIndex === -1 && conn.outputIndex < node.outputs.length) {
            const oldType = conn.outputName.split('_').pop();
            const newOutput = node.outputs[conn.outputIndex];
            const newType = newOutput.name.split('_').pop();
            
            if (oldType === newType) {
                newOutputIndex = conn.outputIndex;
            }
        }
        
        // Restore connection if found
        if (newOutputIndex >= 0) {
            try {
                node.connect(newOutputIndex, conn.target_id, conn.target_slot);
            } catch (e) {
                console.warn("Failed to restore connection:", e);
            }
        }
    }
    
    // Only auto-resize if user hasn't manually resized
    if (shouldResize) {
        node.setSize(node.computeSize());
    }
    
    // Force graph connection refresh
    if (app.graph) {
        app.graph.setDirtyCanvas(true);
        if (app.graph.connectionChange) {
            app.graph.connectionChange(null);
        }
        if (node.onConnectionsChange) {
            node.onConnectionsChange();
        }
    }
}

function computeOutputSignature(node) {
    // A5: Compute hash of current outputs - no sorting
    const panels = node._nsFlexPresetWidgets.value_panels;
    
    const parts = [];
    for (const panel of panels) {
        const typeWidget = panel.widgets.find(w => w.name === "Type");
        if (typeWidget) {
            parts.push(`${panel.key}:${typeWidget.value}`);
        }
    }
    
    return parts.join(",");
}