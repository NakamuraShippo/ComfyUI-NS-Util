import { app } from "../../../scripts/app.js";
import { api } from "../../../scripts/api.js";

// Store for YAML/title data
const promptListStore = {
    yamlFiles: [],
    titlesByYaml: {},
};

// Helper to find widget by name
function findWidget(node, name) {
    return node.widgets?.find(w => w.name === name);
}

function hasPromptListWidgetSignature(node) {
    const widgetNames = new Set(node?.widgets?.map(widget => widget?.name) || []);
    return widgetNames.has("select_yaml")
        && widgetNames.has("select")
        && widgetNames.has("title")
        && widgetNames.has("prompt");
}

function isPromptListNode(node) {
    return node?.comfyClass === "NS-PromptList"
        || node?.type === "NS-PromptList"
        || hasPromptListWidgetSignature(node);
}

const ACTION_ROW_HEIGHT = 32;
const ACTION_BAR_MARGIN = 16;
const ACTION_BAR_GAP = 8;
const ACTION_ADD_BUTTON_MIN_WIDTH = 44;
const ACTION_DELETE_BUTTON_MIN_WIDTH = 58;
const ACTION_NEWYAML_BUTTON_MIN_WIDTH = 72;
const PROMPTLIST_DEFAULT_WIDTH = 320;
const PROMPTLIST_DEFAULT_HEIGHT = 300;

function normalizePromptListNodeSize(size, fallbackSize = null) {
    const fallback = Array.isArray(fallbackSize) && fallbackSize.length >= 2
        ? fallbackSize
        : [PROMPTLIST_DEFAULT_WIDTH, PROMPTLIST_DEFAULT_HEIGHT];
    const width = Number(size?.[0]);
    const height = Number(size?.[1]);
    return [
        Number.isFinite(width) && width > 0 ? width : fallback[0],
        Number.isFinite(height) && height > 0 ? height : fallback[1],
    ];
}

function getPromptListNodeSize(node) {
    return normalizePromptListNodeSize(Array.isArray(node?.size) ? node.size : null);
}

function getPromptListPreferredSize(node) {
    return normalizePromptListNodeSize(
        node?._nsPromptListPreferredSize,
        getPromptListNodeSize(node),
    );
}

function storePromptListPreferredSize(node, size) {
    if (!node) {
        return normalizePromptListNodeSize(size);
    }

    const normalizedSize = normalizePromptListNodeSize(size, getPromptListPreferredSize(node));
    node._nsPromptListPreferredSize = [...normalizedSize];
    node._nsPromptListLockedSize = [...normalizedSize];
    return normalizedSize;
}

function applyPromptListNodeSize(node, size, persist = false) {
    if (!node) return;

    const target = normalizePromptListNodeSize(size, getPromptListPreferredSize(node));

    node._nsPromptListApplyingSize = true;
    try {
        if (Array.isArray(node.size)) {
            node.size[0] = target[0];
            node.size[1] = target[1];
        } else {
            node.size = [...target];
        }
    } finally {
        node._nsPromptListApplyingSize = false;
    }

    if (persist) {
        storePromptListPreferredSize(node, target);
    }

    app.graph.setDirtyCanvas(true, true);
}

function restorePromptListNodeSize(node, lockedSize = null) {
    if (!node) return;

    applyPromptListNodeSize(node, lockedSize || node._nsPromptListLockedSize || getPromptListPreferredSize(node));
}

function lockPromptListNodeSize(node) {
    if (!node) return;

    node._nsPromptListLockedSize = getPromptListPreferredSize(node);
    return [...node._nsPromptListLockedSize];
}

