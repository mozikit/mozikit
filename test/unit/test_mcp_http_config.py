from unittest.mock import patch

import pytest

pytest.importorskip("mcp")

from src.mcp_server import create_http_app


@pytest.mark.parametrize("settings, message", [
    ({"host": "192.0.2.1"}, "MOZIKIT_MCP_TOKEN"),
    ({"host": "0.0.0.0", "token": "secret"}, "allowed-host"),
    ({"host": "::", "token": "secret"}, "allowed-host"),
    ({"port": 0}, "port"), ({"port": 65536}, "port"),
    ({"host": "http://localhost"}, "host"),
    ({"token": ""}, "TOKEN"), ({"token": "has space"}, "TOKEN"),
    ({"token": "你好"}, "TOKEN"),
])
def test_http_refuses_invalid_or_unprotected_bindings(tmp_path, settings, message):
    with pytest.raises(ValueError, match=message):
        create_http_app(tmp_path, **settings)


def test_http_can_be_configured_for_lan_with_token(tmp_path):
    app = create_http_app(
        tmp_path, host="0.0.0.0", token="secret", allowed_hosts=["server.example:8000"],
        allowed_origins=["https://tools.example"],
    )
    assert [route.path for route in app.routes] == ["/mcp"]


def test_nondefault_loopback_binding_accepts_its_own_host(tmp_path):
    import anyio
    import httpx

    app = create_http_app(tmp_path, host="127.0.0.2")

    async def scenario():
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.2:8000",
            ) as client:
                response = await client.get("/mcp", headers={"Mcp-Session-Id": "missing"})
                assert response.status_code == 404  # Unknown session, not a rejected Host.

    anyio.run(scenario)


def test_cli_passes_http_options_and_rejects_unknown_transport(cli_runner):
    from src.cli import app

    with patch("src.mcp_server.run_http") as run:
        result = cli_runner.invoke(app, [
            "mcp", "--transport", "streamable-http", "--workspace", "/selected",
            "--port", "8123", "--allowed-host", "tools.example:8123",
            "--allowed-origin", "https://client.example",
        ])
        assert result.exit_code == 0, result.output
        run.assert_called_once_with(
            "/selected", "127.0.0.1", 8123, ["tools.example:8123"], ["https://client.example"],
        )
    result = cli_runner.invoke(app, ["mcp", "--transport", "unknown"])
    assert result.exit_code == 1 and "transport" in result.output


def test_http_environment_token_is_not_printed(tmp_path, monkeypatch, capsys):
    from src.mcp_server import run_http

    monkeypatch.setenv("MOZIKIT_MCP_TOKEN", "private-test-token")
    with patch("uvicorn.run") as run:
        run_http(tmp_path)
        app = run.call_args.args[0]
        assert app.routes[0].app._authorization == b"Bearer private-test-token"
    captured = capsys.readouterr()
    assert "private-test-token" not in captured.out + captured.err
