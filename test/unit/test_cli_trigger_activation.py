import json
from unittest.mock import patch

from typer.testing import CliRunner

from src.cli import app


def test_workflow_activate_and_deactivate(tmp_path, monkeypatch):
    monkeypatch.setenv("MOZIKIT_WORKSPACE", str(tmp_path))
    workflow_path = tmp_path / "workflow.json"
    workflow_path.write_text(
        json.dumps(
            {
                "workflow_name": "event-workflow",
                "active": False,
                "triggers": [
                    {"trigger_id": "ticker", "trigger_type": "test", "config": {}}
                ],
                "nodes": [],
                "edges": [],
            }
        ),
        encoding="utf-8",
    )
    runner = CliRunner()

    with patch(
        "src.core.runtime_client.RuntimeClient.ensure_running", return_value=True
    ) as ensure_running:
        activated = runner.invoke(app, ["workflow", "activate", str(workflow_path)])

    assert activated.exit_code == 0
    assert json.loads(workflow_path.read_text(encoding="utf-8"))["active"] is True
    ensure_running.assert_called_once_with(required=True)

    deactivated = runner.invoke(app, ["workflow", "deactivate", str(workflow_path)])
    assert deactivated.exit_code == 0
    assert json.loads(workflow_path.read_text(encoding="utf-8"))["active"] is False


def test_workflow_activation_requires_trigger(tmp_path, monkeypatch):
    monkeypatch.setenv("MOZIKIT_WORKSPACE", str(tmp_path))
    workflow_path = tmp_path / "workflow.json"
    workflow_path.write_text(
        json.dumps({"workflow_name": "plain", "nodes": [], "edges": []}),
        encoding="utf-8",
    )

    result = CliRunner().invoke(app, ["workflow", "activate", str(workflow_path)])

    assert result.exit_code == 1
    assert "没有配置 Trigger" in result.output
