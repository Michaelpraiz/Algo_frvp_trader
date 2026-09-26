import builtins

from mt5_mcp import server


def test_main_fails_if_mcp_sdk_cannot_be_loaded(monkeypatch):
    original_import = builtins.__import__

    def import_without_mcp(name, *args, **kwargs):
        if name == 'mcp.server.fastmcp':
            raise RuntimeError('MCP SDK import failed')
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, '__import__', import_without_mcp)

    assert server.main() == 1
