from __future__ import annotations

from typing import Any

from backend.domain.execution_task import ExecutionTask
from backend.services.tools.runtime_authority import ToolRuntimeAuthority
from backend.workers.task_dispatcher import TaskHandlerContext, register_handler


@register_handler("tool.invoke", output_reason="tool action completed")
def tool_invoke_handler(task: ExecutionTask, context: TaskHandlerContext) -> dict[str, Any]:
    return ToolRuntimeAuthority().execute(task=task, context=context)
