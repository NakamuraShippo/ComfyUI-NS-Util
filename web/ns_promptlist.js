import { app } from "../../scripts/app.js";
import { ComfyWidgets } from "../../scripts/widgets.js";
import { api } from "../../scripts/api.js";

// Store for YAML/title data
const promptListStore = {
    yamlFiles: [],
    titlesByYaml: {},
};

// Helper to find widget by name
function findWidget(node, name) {
    return node.widgets?.find(w => w.name === name);
}

// Helper to refresh node display
function refreshNode(node) {
    const currentSize = [...node.size];
    
    if (ComfyWidgets?.refreshNode) {
        ComfyWidgets.refreshNode(node);
    } else {
        const size = node.computeSize();
        node.setSize(size);
        app.graph.setDirtyCanvas(true, true);
    }
    
    if (node.size[0] < currentSize[0] || node.size[1] < currentSize[1]) {
        node.size[0] = Math.max(node.size[0], currentSize[0]);
        node.size[1] = Math.max(node.size[1], currentSize[1]);
    }
}

// Setup socket listeners
function setupSocketListeners() {
    // Listen for enum updates
    api.addEventListener("ns_promptlist_enum", (event) => {
        const data = event.detail;
        promptListStore.yamlFiles = data.yaml_files || [];
        promptListStore.titlesByYaml = data.titles_by_yaml || {};
        
        // Update all NS-PromptList nodes
        app.graph._nodes.forEach(node => {
            if (node.type === "NS-PromptList") {
                updateNodeEnums(node);
            }
        });
    });
    
    // Listen for widget updates
    api.addEventListener("ns_promptlist_set_widgets", (event) => {
        const data = event.detail;
        const targetNodeId = data.node_id;
        
        if (targetNodeId) {
            const targetNode = app.graph._nodes.find(n => n.id === targetNodeId);
            if (targetNode && targetNode.type === "NS-PromptList") {
                const titleWidget = findWidget(targetNode, "title");
                const promptWidget = findWidget(targetNode, "prompt");
                
                if (titleWidget) titleWidget.value = data.title || "";
                if (promptWidget) promptWidget.value = data.prompt || "";
                
                refreshNode(targetNode);
            }
        } else {
            const activeNode = app.canvas.node_over || app.canvas.selected_nodes?.[0];
            
            if (activeNode && activeNode.type === "NS-PromptList") {
                const titleWidget = findWidget(activeNode, "title");
                const promptWidget = findWidget(activeNode, "prompt");
                
                if (titleWidget) titleWidget.value = data.title || "";
                if (promptWidget) promptWidget.value = data.prompt || "";
                
                refreshNode(activeNode);
            }
        }
    });
}

// Force reload YAML list
async function reloadYamlList() {
    try {
        await api.fetchApi("/ns_promptlist/reload_yamls", {
            method: "POST",
            headers: { "Content-Type": "application/json" }
        });
    } catch (error) {
        console.error("Error reloading YAML list:", error);
    }
}

// Update node combo box options
function updateNodeEnums(node) {
    const yamlWidget = findWidget(node, "select_yaml");
    const selectWidget = findWidget(node, "select");
    
    if (yamlWidget && promptListStore.yamlFiles.length > 0) {
        const currentYaml = yamlWidget.value;
        yamlWidget.options.values = promptListStore.yamlFiles;
        
        if (promptListStore.yamlFiles.includes(currentYaml)) {
            yamlWidget.value = currentYaml;
        } else {
            yamlWidget.value = promptListStore.yamlFiles[0];
        }
    }
    
    if (selectWidget && yamlWidget) {
        const currentTitle = selectWidget.value;
        const titles = promptListStore.titlesByYaml[yamlWidget.value] || [""];
        selectWidget.options.values = titles;
        
        if (titles.includes(currentTitle)) {
            selectWidget.value = currentTitle;
        } else if (titles[0] && titles[0] !== "") {
            selectWidget.value = titles[0];
            requestPromptData(yamlWidget.value, titles[0], node.id);
        } else {
            selectWidget.value = "";
        }
    }
    
    refreshNode(node);
}