function schedulePromptListNodeSizeRestore(node, lockedSize = null) {
    if (!node) return;
    const targetSize = Array.isArray(lockedSize) ? [...lockedSize] : lockPromptListNodeSize(node);

    const restore = () => {
        restorePromptListNodeSize(node, targetSize);
        app.graph.setDirtyCanvas(true, true);
    };

    if (node._nsPromptListRestoreTimer) {
        clearTimeout(node._nsPromptListRestoreTimer);
    }
    if (node._nsPromptListLateRestoreTimer) {
        clearTimeout(node._nsPromptListLateRestoreTimer);
    }
    if (node._nsPromptListRestoreFrame && typeof cancelAnimationFrame === "function") {
        cancelAnimationFrame(node._nsPromptListRestoreFrame);
        node._nsPromptListRestoreFrame = null;
    }

    restore();
    node._nsPromptListRestoreTimer = setTimeout(() => {
        node._nsPromptListRestoreTimer = null;
        restore();
    }, 0);

    node._nsPromptListLateRestoreTimer = setTimeout(() => {
        node._nsPromptListLateRestoreTimer = null;
        restore();
    }, 32);

    if (typeof requestAnimationFrame === "function") {
        node._nsPromptListRestoreFrame = requestAnimationFrame(() => {
            node._nsPromptListRestoreFrame = null;
            restore();
        });
    }
}

// Helper to refresh node display
function refreshNode(node) {
    if (!node) return;

    app.graph.setDirtyCanvas(true, true);
}

function cleanupActionBar(node) {
    const actionBar = node?._nsPromptListActionBar;
    if (actionBar?.parentElement) {
        actionBar.remove();
    }
    if (node) {
        node._nsPromptListActionBar = null;
    }
}

function createActionButton(label, kind, minWidth, onClick) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = label;
    button.dataset.baseWidth = String(minWidth);
    button.style.minWidth = `${minWidth}px`;
    button.style.width = "auto";
    button.style.height = "22px";
    button.style.padding = "0 10px";
    button.style.borderRadius = "6px";
    button.style.border = kind === "add" ? "1px solid #4f9b73" : "1px solid #a66767";
    button.style.background = kind === "add" ? "#2f6f4f" : "#6a4040";
    button.style.color = "#f5f5f5";
    button.style.fontSize = "12px";
    button.style.fontWeight = "600";
    button.style.lineHeight = "20px";
    button.style.whiteSpace = "nowrap";
    button.style.cursor = "pointer";
    button.style.boxSizing = "border-box";
    button.style.pointerEvents = "auto";

    button.addEventListener("pointerdown", (event) => {
        event.stopPropagation();
    });

    button.addEventListener("mousedown", (event) => {
        event.stopPropagation();
    });

    button.addEventListener("click", (event) => {
        event.preventDefault();
        event.stopPropagation();
        onClick();
    });

    return button;
}

function positionActionBar(actionBar, node, y) {
    if (!actionBar || !app.canvas?.canvas || !app.canvas?.ds) return;

    const scale = app.canvas.ds.scale || 1;
    const offset = app.canvas.ds.offset || [0, 0];
    const nodeX = (node.pos[0] + offset[0]) * scale;
    const nodeY = (node.pos[1] + offset[1]) * scale;

    actionBar.style.left = `${nodeX + ACTION_BAR_MARGIN * scale}px`;
    actionBar.style.top = `${nodeY + (y + 4) * scale}px`;
    actionBar.style.gap = `${Math.max(4, ACTION_BAR_GAP * scale)}px`;
    actionBar.style.display = !node.flags?.collapsed && scale > 0.45 ? "flex" : "none";

    const buttons = actionBar.querySelectorAll("button");
    buttons.forEach((button) => {
        const baseWidth = Number(button.dataset.baseWidth || 44);
        button.style.minWidth = `${Math.max(36, baseWidth * scale)}px`;
        button.style.height = `${Math.max(18, 22 * scale)}px`;
        button.style.padding = `0 ${Math.max(6, 10 * scale)}px`;
        button.style.fontSize = `${Math.max(10, 12 * scale)}px`;
        button.style.borderRadius = `${Math.max(4, 6 * scale)}px`;
        button.style.lineHeight = `${Math.max(16, 20 * scale)}px`;
    });
}

