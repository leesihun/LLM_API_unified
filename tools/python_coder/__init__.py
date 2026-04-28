"""
Python Coder Tool - Factory for selecting execution backend
Supports both native subprocess execution and OpenCode
"""
import config
from tools.python_coder.base import BasePythonExecutor


def get_python_executor(session_id: str) -> BasePythonExecutor:
    """
    Factory function to get Python executor based on config

    Args:
        session_id: Session ID for workspace isolation

    Returns:
        Python executor instance (Native or OpenCode)

    Raises:
        ValueError: If PYTHON_EXECUTOR_MODE is invalid
    """
    mode = config.PYTHON_EXECUTOR_MODE

    if mode == "native":
        from tools.python_coder.native_tool import NativePythonExecutor
        return NativePythonExecutor(session_id)

    elif mode == "opencode":
        from tools.python_coder.opencode_tool import OpenCodeExecutor
        return OpenCodeExecutor(session_id)

    else:
        raise ValueError(
            f"Invalid PYTHON_EXECUTOR_MODE: '{mode}'. "
            f"Must be 'native' or 'opencode'"
        )


# Backward compatibility: PythonCoderTool is now a factory
class PythonCoderTool:
    """
    Backward compatibility wrapper
    Automatically selects executor based on config.PYTHON_EXECUTOR_MODE
    """

    def __new__(cls, session_id: str):
        """
        Create appropriate executor instance based on config

        Args:
            session_id: Session ID for workspace isolation

        Returns:
            Executor instance (not PythonCoderTool, but compatible interface)
        """
        return get_python_executor(session_id)


__all__ = ["PythonCoderTool", "get_python_executor", "BasePythonExecutor"]
