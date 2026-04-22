"""
WikiEngine Plugin Base — Core Interfaces and Lifecycle Hooks.
定义了 WikiEngine 插件系统所需的基础协议、上下文对象以及生命周期钩子。
"""

from __future__ import annotations
from enum import Enum, auto
from typing import Protocol, runtime_checkable, Any, TYPE_CHECKING
from dataclasses import dataclass, field

if TYPE_CHECKING:
    from .plugins.atlas import AtlasIndex
    from .plugins.storage import WikiStorage
    from .plugins.search import WikiSearchEngine

class WikiHook(Enum):
    """Wiki 引擎生命周期钩子。"""
    ON_INITIALIZE = auto()      # 引擎启动时
    PRE_SHADOW = auto()         # 影子镜像同步前
    POST_SHADOW = auto()        # 影子镜像同步后
    PRE_COMPILE = auto()        # 编译流水线开始前
    ON_NODE_INGEST = auto()     # 单个节点解析完成，入库前
    POST_COMPILE = auto()       # 编译流水线结束后
    ON_SEARCH = auto()          # 搜索执行时（用于结果修正）
    ON_SHUTDOWN = auto()        # 引擎关闭时

@dataclass
class WikiPluginContext:
    """插件运行上下文，提供共享服务的访问权限。"""
    wiki_dir: str
    registry: WikiPluginRegistry
    config: Any = None
    
    # 核心服务 (由 Registry 提供)
    @property
    def atlas(self) -> Any:
        return self.registry.get_service("atlas")
        
    @property
    def storage(self) -> Any:
        return self.registry.get_service("storage")

@runtime_checkable
class WikiPlugin(Protocol):
    """Wiki 子插件协议。"""
    name: str
    
    async def initialize(self, ctx: WikiPluginContext) -> None:
        """初始化插件。"""
        ...

    async def on_hook(self, hook: WikiHook, payload: Any = None) -> Any:
        """响应钩子调用。"""
        ...

class WikiPluginRegistry:
    """Wiki 内部插件注册表。"""
    def __init__(self, ctx_factory: Any):
        self._plugins: dict[str, WikiPlugin] = {}
        self._hooks: dict[WikiHook, list[WikiPlugin]] = {h: [] for h in WikiHook}
        self._services: dict[str, Any] = {}
        self._ctx_factory = ctx_factory

    async def discover_and_register(self, plugins_dir: str | Path):
        """扫描目录并注册所有 WikiPlugin。"""
        import importlib.util
        import inspect
        import sys
        from pathlib import Path

        plugins_path = Path(plugins_dir)
        if not plugins_path.exists():
            return

        # 获取所有 .py 文件 (不包含 __init__.py)
        for py_file in plugins_path.glob("*.py"):
            if py_file.name == "__init__.py":
                continue

            module_name = f"engine.plugins.wiki.plugins.{py_file.stem}"
            try:
                spec = importlib.util.spec_from_file_location(module_name, py_file)
                if spec and spec.loader:
                    module = importlib.util.module_from_spec(spec)
                    sys.modules[module_name] = module
                    spec.loader.exec_module(module)

                    # 扫描模块中的 WikiPlugin 实现
                    for name, obj in inspect.getmembers(module):
                        if (
                            inspect.isclass(obj)
                            and issubclass(obj, WikiPlugin)
                            and obj is not WikiPlugin
                            and hasattr(obj, "name")
                        ):
                            try:
                                plugin_instance = obj()
                                self.register(plugin_instance)
                                # logger.info(f"Registered internal plugin: {obj.name} from {py_file.name}")
                            except Exception as e:
                                # logger.error(f"Failed to instantiate plugin {name} in {py_file.name}: {e}")
                                pass
            except Exception as e:
                # logger.error(f"Failed to load module {py_file.name}: {e}")
                pass

    def register(self, plugin: WikiPlugin):
        """注册一个插件。"""
        self._plugins[plugin.name] = plugin
        # 记录该插件支持的钩子
        for hook in WikiHook:
            # 这里可以根据插件是否实现了特定逻辑来决定是否加入钩子列表
            # 简单起见，全部加入，由插件自行在 on_hook 处理过滤
            self._hooks[hook].append(plugin)
            
    def register_service(self, name: str, service: Any):
        """注册一个具名服务（供其它插件调用）。"""
        self._services[name] = service

    def get_service(self, name: str) -> Any:
        """获取一个具名服务。"""
        return self._services.get(name)

    def get_plugin(self, name: str) -> Any:
        """获取已加载的插件实例。"""
        return self._plugins.get(name)

    async def dispatch(self, hook: WikiHook, payload: Any = None) -> list[Any]:
        """向所有监听该钩子的插件分发事件。"""
        results = []
        for plugin in self._hooks[hook]:
            try:
                res = await plugin.on_hook(hook, payload)
                if res is not None:
                    results.append(res)
            except Exception as e:
                import logging
                logging.getLogger("Coda.wiki.registry").error(f"Plugin {plugin.name} hook {hook} failed: {e}")
        return results