function createActionWidget() {
    return {
        name: "prompt_actions",
        serialize: false,
        draw(ctx, nodeRef, widgetWidth, y) {
            if (!this.actionBar) {
                const canvasParent = app.canvas?.canvas?.parentElement;
                if (!canvasParent) return ACTION_ROW_HEIGHT;

                const actionBar = document.createElement("div");
                actionBar.className = "ns-promptlist-actions";
                actionBar.style.position = "absolute";
                actionBar.style.display = "flex";
                actionBar.style.alignItems = "center";
                actionBar.style.zIndex = "5";
                actionBar.style.pointerEvents = "auto";

                const addButton = createActionButton("Add", "add", ACTION_ADD_BUTTON_MIN_WIDTH, () => {
                    void handleAddAction(nodeRef);
                });
                const deleteButton = createActionButton("Delete", "delete", ACTION_DELETE_BUTTON_MIN_WIDTH, () => {
                    void handleDeleteAction(nodeRef);
                });
                const newYamlButton = createActionButton("New YAML", "add", ACTION_NEWYAML_BUTTON_MIN_WIDTH, () => {
                    void handleNewYamlAction(nodeRef);
                });

                actionBar.append(addButton, deleteButton, newYamlButton);
                canvasParent.appendChild(actionBar);

                this.actionBar = actionBar;
                nodeRef._nsPromptListActionBar = actionBar;
            }

            positionActionBar(this.actionBar, nodeRef, y);
            return ACTION_ROW_HEIGHT;
        },
        computeSize() {
            return [0, ACTION_ROW_HEIGHT];
        },
    };
}

async function handleAddAction(node) {
    const yamlWidget = findWidget(node, "select_yaml");
    const titleWidget = findWidget(node, "title");
    const promptWidget = findWidget(node, "prompt");
    const titleToAdd = titleWidget?.value?.trim() || "";
    const promptToAdd = promptWidget?.value || "";

    if (!yamlWidget?.value || !titleToAdd) return;

    const result = await addTitle(yamlWidget.value, titleToAdd, promptToAdd, node.id);
    if (!result.success) return;

    await reloadYamlList();
    applyPromptState(node, yamlWidget.value, result);
}

async function handleDeleteAction(node) {
    const yamlWidget = findWidget(node, "select_yaml");
    const selectWidget = findWidget(node, "select");
    const titleWidget = findWidget(node, "title");
    const titleToDelete = selectWidget?.value || titleWidget?.value;

    if (!yamlWidget?.value || !titleToDelete) return;

    if (!confirm(`Delete title "${titleToDelete}" from ${yamlWidget.value}?`)) {
        return;
    }

    const result = await deleteTitle(yamlWidget.value, titleToDelete, node.id);
    if (!result.success) return;

    await reloadYamlList();
    applyPromptState(node, yamlWidget.value, result);
}

async function handleNewYamlAction(node) {
    const name = prompt("Enter YAML file name (without .yaml extension):");
    if (!name || !name.trim()) return;

    const sanitized = name.trim().replace(/[^a-zA-Z0-9_\-]/g, "_");
    const fileName = sanitized.endsWith(".yaml") ? sanitized : sanitized + ".yaml";

    try {
        const response = await api.fetchApi("/ns_promptlist/create_yaml", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                yaml: fileName,
                node_id: node.id
            })
        });
        const result = await response.json();
        if (result.success) {
            applyEnumData(result);
            const yamlWidget = findWidget(node, "select_yaml");
            if (yamlWidget) {
                yamlWidget.options.values = promptListStore.yamlFiles;
                yamlWidget.value = fileName;
                if (yamlWidget.callback) {
                    yamlWidget.callback(fileName);
                }
            }
            refreshNode(node);
        } else {
            alert(result.error || "Failed to create YAML file");
        }
    } catch (error) {
        console.error("Error creating YAML:", error);
        alert("Error creating YAML file");
    }
}

