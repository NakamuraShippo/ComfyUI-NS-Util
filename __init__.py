from importlib import import_module
from pathlib import Path

NODE_CLASS_MAPPINGS = {}
NODE_DISPLAY_NAME_MAPPINGS = {}

# nodes/ 配下の *.py を動的に import
for py in (Path(__file__).parent / "nodes").glob("*.py"):
    mod = import_module(f"{__name__}.nodes.{py.stem}")
    NODE_CLASS_MAPPINGS.update(mod.NODE_CLASS_MAPPINGS)
    NODE_DISPLAY_NAME_MAPPINGS.update(mod.NODE_DISPLAY_NAME_MAPPINGS)

WEB_DIRECTORY = "./web"