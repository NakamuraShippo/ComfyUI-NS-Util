import os
import yaml
import json
import asyncio
import shutil
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Any
import tempfile
import atexit

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileSystemEvent

from server import PromptServer
from aiohttp import web

class SingleQuotedString(str):
    """Marker type for YAML values that should use single quotes"""


class PromptListDumper(yaml.SafeDumper):
    """Custom dumper for PromptList YAML output"""


def represent_single_quoted_string(dumper, value):
    return dumper.represent_scalar('tag:yaml.org,2002:str', str(value), style="'")


PromptListDumper.add_representer(SingleQuotedString, represent_single_quoted_string)


class YAMLFileHandler(FileSystemEventHandler):
    """Handles file system events for YAML files"""
    def __init__(self, node_instance):
        self.node_instance = node_instance

    def on_modified(self, event: FileSystemEvent):
        if not event.is_directory and event.src_path.endswith('.yaml'):
            self.node_instance._debounced_refresh()

    def on_created(self, event: FileSystemEvent):
        if not event.is_directory and event.src_path.endswith('.yaml'):
            self.node_instance._debounced_refresh()

    def on_deleted(self, event: FileSystemEvent):
        if not event.is_directory and event.src_path.endswith('.yaml'):
            self.node_instance._debounced_refresh()


