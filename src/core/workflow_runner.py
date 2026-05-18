#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Worklow Runner
Persistent worker process that executes nodes on demand.
Reads JSON commands from stdin and writes results to stdout.
"""
import sys
import json
import importlib.util
import inspect
import traceback
import io
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from src.core.exceptions import ErrorCode, LocalFlowError
from src.core.log_manager import get_logger

logger = get_logger("workflow_runner")


class ProgressAwareStdout:
    """Custom stdout wrapper that forwards progress lines and captures the rest."""

    PROGRESS_MARKER = "###PROGRESS##"
    LOG_MARKER = "###LOG##"

    def __init__(self, real_stdout, buffer):
        self.real_stdout = real_stdout
        self.buffer = buffer
        self._line_buffer = ""

    def write(self, text):
        if not text:
            return 0
        if self.PROGRESS_MARKER in text:
            self.real_stdout.write(text)
            self.real_stdout.flush()
        else:
            self.buffer.write(text)
            self._line_buffer += text
            while '\n' in self._line_buffer:
                line, self._line_buffer = self._line_buffer.split('\n', 1)
                self.real_stdout.write(f"{self.LOG_MARKER}{line}\n")
            self.real_stdout.flush()
        return len(text)

    def flush(self):
        if self._line_buffer:
            self.real_stdout.write(f"{self.LOG_MARKER}{self._line_buffer}\n")
            self._line_buffer = ""
        self.buffer.flush()
        self.real_stdout.flush()

    def fileno(self):
        return self.real_stdout.fileno()


def load_module_from_file(file_path):
    """Dynamically load a module from a file path"""
    try:
        module_name = Path(file_path).stem
        spec = importlib.util.spec_from_file_location(module_name, file_path)
        if spec and spec.loader:
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module
        return None
    except Exception as e:
        raise LocalFlowError(ErrorCode.NODE_CREATION_FAILED, f"Failed to load module {file_path}: {e}")

def handle_run_node(command):
    """Handle run_node command"""
    stdout_buffer = io.StringIO()
    stderr_buffer = io.StringIO()
    try:
        script_path = command.get("script_path")
        input_data = command.get("input_data", {})
        
        if not script_path:
            return {"success": False, "error": "script_path is required"}
            
        module = load_module_from_file(script_path)
        if not module:
            return {"success": False, "error": f"Could not load module from {script_path}"}
            
        if not hasattr(module, "execute"):
            return {"success": False, "error": f"Module {script_path} does not have an execute function"}

        execute_fn = module.execute
        signature = inspect.signature(execute_fn)
        params = list(signature.parameters.values())

        progress_stdout = ProgressAwareStdout(sys.stdout, stdout_buffer)
        with redirect_stdout(progress_stdout), redirect_stderr(stderr_buffer):
            if len(params) == 1:
                output_data = execute_fn(input_data)
            elif len(params) >= 2:
                node_config = getattr(module, "NODE_CONFIG", {})

                class NodeShim:
                    def __init__(self, config):
                        self.config = config

                output_data = execute_fn(NodeShim(node_config), input_data)
            else:
                return {
                    "success": False,
                    "error": f"Unsupported execute signature in {script_path}",
                    "stdout": stdout_buffer.getvalue(),
                    "stderr": stderr_buffer.getvalue(),
                }
        
        return {
            "success": True, 
            "data": output_data,
            "stdout": stdout_buffer.getvalue(),
            "stderr": stderr_buffer.getvalue(),
        }
    except Exception as e:
        tb = traceback.format_exc()
        return {
            "success": False, 
            "error": str(e),
            "traceback": tb,
            "stdout": stdout_buffer.getvalue(),
            "stderr": stderr_buffer.getvalue(),
        }

def main():
    """Main loop"""
    # Print ready signal
    print("READY", flush=True)
    
    while True:
        try:
            line = sys.stdin.readline()
            if not line:
                break
                
            line = line.strip()
            if not line:
                continue
                
            command = json.loads(line)
            cmd_type = command.get("type")
            
            if cmd_type == "exit":
                break
                
            elif cmd_type == "run_node":
                result = handle_run_node(command)
                
                # Write result
                print("###JSON_OUTPUT###")
                print(json.dumps(result, ensure_ascii=False))
                print("###JSON_OUTPUT_END###", flush=True)
                
            else:
                error_result = {"success": False, "error": f"Unknown command: {cmd_type}"}
                print("###JSON_OUTPUT###")
                print(json.dumps(error_result, ensure_ascii=False))
                print("###JSON_OUTPUT_END###", flush=True)
                
        except json.JSONDecodeError:
            error_result = {"success": False, "error": "Invalid JSON input"}
            print("###JSON_OUTPUT###")
            print(json.dumps(error_result, ensure_ascii=False))
            print("###JSON_OUTPUT_END###", flush=True)
            
        except Exception as e:
            error_result = {"success": False, "error": str(e)}
            print("###JSON_OUTPUT###")
            print(json.dumps(error_result, ensure_ascii=False))
            print("###JSON_OUTPUT_END###", flush=True)

if __name__ == "__main__":
    main()
