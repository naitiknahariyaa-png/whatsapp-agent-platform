import asyncio
import logging
import inspect
from typing import Dict, Any, Callable, List, Optional

logger = logging.getLogger("tool_dispatcher")

class ToolDispatcher:
    \"\"\"
    Central registry for all agent tools.
    Supports async/sync tools, auto-docstring extraction, and structured error handling.
    \"\"\"
    def __init__(self):
        # registry format: { \"tool_name\": {\"func\": callable, \"desc\": str, \"args\": list} }
        self.registry: Dict[str, Dict[str, Any]] = {}

    def register_tool(self, name: Optional[str] = None):
        \"\"\"
        Decorator to register a function as a tool.
        If name is not provided, uses the function name.
        \"\"\"
        def decorator(func: Callable):
            tool_name = name if name else func.__name__
            # Extract docstring as tool description for the LLM
            doc = inspect.getdoc(func) or \"No description provided.\"
            
            # Extract function signature for tool definition
            sig = inspect.signature(func)
            args = []
            for k, v in sig.parameters.items():
                # Handle basic type hinting correctly
                if hasattr(v.annotation, '__name__'):
                    type_name = v.annotation.__name__
                else:
                    type_name = str(v.annotation).replace('typing.', '')
                args.append({\"name\": k, \"type\": type_name})
            
            self.registry[tool_name] = {
                \"func\": func,
                \"desc\": doc,
                \"args\": args
            }
            logger.info(f\"Tool registered: {tool_name}\")
            return func
        return decorator

    async def call(self, name: str, **kwargs) -> Any:
        \"\"\"
        Executes a tool. Wraps sync calls in a thread executor to avoid freezing the event loop.
        Returns a structured response.
        \"\"\"
        if name not in self.registry:
            return {\"status\": \"error\", \"message\": f\"Tool '{name}' not found in registry.\"}
        
        tool_data = self.registry[name]
        func = tool_data[\"func\"]
        
        try:
            if asyncio.iscoroutinefunction(func):
                result = await func(**kwargs)
            else:
                # Offload sync blocking calls to a separate thread to prevent event loop freeze
                result = await asyncio.to_thread(func, **kwargs)
            
            return {\"status\": \"success\", \"data\": result}
        
        except Exception as e:
            logger.error(f\"Tool {name} execution failed: {e}\", exc_info=True)
            return {\"status\": \"error\", \"message\": str(e)}

    def get_tool_definitions(self, tool_names: List[str]) -> str:
        \"\"\"
        Returns tool descriptions for a specific subset of tools.
        Used by agents to understand their available toolkit.
        \"\"\"
        defs = []
        for name in tool_names:
            if name in self.registry:
                d = self.registry[name]
                args_str = \", \".join([f\"{a['name']} ({a['type']})\" for a in d['args']])
                defs.append(f\"- {name}({args_str}): {d['desc']}\")
        
        return \"\\n\".join(defs) if defs else \"No tools available.\"

# Global dispatcher instance
tool_dispatcher = ToolDispatcher()
