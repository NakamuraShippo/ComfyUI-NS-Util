import os
import re
import yaml
import json
import asyncio
import shutil
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Any, Union
from collections import OrderedDict
import tempfile
import atexit

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileSystemEvent

from server import PromptServer
from aiohttp import web  # B1: Import for proper Response objects

class OrderedLoader(yaml.SafeLoader):
    pass

def construct_mapping(loader, node):
    loader.flatten_mapping(node)
    return OrderedDict(loader.construct_pairs(node))

OrderedLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    construct_mapping)

class OrderedDumper(yaml.SafeDumper):
    pass

def dict_representer(dumper, data):
    return dumper.represent_dict(data.items())

OrderedDumper.add_representer(OrderedDict, dict_representer)
OrderedDumper.add_representer(dict, dict_representer)

class YAMLFileHandler(FileSystemEventHandler):
    """Handles file system events for YAML files"""
    def __init__(self, node_instance):
        self.node_instance = node_instance
        
    def on_modified(self, event: FileSystemEvent):
        if not event.is_directory and event.src_path.endswith('.yaml'):
            self.node_instance.refresh_enums()
    
    def on_created(self, event: FileSystemEvent):
        if not event.is_directory and event.src_path.endswith('.yaml'):
            self.node_instance.refresh_enums()
    
    def on_deleted(self, event: FileSystemEvent):
        if not event.is_directory and event.src_path.endswith('.yaml'):
            self.node_instance.refresh_enums()


