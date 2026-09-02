import asyncio
import logging
import inspect
from typing import Dict, Any, Callable, List, Optional

logger = logging.getLogger("tool_dispatcher")

class ToolDispatcher:
    """
    Central registry for all agent tools.
    Supports async/sync tools, auto-docstring extraction, and structured error handling.
    """
    def __init__(self):
        # registry format: { "tool_name": {"func": callable, "desc": str, "args": list} }
        self.registry: Dict[str, Dict[str, Any]] = {}

    def register_tool(self, name: Optional[str] = None):
        """
        Decorator to register a function as a tool.
        If name is not provided, uses the function name.
        """
        def decorator(func: Callable):
            tool_name = name if name else func.__name__
            # Extract docstring as tool description for the LLM
            doc = inspect.getdoc(func) or "No description provided."
            
            # Extract function signature for tool definition
            sig = inspect.signature(func)
            args = []
            for k, v in sig.parameters.items():
                # Handle basic type hinting correctly
                if hasattr(v.annotation, '__name__'):
                    type_name = v.annotation.__name__
                else:
                    type_name = str(v.annotation).replace('typing.', '')
                args.append({"name": k, "type": type_name})
            
            self.registry[tool_name] = {
                "func": func,
                "desc": doc,
                "args": args
            }
            logger.info(f"Tool registered: {tool_name}")
            return func
        return decorator

    def register(self, name: str, func: Callable) -> Callable:
        """
        Direct registration: tool_dispatcher.register("tool_name", func).
        Equivalent to the register_tool decorator, for non-decorator use.
        """
        doc = inspect.getdoc(func) or "No description provided."
        sig = inspect.signature(func)
        args = []
        for k, v in sig.parameters.items():
            if hasattr(v.annotation, '__name__'):
                type_name = v.annotation.__name__
            else:
                type_name = str(v.annotation).replace('typing.', '')
            args.append({"name": k, "type": type_name})

        self.registry[name] = {"func": func, "desc": doc, "args": args}
        logger.info(f"Tool registered: {name}")
        return func

    async def call(self, name: Optional[str] = None, /, **kwargs) -> Any:
        """
        Executes a tool. Wraps sync calls in a thread executor to avoid freezing the event loop.
        Returns a structured response.

        `name` is positional-only so an LLM-supplied `name` kwarg (e.g. the
        customer's name for a booking) can never collide with it.
        Unknown kwargs are filtered against the tool's signature (and reported)
        instead of raising a TypeError that would abort the agent's turn.
        """
        if name is None:
            name = kwargs.pop("tool", None) or kwargs.pop("tool_name", None)
        if name not in self.registry:
            return {"status": "error", "message": f"Tool '{name}' not found in registry."}

        tool_data = self.registry[name]
        func = tool_data["func"]

        # Filter kwargs to what the tool actually accepts — LLMs often add
        # extra keys (customer_name, service, ...) that would raise TypeError.
        try:
            sig = inspect.signature(func)
            accepts_extra = any(p.kind is p.VAR_KEYWORD for p in sig.parameters.values())
            valid = set(sig.parameters)
            dropped = [k for k in kwargs if k not in valid]
            if not accepts_extra and dropped:
                logger.info("Tool %s: ignoring unsupported args %s", name, dropped)
                kwargs = {k: v for k, v in kwargs.items() if k in valid}
        except (TypeError, ValueError):
            pass

        try:
            if asyncio.iscoroutinefunction(func):
                result = await func(**kwargs)
            else:
                # Offload sync blocking calls to a separate thread to prevent event loop freeze
                result = await asyncio.to_thread(func, **kwargs)

            return {"status": "success", "data": result}
        
        except Exception as e:
            logger.error(f"Tool {name} execution failed: {e}", exc_info=True)
            # Return a *structured* error (never a raw exception) and instruct
            # the agent to try a different approach rather than crash the turn.
            return {
                "status": "error",
                "tool": name,
                "error": str(e),
                "message": (
                    f"Tool '{name}' failed: {e}. "
                    "Do not retry the same failing tool. Try a different tool, "
                    "rephrase the request, or ask the user for clarification."
                ),
            }

    def get_tool_definitions(self, tool_names: List[str]) -> str:
        """
        Returns tool descriptions for a specific subset of tools.
        Used by agents to understand their available toolkit.
        """
        defs = []
        for name in tool_names:
            if name in self.registry:
                d = self.registry[name]
                args_str = ", ".join([f"{a['name']} ({a['type']})" for a in d['args']])
                defs.append(f"- {name}({args_str}): {d['desc']}")
        
        return "\n".join(defs) if defs else "No tools available."

# Global dispatcher instance
tool_dispatcher = ToolDispatcher()


def _autoload_tools():
    """
    Import all tool modules so their `tool_dispatcher.register(...)` calls run.
    Without this the registry stays empty and every agent tool call fails with
    "Tool not found". Each import is guarded so one broken module can't crash
    the app (no silent failures: errors are logged).
    """
    import importlib
    for mod in ("tools.calendar_tools", "tools.crm_tools", "tools.handoff_tools",
                "tools.knowledge_tools", "tools.payment_tools"):
        try:
            importlib.import_module(mod)
        except Exception as e:  # pragma: no cover
            logger.error("Failed to load tool module %s: %s", mod, e)


_autoload_tools()