class NS_PromptList:
    """NS-PromptList Node for ComfyUI"""

    def __init__(self):
        # YAMLディレクトリを nodes/promptlistYAML に設定
        self.yaml_dir = Path(__file__).parent / "promptlistYAML"
        self.yaml_dir.mkdir(exist_ok=True)

        self.write_lock = asyncio.Lock()
        self._io_lock = threading.Lock()  # スレッド間のファイルI/O保護
        self._writing = False  # 自身の書き込み中フラグ
        self._refresh_timer = None  # デバウンス用タイマー
        self._DEBOUNCE_SEC = 0.3  # デバウンス間隔
        self.observer = None
        self.file_handler = YAMLFileHandler(self)
        self._yaml_cache: Dict[str, Dict[str, Any]] = {}

        # Store server instance - FlexPresetと同じ方法を使用
        self.server = PromptServer.instance() if callable(PromptServer.instance) else PromptServer.instance

        # Track if routes are already registered
        self._routes_registered = False

        # Start watchdog observer
        self._start_watchdog()

        # Register socket handlers
        self._register_socket_handlers()

        # Initial enum refresh with delay
        def delayed_refresh():
            time.sleep(0.5)
            self.refresh_enums()

        thread = threading.Thread(target=delayed_refresh)
        thread.daemon = True
        thread.start()

        # Register cleanup on exit
        atexit.register(self.shutdown)

    def __del__(self):
        """Cleanup on deletion"""
        self.shutdown()

    def shutdown(self):
        """Properly stop watchdog observer"""
        if self.observer and self.observer.is_alive():
            self.observer.stop()
            self.observer.join(timeout=2.0)
            self.observer = None

    @classmethod
    def INPUT_TYPES(cls):
        # Always get fresh YAML list when INPUT_TYPES is called
        yaml_dir = Path(__file__).parent / "promptlistYAML"
        yaml_dir.mkdir(exist_ok=True)

        yaml_files = [f.name for f in yaml_dir.glob("*.yaml")
                      if not f.name.startswith("bad_")]
        if not yaml_files:
            # Create default yaml if none exist
            default_yaml = yaml_dir / "default.yaml"
            default_yaml.write_text("example:\n  prompt: 'Enter your prompt here'\n")
            yaml_files = ["default.yaml"]

        # Get all possible titles from all YAML files for validation
        all_titles = set([""])  # Always include empty string
        for yaml_file in yaml_files:
            yaml_path = yaml_dir / yaml_file
            try:
                data = cls._load_yaml_data(yaml_path)
                all_titles.update(str(title) for title in data.keys())
            except:
                pass

        return {
            "required": {
                "select_yaml": (sorted(yaml_files), {"default": yaml_files[0] if yaml_files else ""}),
                "select": (sorted(list(all_titles)), {"default": ""}),
                "title": ("STRING", {"default": "", "multiline": False}),
                "prompt": ("STRING", {"default": "", "multiline": True}),
            },
            "hidden": {
                "unique_id": "UNIQUE_ID",
            }
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("prompt",)
    FUNCTION = "run"
    CATEGORY = "NS/Utility"  # FlexPresetと同じカテゴリを使用

    @classmethod
    def _get_instance(cls):
        """Get or create singleton instance"""
        if not hasattr(cls, '_instance'):
            cls._instance = cls()
        return cls._instance

    def _get_yaml_files(self) -> List[str]:
        """Get list of YAML files in yaml directory"""
        if not self.yaml_dir.exists():
            return ["default.yaml"]

        yaml_files = [f.name for f in self.yaml_dir.glob("*.yaml")
                      if not f.name.startswith("bad_")]
        if not yaml_files:
            # Create default yaml if none exist
            default_yaml = self.yaml_dir / "default.yaml"
            default_yaml.write_text("example:\n  prompt: 'Enter your prompt here'\n")
            yaml_files = ["default.yaml"]

        return sorted(yaml_files)

    @staticmethod
    def _load_yaml_data(yaml_path: Path) -> Dict[str, Any]:
        """Load PromptList YAML with scalar values preserved as strings."""
        with open(yaml_path, 'r', encoding='utf-8') as f:
            data = yaml.load(f, Loader=yaml.BaseLoader) or {}

        return data if isinstance(data, dict) else {}

    def _get_yaml_data(self, yaml_path: Path, *, use_cache: bool = True) -> Dict[str, Any]:
        """Read YAML and fall back to the last good in-memory data when possible."""
        with self._io_lock:
            try:
                data = self._load_yaml_data(yaml_path)
                self._yaml_cache[yaml_path.name] = data
                return data
            except Exception as e:
                print(f"Error reading YAML {yaml_path.name}: {e}")
                if use_cache:
                    cached_data = self._yaml_cache.get(yaml_path.name)
                    if isinstance(cached_data, dict):
                        return cached_data
                return {}

    @staticmethod
    def _extract_prompt_text(entry: Any) -> str:
        """Normalize supported prompt entry shapes into a single prompt string."""
        if entry is None:
            return ""

        if isinstance(entry, dict):
            if "prompt" in entry:
                return NS_PromptList._extract_prompt_text(entry.get("prompt"))
            return ""

        if isinstance(entry, list):
            return "\n".join(
                text for text in (
                    NS_PromptList._extract_prompt_text(child) for child in entry
                )
                if text
            )

        return str(entry)

    def _get_titles_from_yaml(self, yaml_file: str) -> List[str]:
        """Get titles from a YAML file"""
        yaml_path = self.yaml_dir / yaml_file
        if not yaml_path.exists():
            return [""]

        data = self._get_yaml_data(yaml_path)
        if not data:
            print(f"[NS-PromptList] Could not read YAML: {yaml_file}")
            return [""]
        return [str(title) for title in data.keys()] or [""]

    def _debounced_refresh(self):
        """デバウンス付きリフレッシュ。自身の書き込み中はスキップ。"""
        if self._writing:
            return

        if self._refresh_timer is not None:
            self._refresh_timer.cancel()

        self._refresh_timer = threading.Timer(self._DEBOUNCE_SEC, self.refresh_enums)
        self._refresh_timer.daemon = True
        self._refresh_timer.start()

    def _start_watchdog(self):
        """Start file system observer"""
        if self.observer is None or not self.observer.is_alive():
            self.observer = Observer()
            self.observer.schedule(self.file_handler, str(self.yaml_dir), recursive=False)
            self.observer.start()

    def refresh_enums(self):
        """Refresh YAML and title enums, broadcast update"""
        enum_data = self._build_enum_data()
        self._broadcast_enum(enum_data)
        return enum_data

    def _build_enum_data(self) -> Dict[str, Any]:
        """Build enum data for all YAML files"""
        yaml_files = self._get_yaml_files()

        enum_data = {
            "yaml_files": yaml_files,
            "titles_by_yaml": {}
        }

        for yaml_file in yaml_files:
            titles = self._get_titles_from_yaml(yaml_file)
            enum_data["titles_by_yaml"][yaml_file] = titles

        return enum_data

    def _ws_emit(self, event: str, payload: Any):
        """Unified WebSocket emit with multiple fallbacks"""
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
        self._ws_emit("ns_promptlist_enum", enum_data)

    def _register_socket_handlers(self):
        """Register socket.io handlers"""
        # Only register once
        if self._routes_registered:
            return
        self._routes_registered = True

        server = self.server

        @server.routes.post("/ns_promptlist/get_prompt")
        async def get_prompt(request):
            data = await request.json()
            yaml_file = data.get("yaml", "")
            title = data.get("title", "")
            node_id = data.get("node_id", None)
            request_id = data.get("request_id", None)

            instance = NS_PromptList._get_instance()
            response_data = instance._get_prompt_data(yaml_file, title)
            response_data["node_id"] = node_id
            response_data["yaml_file"] = yaml_file
            response_data["request_id"] = request_id

            # Send via websocket
            instance._ws_emit("ns_promptlist_set_widgets", response_data)

            return web.json_response({"success": True})

        @server.routes.post("/ns_promptlist/reload_yamls")
        async def reload_yamls(request):
            """Force reload YAML list"""
            instance = NS_PromptList._get_instance()
            enum_data = instance.refresh_enums()
            return web.json_response({"success": True, **enum_data})

        @server.routes.post("/ns_promptlist/delete_title")
        async def delete_title(request):
            """Delete a title from YAML"""
            data = await request.json()
            yaml_file = data.get("yaml", "")
            title = data.get("title", "")
            node_id = data.get("node_id", None)

            instance = NS_PromptList._get_instance()
            success = await instance._delete_title(yaml_file, title)
            state = instance._build_ui_state(yaml_file)
            if success:
                instance.refresh_enums()
                instance._emit_prompt_state(yaml_file, state["title"], node_id)

            return web.json_response({"success": success, **state})

        @server.routes.post("/ns_promptlist/add_title")
        async def add_title(request):
            """Add or update a title in YAML"""
            data = await request.json()
            yaml_file = data.get("yaml", "")
            title = data.get("title", "").strip()
            prompt = data.get("prompt", "")
            node_id = data.get("node_id", None)

            instance = NS_PromptList._get_instance()
            success = await instance._upsert_title(yaml_file, title, prompt)
            state = instance._build_ui_state(yaml_file, title)
            if success:
                instance.refresh_enums()
                instance._emit_prompt_state(yaml_file, state["title"], node_id)

            return web.json_response({"success": success, **state})

        @server.routes.post("/ns_promptlist/create_yaml")
        async def create_yaml(request):
            """Create a new empty YAML file"""
            data = await request.json()
            yaml_name = data.get("yaml", "")
            node_id = data.get("node_id", None)

            if not yaml_name:
                return web.json_response({"success": False, "error": "Missing YAML name"})

            instance = NS_PromptList._get_instance()
            yaml_path = instance.yaml_dir / yaml_name

            if yaml_path.exists():
                return web.json_response({"success": False, "error": "YAML file already exists"})

            try:
                await instance._save_yaml(yaml_name, {})
                enum_data = instance.refresh_enums()
                return web.json_response({"success": True, **enum_data})
            except Exception as e:
                print(f"Error creating YAML: {e}")
                return web.json_response({"success": False, "error": str(e)})

    def _get_prompt_data(self, yaml_file: str, title: str) -> Dict[str, str]:
        """Get prompt data from YAML"""
        yaml_path = self.yaml_dir / yaml_file
        normalized_title = str(title) if title is not None else ""

        if not yaml_path.exists():
            return {"title": normalized_title, "prompt": ""}

        try:
            data = self._get_yaml_data(yaml_path)
            prompt = self._extract_prompt_text(data.get(normalized_title))

            return {"title": normalized_title, "prompt": prompt}
        except Exception as e:
            print(f"Error reading prompt: {e}")
            return {"title": normalized_title, "prompt": ""}

    def _build_ui_state(self, yaml_file: str, preferred_title: str = "") -> Dict[str, Any]:
        """Build the current UI state for a specific YAML file"""
        titles = [title for title in self._get_titles_from_yaml(yaml_file) if title]
        active_title = preferred_title if preferred_title in titles else (titles[0] if titles else "")
        prompt_data = self._get_prompt_data(yaml_file, active_title) if active_title else {
            "title": "",
            "prompt": "",
        }

        return {
            "yaml_file": yaml_file,
            "titles": titles,
            "title": prompt_data.get("title", ""),
            "prompt": prompt_data.get("prompt", ""),
        }

    def _emit_prompt_state(self, yaml_file: str, title: str, node_id: Optional[Any] = None,
                           request_id: Optional[str] = None):
        """Emit the current title/prompt state to the frontend"""
        prompt_data = self._get_prompt_data(yaml_file, title)
        prompt_data["node_id"] = node_id
        prompt_data["yaml_file"] = yaml_file
        prompt_data["request_id"] = request_id
        self._ws_emit("ns_promptlist_set_widgets", prompt_data)

    async def _save_yaml(self, yaml_file: str, data: Dict):
        """Atomic save YAML with lock"""
        async with self.write_lock:
            self._writing = True
            try:
                with self._io_lock:
                    yaml_path = self.yaml_dir / yaml_file
                    dump_data = self._prepare_data_for_dump(data)

                    # Use temporary file for atomic write
                    with tempfile.NamedTemporaryFile(mode='w', dir=str(self.yaml_dir),
                                                    delete=False, encoding='utf-8',
                                                    suffix='.tmp') as tmp:
                        yaml.dump(dump_data, tmp, Dumper=PromptListDumper, default_flow_style=False,
                                  allow_unicode=True, sort_keys=True)
                        tmp_path = tmp.name

                    # Atomic replace
                    os.replace(tmp_path, str(yaml_path))

                    # キャッシュを即座に更新
                    self._yaml_cache[yaml_file] = data
            finally:
                self._writing = False

    def _prepare_data_for_dump(self, value: Any) -> Any:
        """Wrap prompt values so they are dumped with single quotes"""
        if isinstance(value, dict):
            prepared = {}
            for key, child in value.items():
                if key == "prompt" and isinstance(child, str):
                    prepared[key] = SingleQuotedString(child)
                else:
                    prepared[key] = self._prepare_data_for_dump(child)
            return prepared

        if isinstance(value, list):
            return [self._prepare_data_for_dump(child) for child in value]

        return value

    async def _upsert_title(self, yaml_file: str, title: str, prompt: str) -> bool:
        """Create or update a title entry in YAML"""
        if not yaml_file or not title:
            return False

        yaml_path = self.yaml_dir / yaml_file

        try:
            # 読み込みと書き込みを同一ロック内で行い原子性を確保
            async with self.write_lock:
                self._writing = True
                try:
                    with self._io_lock:
                        if yaml_path.exists():
                            data = self._load_yaml_data(yaml_path)
                        else:
                            data = {}

                        if title not in data or not isinstance(data[title], dict):
                            data[title] = {}
                        data[title]["prompt"] = prompt or ""

                        dump_data = self._prepare_data_for_dump(data)

                        with tempfile.NamedTemporaryFile(mode='w', dir=str(self.yaml_dir),
                                                        delete=False, encoding='utf-8',
                                                        suffix='.tmp') as tmp:
                            yaml.dump(dump_data, tmp, Dumper=PromptListDumper,
                                      default_flow_style=False, allow_unicode=True,
                                      sort_keys=True)
                            tmp_path = tmp.name

                        os.replace(tmp_path, str(yaml_path))
                        self._yaml_cache[yaml_file] = data
                finally:
                    self._writing = False
            return True
        except Exception as e:
            print(f"Error adding title: {e}")
            return False

    async def _delete_title(self, yaml_file: str, title: str) -> bool:
        """Delete a title from YAML"""
        yaml_path = self.yaml_dir / yaml_file

        if not yaml_path.exists():
            return False

        try:
            # 読み込みと書き込みを同一ロック内で行い原子性を確保
            async with self.write_lock:
                self._writing = True
                try:
                    with self._io_lock:
                        data = self._load_yaml_data(yaml_path)

                        if title in data:
                            del data[title]

                            dump_data = self._prepare_data_for_dump(data)

                            with tempfile.NamedTemporaryFile(mode='w', dir=str(self.yaml_dir),
                                                            delete=False, encoding='utf-8',
                                                            suffix='.tmp') as tmp:
                                yaml.dump(dump_data, tmp, Dumper=PromptListDumper,
                                          default_flow_style=False, allow_unicode=True,
                                          sort_keys=True)
                                tmp_path = tmp.name

                            os.replace(tmp_path, str(yaml_path))
                            self._yaml_cache[yaml_file] = data
                        else:
                            return False
                finally:
                    self._writing = False
            return True
        except Exception as e:
            print(f"Error deleting title: {e}")
            return False

    def run(self, select_yaml: str, select: str, title: str, prompt: str,
            unique_id: str) -> Tuple[str]:
        """Main execution function"""

        # Check prompt length warning
        if len(prompt) > 4096:
            print(f"Warning: Prompt length ({len(prompt)} chars) exceeds recommended 4096 chars")

        # Save current prompt to YAML
        if title and prompt:
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    async def save_and_refresh():
                        success = await self._upsert_title(select_yaml, title, prompt)
                        if success:
                            self.refresh_enums()
                            self._emit_prompt_state(select_yaml, title, unique_id)

                    asyncio.create_task(save_and_refresh())
                else:
                    success = loop.run_until_complete(self._upsert_title(select_yaml, title, prompt))
                    if success:
                        self.refresh_enums()
                        self._emit_prompt_state(select_yaml, title, unique_id)

            except RuntimeError:
                # Fallback for edge cases
                success = asyncio.run(self._upsert_title(select_yaml, title, prompt))
                if success:
                    self.refresh_enums()
                    self._emit_prompt_state(select_yaml, title, unique_id)
            except Exception as e:
                print(f"Error saving prompt: {e}")

        return (prompt,)

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        """Force re-execution on each run"""
        return float("NaN")

    @classmethod
    def VALIDATE_INPUTS(cls, select_yaml, select, title, prompt, unique_id):
        """Validate inputs - always return True to avoid validation errors"""
        return True


# Singleton instance
_instance = None

def get_instance():
    global _instance
    if _instance is None:
        _instance = NS_PromptList()
    return _instance


NODE_CLASS_MAPPINGS = {
    "NS-PromptList": NS_PromptList
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "NS-PromptList": "NS Prompt List"
}

# Initialize instance on import

get_instance()
