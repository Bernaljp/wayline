"""What a launch line must carry so a session starts none of the owner's MCP servers or plugins (ticket 130).

`owner_with_a_plugin` gives a test an owner whose user settings enable one plugin; the assertions read the argv a
backend was given, the stand-in's record or the fake's `Call.argv`, never one the test rebuilds.
"""

import json
import os
import tempfile
from pathlib import Path
from unittest import mock

OWNER_PLUGIN = "owner-skills@owner-marketplace"
NO_MCP_SERVERS = {"mcpServers": {}}


def owner_with_a_plugin(case):
    """For the rest of `case`: `CLAUDE_CONFIG_DIR` is a home whose `settings.json` enables `OWNER_PLUGIN`."""
    home = tempfile.TemporaryDirectory(prefix="wayline-owner-home-")
    case.addCleanup(home.cleanup)
    Path(home.name, "settings.json").write_text(json.dumps({"enabledPlugins": {OWNER_PLUGIN: True}}) + "\n",
                                                encoding="utf-8")
    patched = mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": home.name})
    patched.start()
    case.addCleanup(patched.stop)


def assert_no_mcp(case, argv):
    """MCP servers only from `--mcp-config`, and the config given names none."""
    argv = [str(arg) for arg in argv]
    case.assertIn("--strict-mcp-config", argv)
    case.assertEqual(json.loads(argv[argv.index("--mcp-config") + 1]), NO_MCP_SERVERS)


def assert_no_owner_plugin(case, argv):
    """The settings file the launch line names turns `OWNER_PLUGIN` off (under `owner_with_a_plugin`)."""
    argv = [str(arg) for arg in argv]
    settings = json.loads(Path(argv[argv.index("--settings") + 1]).read_text(encoding="utf-8"))
    case.assertIs(settings["enabledPlugins"][OWNER_PLUGIN], False)


def assert_no_owner_mcp_or_plugin(case, argv):
    assert_no_mcp(case, argv)
    assert_no_owner_plugin(case, argv)