function updatePromptListStore(yamlFile, titles) {
    if (!yamlFile) return;

    const normalizedTitles = Array.isArray(titles)
        ? titles.filter(title => typeof title === "string" && title !== "")
        : [];
    promptListStore.titlesByYaml[yamlFile] = normalizedTitles;

    if (!promptListStore.yamlFiles.includes(yamlFile)) {
        promptListStore.yamlFiles = [...promptListStore.yamlFiles, yamlFile].sort();
    }
}

function applyEnumData(data) {
    if (!data) return;

    if (Array.isArray(data.yaml_files)) {
        promptListStore.yamlFiles = data.yaml_files;
    }

    if (data.titles_by_yaml && typeof data.titles_by_yaml === "object") {
        const normalized = {};
        for (const [yamlFile, titles] of Object.entries(data.titles_by_yaml)) {
            normalized[yamlFile] = Array.isArray(titles)
                ? titles.filter(title => typeof title === "string" && title !== "")
                : [];
        }
        promptListStore.titlesByYaml = normalized;
    }
}

function findPromptListNodeById(nodeId) {
    return app.graph._nodes.find(node => String(node.id) === String(nodeId));
}

function createPromptRequestId(node) {
    if (!node) return null;

    const nextSeq = Number(node._nsPromptListRequestSeq || 0) + 1;
    node._nsPromptListRequestSeq = nextSeq;
    return `${node.id}:${nextSeq}`;
}

function applyPromptState(node, yamlFile, state) {
    if (!node || !state) return;
    const lockedSize = lockPromptListNodeSize(node);

    updatePromptListStore(yamlFile, state.titles);

    const yamlWidget = findWidget(node, "select_yaml");
    const selectWidget = findWidget(node, "select");
    const titleWidget = findWidget(node, "title");
    const promptWidget = findWidget(node, "prompt");
    const titles = promptListStore.titlesByYaml[yamlFile] || [];
    const activeTitle = state.title || "";

    if (yamlWidget && yamlFile) {
        yamlWidget.options.values = promptListStore.yamlFiles;
        yamlWidget.value = yamlFile;
    }

    if (selectWidget) {
        selectWidget.options.values = titles.length > 0 ? titles : [""];
        selectWidget.value = activeTitle;
    }

    if (titleWidget) {
        titleWidget.value = activeTitle;
    }

    if (promptWidget) {
        promptWidget.value = state.prompt || "";
    }

    refreshNode(node);
    schedulePromptListNodeSizeRestore(node, lockedSize);
}

// Setup socket listeners
function setupSocketListeners() {
    // Listen for enum updates
    api.addEventListener("ns_promptlist_enum", (event) => {
        const data = event.detail;
        applyEnumData(data);
        
        // Update all NS-PromptList nodes
        app.graph._nodes.forEach(node => {
            if (node._nsPromptListNode || isPromptListNode(node)) {
                updateNodeEnums(node);
            }
        });
    });
    
    // Listen for widget updates
    api.addEventListener("ns_promptlist_set_widgets", (event) => {
        const data = event.detail;
        const targetNodeId = data.node_id;
        
        // Only update the specific node if node_id is provided
        if (targetNodeId) {
            const targetNode = findPromptListNodeById(targetNodeId);
            if (targetNode && (targetNode._nsPromptListNode || isPromptListNode(targetNode))) {
                const lockedSize = lockPromptListNodeSize(targetNode);
                const yamlWidget = findWidget(targetNode, "select_yaml");
                const titleWidget = findWidget(targetNode, "title");
                const selectWidget = findWidget(targetNode, "select");
                const promptWidget = findWidget(targetNode, "prompt");

                if (data.request_id && targetNode._nsPromptListLatestRequestId
                    && data.request_id !== targetNode._nsPromptListLatestRequestId) {
                    return;
                }

                if (yamlWidget && data.yaml_file && yamlWidget.value !== data.yaml_file) {
                    return;
                }
                
                if (titleWidget) titleWidget.value = data.title || "";
                if (selectWidget) selectWidget.value = data.title || "";
                if (promptWidget) promptWidget.value = data.prompt || "";
                
                refreshNode(targetNode);
                schedulePromptListNodeSizeRestore(targetNode, lockedSize);
            }
        } else {
            // Fallback: update active node only
            const activeNode = app.canvas.node_over || app.canvas.selected_nodes?.[0];
            
            if (activeNode && (activeNode._nsPromptListNode || isPromptListNode(activeNode))) {
                const lockedSize = lockPromptListNodeSize(activeNode);
                const titleWidget = findWidget(activeNode, "title");
                const promptWidget = findWidget(activeNode, "prompt");
                
                if (titleWidget) titleWidget.value = data.title || "";
                if (promptWidget) promptWidget.value = data.prompt || "";
                
                refreshNode(activeNode);
                schedulePromptListNodeSizeRestore(activeNode, lockedSize);
            }
        }
    });
}

