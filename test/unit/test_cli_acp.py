import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest
from typer.testing import CliRunner

from src.cli import app


ROOT = Path(__file__).resolve().parents[2]
AGENT = ROOT / "test" / "fixtures" / "fake_acp_agent.py"


def test_acp_help_does_not_import_sdk_or_qt():
    script = "from src.cli import app; import sys; assert 'acp' not in sys.modules; assert 'PySide6' not in sys.modules"
    process = subprocess.run(
        [sys.executable, "-c", script], cwd=ROOT, capture_output=True, text=True
    )
    assert process.returncode == 0, process.stderr
    result = CliRunner().invoke(app, ["acp", "prompt", "--help"])
    assert result.exit_code == 0
    assert "--agent" in result.stdout


def test_cli_prompt_json_over_real_stdio(tmp_path):
    process = subprocess.run(
        [
            sys.executable,
            "main.py",
            "acp",
            "prompt",
            "hello",
            "--agent",
            sys.executable,
            "--agent-arg",
            str(AGENT),
            "--cwd",
            str(tmp_path),
            "--json",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert process.returncode == 0, process.stderr
    payload = json.loads(process.stdout)
    assert payload["success"] is True
    assert payload["text"] == "你好，ACP"
    assert "fake agent diagnostic" in process.stderr
    assert "fake agent diagnostic" not in process.stdout


def test_cli_check_and_streaming_text(tmp_path):
    args = [
        "--agent",
        sys.executable,
        "--agent-arg",
        str(AGENT),
        "--cwd",
        str(tmp_path),
    ]
    result = CliRunner().invoke(app, ["acp", "check", *args, "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["protocolVersion"] == 1
    result = CliRunner().invoke(app, ["acp", "prompt", "hello", *args])
    assert result.exit_code == 0, result.output
    assert result.stdout == "你好，ACP\n"


def test_cli_error_json_and_timeout(tmp_path):
    result = CliRunner().invoke(
        app, ["acp", "check", "--agent", str(tmp_path / "missing"), "--json"]
    )
    assert result.exit_code == 1
    assert json.loads(result.stdout)["error_code"] == "ACP_PROCESS_START_FAILED"
    result = CliRunner().invoke(
        app,
        [
            "acp",
            "prompt",
            "wait",
            "--agent",
            sys.executable,
            "--agent-arg",
            str(AGENT),
            "--agent-arg",
            "wait",
            "--timeout",
            "0.05",
            "--json",
        ],
    )
    assert result.exit_code == 1, result.output
    assert json.loads(result.stdout)["error_code"] == "ACP_TIMEOUT"


def test_missing_sdk_is_reported_as_json(monkeypatch):
    monkeypatch.setitem(sys.modules, "acp", None)
    result = CliRunner().invoke(app, ["acp", "check", "--agent", "unused", "--json"])
    assert result.exit_code == 1
    assert json.loads(result.stdout)["error_code"] == "ACP_DEPENDENCY_MISSING"


@pytest.mark.skipif(
    os.name == "nt",
    reason="POSIX SIGINT integration; Windows has a different console signal API",
)
def test_sigint_sends_cancel_and_reaps_agent(tmp_path):
    trace = tmp_path / "wire.jsonl"
    process = subprocess.Popen(
        [
            sys.executable,
            "main.py",
            "acp",
            "prompt",
            "wait",
            "--agent",
            sys.executable,
            "--agent-arg",
            str(AGENT),
            "--agent-arg",
            "wait",
            "--agent-arg",
            str(trace),
            "--json",
        ],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            lines = trace.read_text().splitlines() if trace.exists() else []
            if any('"method": "session/prompt"' in line for line in lines):
                break
            assert process.poll() is None
            time.sleep(0.02)
        else:
            pytest.fail("Agent did not receive the prompt")
        process.send_signal(signal.SIGINT)
        stdout, stderr = process.communicate(timeout=10)
        assert process.returncode == 130, stderr
        assert json.loads(stdout)["error_code"] == "ACP_CANCELLED"
        requests = [json.loads(line) for line in trace.read_text().splitlines()]
        assert any(r.get("method") == "session/cancel" for r in requests)
        with pytest.raises(ProcessLookupError):
            os.kill(requests[0]["pid"], 0)
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate(timeout=10)