class NS_FlexPreset:
    """NS-FlexPreset Node for ComfyUI"""
    
    # Type validation regexes
    TYPE_REGEX = {
        'int': r'^-?[0-9]+$',
        'float': r'^-?[0-9]*\.?[0-9]+$',
        'string': r'.*'  # Any scalar value
    }
    
    def __init__(self):
        # Handle migration from yaml to presets
        self.presets_dir = Path(__file__).parent / "presets"
        old_yaml_dir = Path(__file__).parent / "yaml"
        
        # Migration logic
        if old_yaml_dir.exists() and not self.presets_dir.exists():
            print("NS-FlexPreset: Migrating yaml directory to presets...")
            shutil.move(str(old_yaml_dir), str(self.presets_dir))
        else:
            self.presets_dir.mkdir(exist_ok=True)
        
        self.write_lock = asyncio.Lock()
        self.observer = None
        self.file_handler = YAMLFileHandler(self)
        
        # B2: Store dynamic output information
        self._dynamic_output_types = []
        self._dynamic_output_names = []
        
        # C3: Track panel order for consistent output ordering
        self._panel_order = []
        
        # A3: Handle both attribute and method forms of PromptServer.instance
        self.server = PromptServer.instance() if callable(PromptServer.instance) else PromptServer.instance
        
        # A9: Track if routes are already registered
        self._routes_registered = False

        # 初期ロードフラグを追加
        self._initial_load_pending = True
        self._workflow_loading = False  # 追加：ワークフローロード中フラグ

        # Start watchdog observer
        self._start_watchdog()
        
        # Register socket handlers
        self._register_socket_handlers()
        
        # Initial enum refresh - 少し遅延を入れる
        import threading
        def delayed_refresh():
            import time
            time.sleep(0.5)  # バックエンドの準備を待つ
            self.refresh_enums()
        
        thread = threading.Thread(target=delayed_refresh)
        thread.daemon = True
        thread.start()
        
        # A2: Register cleanup on exit
        atexit.register(self.shutdown)
    
    def __del__(self):
        """Cleanup on deletion"""
        self.shutdown()
    
    def shutdown(self):
        """A2: Properly stop watchdog observer"""
        if self.observer and self.observer.is_alive():
            self.observer.stop()
            self.observer.join(timeout=2.0)
            self.observer = None
    
    @classmethod
    def INPUT_TYPES(cls):
        # Always get fresh YAML list when INPUT_TYPES is called
        presets_dir = Path(__file__).parent / "presets"
        presets_dir.mkdir(exist_ok=True)
        
        yaml_files = [f.name for f in presets_dir.glob("*.yaml")]
        if not yaml_files:
            # Create default yaml if none exist
            default_yaml = presets_dir / "default.yaml"
            default_yaml.write_text("example:\n  values:\n    sample_key:\n      type: string\n      value: 'Enter your value here'\n")
            yaml_files = ["default.yaml"]
        
        # Get all possible titles from all YAML files for validation
        all_titles = set([""])  # Always include empty string
        for yaml_file in yaml_files:
            yaml_path = presets_dir / yaml_file
            try:
                with open(yaml_path, 'r', encoding='utf-8') as f:
                    data = yaml.load(f, Loader=OrderedLoader) or {}
                    all_titles.update(data.keys())
            except:
                pass
        
        return {
            "required": {
                "select_yaml": (sorted(yaml_files), {"default": yaml_files[0] if yaml_files else ""}),
                "select_preset": (sorted(list(all_titles)), {"default": ""}),
                "input_preset_name": ("STRING", {"default": "", "multiline": False}),
            },
            "hidden": {
                "unique_id": "UNIQUE_ID",
            }
        }
    
    # R7: Legacy placeholders for ComfyUI core compatibility
    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("output",)
    
    # R2: Dynamic output support
    OUTPUT_IS_DYNAMIC = True
    
    @classmethod
    def dynamic_output_types(cls, select_yaml: str, select_preset: str, input_preset_name: str, **kwargs):
        """Generate dynamic outputs based on YAML values"""
        outputs = []
        output_names = []
        
        # Use input_preset_name if provided, otherwise use select_preset
        title_to_use = input_preset_name if input_preset_name else select_preset
        
        # Get instance to access panel order
        instance = cls._get_instance() if hasattr(cls, '_get_instance') else None
        
        # # ワークフローロード時の初期化チェック
        # if instance and hasattr(instance, '_initial_load_pending'):
        #     if instance._initial_load_pending:
        #         instance._initial_load_pending = False
        #         # 強制的にリフレッシュ
        #         instance.refresh_enums()
        
        if not title_to_use or not select_yaml:
            if instance and instance._workflow_loading:
                # ワークフローロード中は空の配列を返す
                return ([], [])
            else:
                # 通常時はデフォルト値を返す
                if instance:
                    instance._dynamic_output_types = ["STRING"]
                    instance._dynamic_output_names = ["output"]
                    instance._panel_order = []
                cls.RETURN_TYPES = ("STRING",)
                cls.RETURN_NAMES = ("output",)
                return (["STRING"], ["output"])
        
        presets_dir = Path(__file__).parent / "presets"
        yaml_path = presets_dir / select_yaml
        
        if not yaml_path.exists():
            # B2: Update instance if available
            if instance:
                instance._dynamic_output_types = ["STRING"]
                instance._dynamic_output_names = ["output"]
                instance._panel_order = []
            # C2: Update class-level RETURN_TYPES
            cls.RETURN_TYPES = ("STRING",)
            cls.RETURN_NAMES = ("output",)
            return (["STRING"], ["output"])
        
        try:
            with open(yaml_path, 'r', encoding='utf-8') as f:
                data = yaml.load(f, Loader=OrderedLoader) or {}
            
            if title_to_use in data and isinstance(data[title_to_use], dict):
                values = data[title_to_use].get('values', {})
                
                # C3: Use panel order if available, otherwise use YAML order
                if instance and instance._panel_order:
                    # Use UI panel order for consistency
                    keys_to_process = []
                    for panel_key in instance._panel_order:
                        if panel_key in values:
                            keys_to_process.append(panel_key)
                    # Add any missing keys from YAML
                    for key in values.keys():
                        if key not in keys_to_process:
                            keys_to_process.append(key)
                else:
                    # Fallback to YAML order
                    keys_to_process = list(values.keys())
                
                # Process keys in determined order
                for key in keys_to_process:
                    if key in values:
                        value_data = values[key]
                        if isinstance(value_data, dict):
                            value_type = value_data.get('type', 'string')
                            
                            # Output name format: <key>_<type>
                            output_name = f"{key}_{value_type}"
                            
                            if value_type == 'int':
                                outputs.append("INT")
                                output_names.append(output_name)
                            elif value_type == 'float':
                                outputs.append("FLOAT")
                                output_names.append(output_name)
                            else:  # string or default
                                outputs.append("STRING")
                                output_names.append(output_name)
        except Exception as e:
            print(f"Error reading YAML for dynamic outputs: {e}")
        
        # Always have at least one output
        if not outputs:
            outputs = ["STRING"]
            output_names = ["output"]
        
        # B2/C2: Store dynamic types in instance and update RETURN_TYPES
        if instance:
            instance._dynamic_output_types = outputs.copy()
            instance._dynamic_output_names = output_names.copy()
        
        # C2: Always update class-level RETURN_TYPES
        cls.RETURN_TYPES = tuple(outputs)
        cls.RETURN_NAMES = tuple(output_names)
        
        return (outputs, output_names)
    
    FUNCTION = "run"
    CATEGORY = "NS"
    
    @classmethod
    def _get_instance(cls):
        """Get or create singleton instance"""
        if not hasattr(cls, '_instance'):
            cls._instance = cls()
        return cls._instance
    
    def _get_yaml_files(self) -> List[str]:
        """Get list of YAML files in presets directory"""
        if not self.presets_dir.exists():
            return ["default.yaml"]
        
        yaml_files = [f.name for f in self.presets_dir.glob("*.yaml")]
        if not yaml_files:
            # Create default yaml if none exist
            default_yaml = self.presets_dir / "default.yaml"
            default_yaml.write_text("example:\n  values:\n    sample_key:\n      type: string\n      value: 'Enter your value here'\n")
            yaml_files = ["default.yaml"]
        
        return sorted(yaml_files)
    
    def _get_titles_from_yaml(self, yaml_file: str) -> List[str]:
        """Get titles from a YAML file"""
        yaml_path = self.presets_dir / yaml_file
        if not yaml_path.exists():
            return [""]
        
        try:
            with open(yaml_path, 'r', encoding='utf-8') as f:
                data = yaml.load(f, Loader=OrderedLoader) or {}
            return list(data.keys())
        except Exception as e:
            print(f"Error reading YAML {yaml_file}: {e}")
            self._handle_corrupt_yaml(yaml_path)
            return [""]
    
    def _get_values_from_yaml(self, yaml_file: str, title: str) -> Dict[str, Any]:
        """Get values from a YAML file for a specific title"""
        yaml_path = self.presets_dir / yaml_file
        if not yaml_path.exists():
            return {}
        
        try:
            with open(yaml_path, 'r', encoding='utf-8') as f:
                data = yaml.load(f, Loader=OrderedLoader) or {}
            
            if title in data and isinstance(data[title], dict):
                return data[title].get('values', {})
            return {}
        except Exception as e:
            print(f"Error reading values from YAML: {e}")
            return {}
    
    def _handle_corrupt_yaml(self, yaml_path: Path):
        """Handle corrupt YAML by renaming and creating new"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        bad_path = yaml_path.parent / f"bad_{timestamp}_{yaml_path.name}"
        shutil.move(str(yaml_path), str(bad_path))
        yaml_path.write_text("# Recovered from corrupt file\n")
    
    def _validate_value_type(self, value_type: str, value: str) -> bool:
        """Validate value matches its declared type"""
        if value_type not in self.TYPE_REGEX:
            return False
        
        regex = self.TYPE_REGEX[value_type]
        return bool(re.match(regex, str(value)))
    
    def _start_watchdog(self):
        """Start file system observer"""
        # A2: Don't start if already running
        if self.observer is None or not self.observer.is_alive():
            self.observer = Observer()
            self.observer.schedule(self.file_handler, str(self.presets_dir), recursive=False)
            self.observer.start()
    
    def refresh_enums(self):
        """Refresh YAML and title enums, broadcast update"""
        yaml_files = self._get_yaml_files()
        
        # Build enum data for all YAML files
        enum_data = {
            "yaml_files": yaml_files,
            "titles_by_yaml": {},
            "values_by_yaml_title": {}
        }
        
        for yaml_file in yaml_files:
            titles = self._get_titles_from_yaml(yaml_file)
            enum_data["titles_by_yaml"][yaml_file] = titles
            
            # Also get values for each title
            for title in titles:
                values = self._get_values_from_yaml(yaml_file, title)
                key = f"{yaml_file}::{title}"
                # Preserve insertion order of keys
                enum_data["values_by_yaml_title"][key] = list(values.keys())
        
        self._broadcast_enum(enum_data)
    
    def _ws_emit(self, event: str, payload: Any):
        """A4: Unified WebSocket emit with multiple fallbacks"""
        if hasattr(self.server, 'send_sync'):
            self.server.send_sync(event, payload)
        elif hasattr(self.server, 'broadcast_sync'):
            self.server.broadcast_sync(event, payload)
        elif hasattr(self.server, 'socketio'):
            self.server.socketio.emit(event, payload)
        else:
            print(f"Warning: No WebSocket method available to emit {event}")
    
    def _broadcast_enum(self, enum_data: Dict):
        """Broadcast enum update to frontend"""
        self._ws_emit("ns_flexpreset_enum", enum_data)
    
    def _register_socket_handlers(self):
        """Register socket.io handlers"""
        # A9: Only register once
        if self._routes_registered:
            return
        self._routes_registered = True
        
        server = self.server
        
        # get_prompt エンドポイントハンドラの修正
        @server.routes.post("/ns_flexpreset/get_prompt")
        async def get_prompt(request):
            data = await request.json()
            yaml_file = data.get("yaml", "")
            title = data.get("title", "")
            node_id = data.get("node_id", None)
            init_outputs = data.get("init_outputs", False)
            
            instance = NS_FlexPreset._get_instance()
            
            # ワークフローロード時の初期化
            if init_outputs:
                instance._workflow_loading = True
                instance._initial_load_pending = False
                # 強制的にenumをリフレッシュ
                instance.refresh_enums()
            
            # Force refresh dynamic outputs
            outputs, names = instance.__class__.dynamic_output_types(yaml_file, title, title)
            
            response_data = instance._get_prompt_data(yaml_file, title)
            response_data["refresh_outputs"] = True
            response_data["node_id"] = node_id
            response_data["outputs"] = outputs  # 追加：出力タイプを含める
            response_data["output_names"] = names  # 追加：出力名を含める
            
            # ワークフローロードフラグをリセット
            if init_outputs:
                instance._workflow_loading = False
            
            # Send via websocket
            instance._ws_emit("ns_flexpreset_set_widgets", response_data)
            
            return web.json_response({"success": True})
            
        @server.routes.post("/ns_flexpreset/value/update")
        async def update_value(request):
            """Update a value (add or modify)"""
            data = await request.json()
            yaml_file = data.get("yaml", "")
            title = data.get("title", "")
            key_name = data.get("key_name", "")
            key_type = data.get("key_type", "string")
            key_value = data.get("key_value", "")
            update_outputs = data.get("update_outputs", True)
            node_id = data.get("node_id", None)
            
            # Validate type
            instance = NS_FlexPreset._get_instance()
            if not instance._validate_value_type(key_type, key_value):
                print(f"NS-FlexPreset Warning: Value '{key_value}' does not match type '{key_type}'")
            
            success = await instance._add_value(yaml_file, title, key_name, key_type, key_value)
            if success and update_outputs:          # ←★ ここでガード
                instance.__class__.dynamic_output_types(yaml_file, title, title)
                instance.refresh_enums()
                updated_data = instance._get_prompt_data(yaml_file, title)
                updated_data["refresh_outputs"] = True
                updated_data["node_id"] = node_id
                instance._ws_emit("ns_flexpreset_set_widgets", updated_data)

            # B1: Return proper Response object
            return web.json_response({"success": success})
        
        @server.routes.post("/ns_flexpreset/value/add")
        async def add_value(request):
            """Add a new value to YAML"""
            data = await request.json()
            yaml_file = data.get("yaml", "")
            title = data.get("title", "")
            key_name = data.get("key_name", "")
            key_type = data.get("key_type", "string")
            key_value = data.get("key_value", "")
            node_id = data.get("node_id", None)
            
            # Validate type
            instance = NS_FlexPreset._get_instance()
            if not instance._validate_value_type(key_type, key_value):
                print(f"NS-FlexPreset Warning: Value '{key_value}' does not match type '{key_type}'")
            
            success = await instance._add_value(yaml_file, title, key_name, key_type, key_value)
            if success:
                # Force refresh dynamic outputs for new values
                instance.__class__.dynamic_output_types(yaml_file, title, title)
                
                instance.refresh_enums()
                # Send updated widget data
                updated_data = instance._get_prompt_data(yaml_file, title)
                updated_data["refresh_outputs"] = True  # New value needs output refresh
                updated_data["node_id"] = node_id  # Include node ID
                instance._ws_emit("ns_flexpreset_set_widgets", updated_data)
            
            # B1: Return proper Response object
            return web.json_response({"success": success})
        
        @server.routes.post("/ns_flexpreset/value/delete")
        async def delete_value(request):
            """Delete a value from YAML"""
            data = await request.json()
            yaml_file = data.get("yaml", "")
            title = data.get("title", "")
            key_name = data.get("key_name", "")
            node_id = data.get("node_id", None)
            
            instance = NS_FlexPreset._get_instance()
            
            # Remove from panel order if exists
            if key_name in instance._panel_order:
                instance._panel_order.remove(key_name)
            
            success = await instance._delete_value(yaml_file, title, key_name)
            if success:
                # Force refresh dynamic outputs
                instance.__class__.dynamic_output_types(yaml_file, title, title)
                
                instance.refresh_enums()
                # Send updated widget data after delete
                updated_data = instance._get_prompt_data(yaml_file, title)
                updated_data["refresh_outputs"] = True  # Deletion needs output refresh
                updated_data["node_id"] = node_id  # Include node ID
                instance._ws_emit("ns_flexpreset_set_widgets", updated_data)
            
            # B1: Return proper Response object
            return web.json_response({"success": success})
        
        @server.routes.post("/ns_flexpreset/value/update_key")
        async def update_key(request):
            """Update a key name"""
            data = await request.json()
            yaml_file = data.get("yaml", "")
            title = data.get("title", "")
            old_key = data.get("old_key", "")
            new_key = data.get("new_key", "")
            node_id = data.get("node_id", None)
            panel_order = data.get("panel_order", None)
            
            instance = NS_FlexPreset._get_instance()
            
            # Update panel order if provided
            if panel_order and old_key in instance._panel_order:
                instance._panel_order = panel_order
            elif old_key in instance._panel_order:
                # Fallback: update in-place
                idx = instance._panel_order.index(old_key)
                instance._panel_order[idx] = new_key
            
            success = await instance._update_key_name(yaml_file, title, old_key, new_key)
            if success:
                # Force refresh dynamic outputs
                instance.__class__.dynamic_output_types(yaml_file, title, title)
                
                instance.refresh_enums()
                # Send updated widget data
                updated_data = instance._get_prompt_data(yaml_file, title)
                updated_data["refresh_outputs"] = True
                updated_data["node_id"] = node_id
                instance._ws_emit("ns_flexpreset_set_widgets", updated_data)
            
            return web.json_response({"success": success})
        
        @server.routes.post("/ns_flexpreset/reload_yamls")
        async def reload_yamls(request):
            """Force reload YAML list"""
            instance = NS_FlexPreset._get_instance()
            instance.refresh_enums()
            # B1: Return proper Response object
            return web.json_response({"success": True})
        
        @server.routes.post("/ns_flexpreset/update_panel_order")
        async def update_panel_order(request):
            """C3: Update panel order from frontend"""
            data = await request.json()
            panel_order = data.get("panel_order", [])
            node_id = data.get("node_id", None)
            
            instance = NS_FlexPreset._get_instance()
            instance._panel_order = panel_order
            
            # Don't refresh dynamic outputs here - just store the order
            
            return web.json_response({"success": True})
    
    def _get_prompt_data(self, yaml_file: str, title: str) -> Dict[str, Any]:
        """Get prompt data from YAML"""
        yaml_path = self.presets_dir / yaml_file
        
        if not yaml_path.exists():
            return {"title": title, "values": {}}
        
        try:
            with open(yaml_path, 'r', encoding='utf-8') as f:
                data = yaml.load(f, Loader=OrderedLoader) or {}
            
            if title in data and isinstance(data[title], dict):
                values = data[title].get("values", {})
            else:
                values = {}
            
            # 順序を保持するために、キーのリストも送信
            keys_order = list(values.keys()) if values else []
            
            return {
                "title": title, 
                "values": values,
                "keys_order": keys_order  # 追加：キーの順序情報
            }
        except Exception as e:
            print(f"Error reading prompt: {e}")
            return {"title": title, "values": {}}
    
    async def _save_yaml(self, yaml_file: str, data: Dict):
        """Atomic save YAML with lock, preserving order"""
        async with self.write_lock:
            yaml_path = self.presets_dir / yaml_file
            
            with tempfile.NamedTemporaryFile(mode='w', dir=str(self.presets_dir), 
                                        delete=False, encoding='utf-8') as tmp:
                # Use custom dumper to preserve order
                yaml.dump(data, tmp, Dumper=OrderedDumper, 
                        default_flow_style=False, allow_unicode=True, 
                        sort_keys=False)
                tmp_path = tmp.name
            
            # Atomic replace
            os.replace(tmp_path, str(yaml_path))
    
    async def _ensure_title_exists(self, yaml_file: str, title: str) -> bool:
        """Ensure title exists in YAML file"""
        yaml_path = self.presets_dir / yaml_file
        
        try:
            # Read existing data
            if yaml_path.exists():
                with open(yaml_path, 'r', encoding='utf-8') as f:
                    data = yaml.load(f, Loader=OrderedLoader) or {}
            else:
                data = {}
            
            # Check if title exists
            if title not in data:
                data[title] = {"values": {}}
                await self._save_yaml(yaml_file, data)
                return True
            
            return True
            
        except Exception as e:
            print(f"Error ensuring title exists: {e}")
            return False
    
    async def _add_value(self, yaml_file: str, title: str, key_name: str, 
                        key_type: str, key_value: str) -> bool:
        """Add a value to YAML preserving order"""
        yaml_path = self.presets_dir / yaml_file
        
        try:
            # Read existing data with OrderedDict
            if yaml_path.exists():
                with open(yaml_path, 'r', encoding='utf-8') as f:
                    data = yaml.load(f, Loader=OrderedLoader) or OrderedDict()
            else:
                data = OrderedDict()
            
            # Ensure structure exists with OrderedDict
            if title not in data:
                data[title] = OrderedDict([("values", OrderedDict())])
            elif not isinstance(data[title], OrderedDict):
                # Convert to OrderedDict if needed
                data[title] = OrderedDict(data[title])
            
            if "values" not in data[title]:
                data[title]["values"] = OrderedDict()
            elif not isinstance(data[title]["values"], OrderedDict):
                # Convert values to OrderedDict if needed
                data[title]["values"] = OrderedDict(data[title]["values"])
            
            # Add value with OrderedDict
            data[title]["values"][key_name] = OrderedDict([
                ("type", key_type),
                ("value", key_value)
            ])
            
            # Save with order preserved
            await self._save_yaml(yaml_file, data)
            return True
            
        except Exception as e:
            print(f"Error adding value: {e}")
            return False
            

        
    async def _delete_value(self, yaml_file: str, title: str, key_name: str) -> bool:
        """Delete a value from YAML"""
        yaml_path = self.presets_dir / yaml_file
        
        if not yaml_path.exists():
            return False
        
        try:
            with open(yaml_path, 'r', encoding='utf-8') as f:
                data = yaml.load(f, Loader=OrderedLoader) or {}
            
            if title in data and "values" in data[title] and key_name in data[title]["values"]:
                del data[title]["values"][key_name]
                await self._save_yaml(yaml_file, data)
                return True
            
            return False
        except Exception as e:
            print(f"Error deleting value: {e}")
            return False
    
    async def _update_key_name(self, yaml_file: str, title: str, old_key: str, new_key: str) -> bool:
        """Update a key name while preserving order"""
        yaml_path = self.presets_dir / yaml_file
        
        if not yaml_path.exists() or not new_key:
            return False
        
        try:
            with open(yaml_path, 'r', encoding='utf-8') as f:
                data = yaml.load(f, Loader=OrderedLoader) or {}
            
            if (title in data and "values" in data[title] and 
                old_key in data[title]["values"] and old_key != new_key):
                
                # Create new OrderedDict to preserve order
                new_values = OrderedDict()
                
                # Copy all keys in original order, replacing the old key
                for key, value in data[title]["values"].items():
                    if key == old_key:
                        new_values[new_key] = value
                    else:
                        new_values[key] = value
                
                # Update data with new ordered values
                data[title]["values"] = dict(new_values)
                
                await self._save_yaml(yaml_file, data)
                return True
            
            return False
        except Exception as e:
            print(f"Error updating key name: {e}")
            return False
    
    def run(self, select_yaml: str, select_preset: str, input_preset_name: str, 
            unique_id: str) -> Tuple:
        """Main execution function"""
        
        # Use input_preset_name if provided, otherwise use select_preset
        title_to_use = input_preset_name if input_preset_name else select_preset
        
        # A1: Event loop aware async execution
        if title_to_use and select_yaml:
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    # Create task for running loop
                    asyncio.create_task(self._ensure_title_exists(select_yaml, title_to_use))
                else:
                    # Run in new loop
                    loop.run_until_complete(self._ensure_title_exists(select_yaml, title_to_use))
            except RuntimeError:
                # Fallback for edge cases
                asyncio.run(self._ensure_title_exists(select_yaml, title_to_use))
        
        # Get values from YAML
        values = self._get_values_from_yaml(select_yaml, title_to_use)
        
        # FIX: Update dynamic outputs properly before processing
        # Use class method correctly
        outputs, output_names = self.__class__.dynamic_output_types(
            select_yaml, select_preset, input_preset_name, unique_id=unique_id
        )
        
        # Build output values based on the same order as dynamic_output_types
        output_values = []
        
        # FIX: Match the exact logic from dynamic_output_types
        if values:
            # Get keys in the same order as dynamic_output_types
            keys_to_process = []
            if self._panel_order:
                # Use UI panel order for consistency
                for panel_key in self._panel_order:
                    if panel_key in values:
                        keys_to_process.append(panel_key)
                # Add any missing keys from YAML
                for key in values.keys():
                    if key not in keys_to_process:
                        keys_to_process.append(key)
            else:
                # Fallback to YAML order
                keys_to_process = list(values.keys())
            
            # Process values in the same order
            for key in keys_to_process:
                if key in values:
                    value_data = values[key]
                    if isinstance(value_data, dict):
                        value = value_data.get('value', '')
                        value_type = value_data.get('type', 'string')
                        
                        # Convert based on declared type
                        try:
                            if value_type == 'int':
                                output_values.append(int(value))
                            elif value_type == 'float':
                                output_values.append(float(value))
                            else:  # string
                                output_values.append(str(value))
                        except (ValueError, TypeError) as e:
                            # Error handling for type conversion
                            error_msg = f"NS-FlexPreset: Cannot convert '{value}' to {value_type} for key '{key}'"
                            print(error_msg)
                            raise ValueError(error_msg) from e
        
        # FIX: Ensure we have at least one output
        if not output_values:
            output_values = [""]
        
        # FIX: Ensure output count matches declared types exactly
        # This is critical to prevent "tuple index out of range" errors
        expected_count = len(outputs)
        actual_count = len(output_values)
        
        if actual_count < expected_count:
            # Pad with default values
            for i in range(actual_count, expected_count):
                output_type = outputs[i]
                if output_type == "INT":
                    output_values.append(0)
                elif output_type == "FLOAT":
                    output_values.append(0.0)
                else:  # STRING
                    output_values.append("")
        elif actual_count > expected_count:
            # Trim excess values
            output_values = output_values[:expected_count]
        
        # Return tuple matching exact output count
        return tuple(output_values)
    
    @classmethod
    def IS_CHANGED(cls, **kwargs):
        """Force re-execution on each run"""
        return float("NaN")
    
    @classmethod
    def VALIDATE_INPUTS(cls, select_yaml, select_preset, input_preset_name, unique_id):
        """Validate inputs before execution"""
        # Basic validation always passes to allow dynamic behavior
        # Actual type validation happens in run() method
        return True


# Singleton instance
_instance = None

def get_instance():
    global _instance
    if _instance is None:
        _instance = NS_FlexPreset()
    return _instance


NODE_CLASS_MAPPINGS = {
    "NS-FlexPreset": NS_FlexPreset
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "NS-FlexPreset": "NS Flex Preset"
}

# Initialize instance on import
get_instance()