// Hook select widget change handler
function hookSelectChange(node) {
    if (node.type !== "NS-PromptList") return;
    
    const yamlWidget = findWidget(node, "select_yaml");
    const selectWidget = findWidget(node, "select");
    
    const originalYamlCallback = yamlWidget?.callback;
    const originalSelectCallback = selectWidget?.callback;
    
    if (yamlWidget) {
        yamlWidget.callback = function(value) {
            if (originalYamlCallback) {
                originalYamlCallback.call(this, value);
            }
            
            const titles = promptListStore.titlesByYaml[value] || [""];
            if (selectWidget) {
                selectWidget.options.values = titles;
                selectWidget.value = titles[0] || "";
                
                if (titles[0]) {
                    requestPromptData(value, titles[0], node.id);
                }
            }
            
            refreshNode(node);
        };
    }
    
    if (selectWidget) {
        selectWidget.callback = function(value) {
            if (originalSelectCallback) {
                originalSelectCallback.call(this, value);
            }
            
            if (value) {
                requestPromptData(yamlWidget?.value || "", value, node.id);
            }
        };
    }
}

// Request prompt data from backend
async function requestPromptData(yamlFile, title, nodeId = null) {
    if (!yamlFile || !title) return;
    
    try {
        await api.fetchApi("/ns_promptlist/get_prompt", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ 
                yaml: yamlFile, 
                title: title,
                node_id: nodeId 
            })
        });
    } catch (error) {
        console.error("Error fetching prompt data:", error);
    }
}

// Delete title
async function deleteTitle(yamlFile, title) {
    try {
        const response = await api.fetchApi("/ns_promptlist/delete_title", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ 
                yaml: yamlFile, 
                title: title
            })
        });
        const result = await response.json();
        if (result.success) {
            await reloadYamlList();
        }
        return result.success;
    } catch (error) {
        console.error("Error deleting title:", error);
        return false;
    }
}

// Extension registration
app.registerExtension({
    name: "NS.PromptList",
    
    async setup() {
        setupSocketListeners();
        
        setTimeout(async () => {
            await reloadYamlList();
        }, 500);
        
        const origNodeAdded = app.graph.onNodeAdded;
        app.graph.onNodeAdded = function(node) {
            if (origNodeAdded) {
                origNodeAdded.call(this, node);
            }
            
            if (node.type === "NS-PromptList") {
                setTimeout(() => {
                    hookSelectChange(node);
                    updateNodeEnums(node);
                    reloadYamlList();
                }, 0);
            }
        };
    },
    
    async nodeCreated(node) {
        if (node.type === "NS-PromptList") {
            node.size = [400, 300];
            node.computeSize = function() {
                const size = LGraphNode.prototype.computeSize.apply(this, arguments);
                size[0] = Math.max(size[0], 400);
                size[1] = Math.max(size[1], 300);
                return size;
            };
            
            // Add delete button
            const deleteButton = node.addWidget("button", "Delete Title", "", async () => {
                const yamlWidget = findWidget(node, "select_yaml");
                const titleWidget = findWidget(node, "title");
                
                if (yamlWidget?.value && titleWidget?.value) {
                    if (confirm(`Delete title "${titleWidget.value}" from ${yamlWidget.value}?`)) {
                        const success = await deleteTitle(yamlWidget.value, titleWidget.value);
                        if (success) {
                            titleWidget.value = "";
                            const promptWidget = findWidget(node, "prompt");
                            if (promptWidget) promptWidget.value = "";
                            refreshNode(node);
                        }
                    }
                }
            });
            
            setTimeout(() => {
                const yamlWidget = findWidget(node, "select_yaml");
                const selectWidget = findWidget(node, "select");
                
                if (yamlWidget && selectWidget) {
                    const currentYaml = yamlWidget.value;
                    const titles = promptListStore.titlesByYaml[currentYaml];
                    
                    if (titles && titles.length > 0 && titles[0] !== "") {
                        selectWidget.value = titles[0];
                        requestPromptData(currentYaml, titles[0], node.id);
                    }
                }
            }, 100);
        }
    }
});