// Force reload YAML list
async function reloadYamlList() {
    try {
        // This will trigger the backend to refresh and broadcast new enum data
        const response = await api.fetchApi("/ns_promptlist/reload_yamls", {
            method: "POST",
            headers: { "Content-Type": "application/json" }
        });
        const data = await response.json();
        if (data?.success) {
            applyEnumData(data);
        }
        return data;
    } catch (error) {
        console.error("Error reloading YAML list:", error);
        return null;
    }
}

// Update node combo box options
function updateNodeEnums(node) {
    const lockedSize = lockPromptListNodeSize(node);
    const yamlWidget = findWidget(node, "select_yaml");
    const selectWidget = findWidget(node, "select");
    const titleWidget = findWidget(node, "title");
    const promptWidget = findWidget(node, "prompt");

    if (!yamlWidget || promptListStore.yamlFiles.length === 0) {
        refreshNode(node);
        schedulePromptListNodeSizeRestore(node, lockedSize);
        return;
    }
    
    // Update YAML options
    const currentYaml = yamlWidget.value;
    yamlWidget.options.values = promptListStore.yamlFiles;
    
    // Keep current selection if it still exists
    if (promptListStore.yamlFiles.includes(currentYaml)) {
        yamlWidget.value = currentYaml;
    } else {
        yamlWidget.value = promptListStore.yamlFiles[0];
    }
    
    if (selectWidget) {
        // Update title options based on current YAML
        if (!Object.prototype.hasOwnProperty.call(promptListStore.titlesByYaml, yamlWidget.value)) {
            refreshNode(node);
            schedulePromptListNodeSizeRestore(node, lockedSize);
            return;
        }

        const currentTitle = selectWidget.value;
        const titles = promptListStore.titlesByYaml[yamlWidget.value] || [];
        selectWidget.options.values = titles.length > 0 ? titles : [""];
        
        // Keep current selection if it still exists
        if (titles.includes(currentTitle)) {
            selectWidget.value = currentTitle;
        } else if (titles[0] && titles[0] !== "") {
            selectWidget.value = titles[0];
            // Fetch prompt for the new selection
            requestPromptData(yamlWidget.value, titles[0], node.id, createPromptRequestId(node));
        } else {
            selectWidget.value = "";
            if (titleWidget) titleWidget.value = "";
            if (promptWidget) promptWidget.value = "";
        }
    }
    
    refreshNode(node);
    schedulePromptListNodeSizeRestore(node, lockedSize);
}

// Hook select widget change handler
function hookSelectChange(node) {
    if (!isPromptListNode(node)) return;
    
    const yamlWidget = findWidget(node, "select_yaml");
    const selectWidget = findWidget(node, "select");
    
    // Hook YAML selection change
    if (yamlWidget) {
        yamlWidget.callback = async function(value) {
            const lockedSize = lockPromptListNodeSize(node);
            let titles = promptListStore.titlesByYaml[value];

            if (!Array.isArray(titles)) {
                await reloadYamlList();
                titles = promptListStore.titlesByYaml[value];
            }
            
            // Update title options for this specific node
            if (selectWidget) {
                const resolvedTitles = Array.isArray(titles) ? titles : [];
                selectWidget.options.values = resolvedTitles.length > 0 ? resolvedTitles : [""];
                // Auto-select first title if available
                selectWidget.value = resolvedTitles[0] || "";
                
                // If we have a title, fetch its prompt
                if (resolvedTitles[0]) {
                    await requestPromptData(value, resolvedTitles[0], node.id, createPromptRequestId(node));
                } else {
                    const titleWidget = findWidget(node, "title");
                    const promptWidget = findWidget(node, "prompt");
                    if (titleWidget) titleWidget.value = "";
                    if (promptWidget) promptWidget.value = "";
                }
            }
            
            refreshNode(node);
            schedulePromptListNodeSizeRestore(node, lockedSize);
        };
    }
    
    // Hook title selection change
    if (selectWidget) {
        selectWidget.callback = async function(value) {
            const lockedSize = lockPromptListNodeSize(node);
            
            // Fetch prompt data for this specific node
            if (value) {
                await requestPromptData(
                    yamlWidget?.value || "",
                    value,
                    node.id,
                    createPromptRequestId(node),
                );
            } else {
                const titleWidget = findWidget(node, "title");
                const promptWidget = findWidget(node, "prompt");
                if (titleWidget) titleWidget.value = "";
                if (promptWidget) promptWidget.value = "";
                refreshNode(node);
                schedulePromptListNodeSizeRestore(node, lockedSize);
            }

            schedulePromptListNodeSizeRestore(node, lockedSize);
        };
    }

    // Hook prompt widget change for auto-save (debounced)
    const promptWidget = findWidget(node, "prompt");
    if (promptWidget) {
        promptWidget.callback = function() {
            const title = selectWidget?.value || findWidget(node, "title")?.value;
            if (!yamlWidget?.value || !title) return;

            if (node._nsPromptListSaveTimer) {
                clearTimeout(node._nsPromptListSaveTimer);
            }
            node._nsPromptListSaveTimer = setTimeout(() => {
                node._nsPromptListSaveTimer = null;
                void addTitle(yamlWidget.value, title, promptWidget.value, node.id);
            }, 500);
        };
    }
}

// Request prompt data from backend
async function requestPromptData(yamlFile, title, nodeId = null, requestId = null) {
    if (!yamlFile || !title) return;
    
    try {
        const payload = {
            yaml: yamlFile,
            title: title,
            node_id: nodeId,
        };

        if (requestId) {
            payload.request_id = requestId;

            const targetNode = findPromptListNodeById(nodeId);
            if (targetNode) {
                targetNode._nsPromptListLatestRequestId = requestId;
            }
        }

        await api.fetchApi("/ns_promptlist/get_prompt", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        });
    } catch (error) {
        console.error("Error fetching prompt data:", error);
    }
}

// Add or update title
async function addTitle(yamlFile, title, prompt, nodeId = null) {
    if (!yamlFile || !title) return { success: false };

    try {
        const response = await api.fetchApi("/ns_promptlist/add_title", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                yaml: yamlFile,
                title: title,
                prompt: prompt,
                node_id: nodeId
            })
        });
        const result = await response.json();

        if (result.success) {
            updatePromptListStore(yamlFile, result.titles);
        }

        return result;
    } catch (error) {
        console.error("Error adding title:", error);
        return { success: false };
    }
}

// Delete title
async function deleteTitle(yamlFile, title, nodeId = null) {
    if (!yamlFile || !title) return { success: false };

    try {
        const response = await api.fetchApi("/ns_promptlist/delete_title", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                yaml: yamlFile,
                title: title,
                node_id: nodeId
            })
        });
        const result = await response.json();

        if (result.success) {
            updatePromptListStore(yamlFile, result.titles);
        }

        return result;
    } catch (error) {
        console.error("Error deleting title:", error);
        return { success: false };
    }
}

function setupPromptListNode(node) {
    if (!isPromptListNode(node) || node._nsPromptListInitialized) return;

    node._nsPromptListInitialized = true;
    node._nsPromptListNode = true;

    // Track the user-chosen size separately so widget refreshes cannot adopt a temporary auto-size.
    const currentSize = getPromptListNodeSize(node);
    storePromptListPreferredSize(node, currentSize);
    applyPromptListNodeSize(node, currentSize);

    if (!node._nsPromptListResizeHookInstalled) {
        const originalOnResize = node.onResize;
        node.onResize = function(size) {
            const result = originalOnResize
                ? originalOnResize.apply(this, arguments)
                : undefined;

            if (!this._nsPromptListApplyingSize) {
                storePromptListPreferredSize(this, Array.isArray(this.size) ? this.size : size);
            }

            return result;
        };
        node._nsPromptListResizeHookInstalled = true;
    }

    node.addCustomWidget(createActionWidget());

    if (!node._nsPromptListRemovalHookInstalled) {
        const originalOnRemoved = node.onRemoved;

        node.onRemoved = function() {
            if (this._nsPromptListRestoreTimer) {
                clearTimeout(this._nsPromptListRestoreTimer);
                this._nsPromptListRestoreTimer = null;
            }
            if (this._nsPromptListLateRestoreTimer) {
                clearTimeout(this._nsPromptListLateRestoreTimer);
                this._nsPromptListLateRestoreTimer = null;
            }
            if (this._nsPromptListRestoreFrame && typeof cancelAnimationFrame === "function") {
                cancelAnimationFrame(this._nsPromptListRestoreFrame);
                this._nsPromptListRestoreFrame = null;
            }
            cleanupActionBar(this);
            if (originalOnRemoved) {
                originalOnRemoved.apply(this, arguments);
            }
        };
        node._nsPromptListRemovalHookInstalled = true;
    }

    hookSelectChange(node);
    updateNodeEnums(node);

    // Initialize with first title after a short delay
    setTimeout(() => {
        const yamlWidget = findWidget(node, "select_yaml");
        const selectWidget = findWidget(node, "select");

        if (yamlWidget && selectWidget) {
            const currentYaml = yamlWidget.value;
            const titles = promptListStore.titlesByYaml[currentYaml];

            if (titles && titles.length > 0 && titles[0] !== "") {
                selectWidget.value = titles[0];
                requestPromptData(currentYaml, titles[0], node.id, createPromptRequestId(node));
            }
        }
    }, 100);
}

// Extension registration
app.registerExtension({
    name: "NS.PromptList",
    
    async setup() {
        // Setup socket listeners
        setupSocketListeners();
        
        // Request initial YAML list on setup
        setTimeout(async () => {
            await reloadYamlList();
        }, 500);
        
        // Hook into node addition
        const origNodeAdded = app.graph.onNodeAdded;
        app.graph.onNodeAdded = function(node) {
            if (origNodeAdded) {
                origNodeAdded.call(this, node);
            }
            
            // Hook our node type
            if (isPromptListNode(node)) {
                setTimeout(() => {
                    setupPromptListNode(node);
                    // Request fresh data when node is added
                    reloadYamlList();
                }, 0);
            }
        };
    },
    
    async nodeCreated(node) {
        setupPromptListNode(node);
    },

    async loadedGraphNode(node) {
        setupPromptListNode(node);
    },

    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== "NS-PromptList") return;

        const originalOnNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function() {
            const result = originalOnNodeCreated
                ? originalOnNodeCreated.apply(this, arguments)
                : undefined;
            setupPromptListNode(this);
            return result;
        };
    }
});
