"""Tests for the CLI argument parsing."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from servicex_mcp.cli import main


class TestCLIServe:
    def test_serve_calls_run(self) -> None:
        with (
            patch("servicex_mcp.server.ServiceXClient"),
            patch("servicex_mcp.server.MCPServer") as mock_mcp_cls,
            patch("sys.argv", ["servicex-mcp", "serve"]),
        ):
            main()
        mock_mcp_cls.return_value.run.assert_called_once_with(transport="stdio")

    def test_default_is_not_read_only(self) -> None:
        captured: dict[str, object] = {}

        def fake_serve(**kwargs: object) -> None:
            captured.update(kwargs)

        with (
            patch("sys.argv", ["servicex-mcp", "serve"]),
            patch("servicex_mcp.cli.serve", fake_serve),
        ):
            main()

        assert captured["read_only"] is False

    def test_read_only_flag_forwarded_to_serve(self) -> None:
        captured: dict[str, object] = {}

        def fake_serve(**kwargs: object) -> None:
            captured.update(kwargs)

        with (
            patch("sys.argv", ["servicex-mcp", "serve", "--read-only"]),
            patch("servicex_mcp.cli.serve", fake_serve),
        ):
            main()

        assert captured["read_only"] is True

    def test_backend_defaults_to_none(self) -> None:
        captured: dict[str, object] = {}

        def fake_serve(**kwargs: object) -> None:
            captured.update(kwargs)

        with (
            patch("sys.argv", ["servicex-mcp", "serve"]),
            patch("servicex_mcp.cli.serve", fake_serve),
        ):
            main()

        assert captured["backend"] is None

    def test_backend_flag_forwarded_to_serve(self) -> None:
        captured: dict[str, object] = {}

        def fake_serve(**kwargs: object) -> None:
            captured.update(kwargs)

        with (
            patch("sys.argv", ["servicex-mcp", "serve", "--backend", "uc-af"]),
            patch("servicex_mcp.cli.serve", fake_serve),
        ):
            main()

        assert captured["backend"] == "uc-af"

    def test_config_path_defaults_to_none(self) -> None:
        captured: dict[str, object] = {}

        def fake_serve(**kwargs: object) -> None:
            captured.update(kwargs)

        with (
            patch("sys.argv", ["servicex-mcp", "serve"]),
            patch("servicex_mcp.cli.serve", fake_serve),
        ):
            main()

        assert captured["config_path"] is None

    def test_config_path_flag_forwarded_to_serve(self) -> None:
        captured: dict[str, object] = {}

        def fake_serve(**kwargs: object) -> None:
            captured.update(kwargs)

        with (
            patch(
                "sys.argv",
                ["servicex-mcp", "serve", "--config-path", "/tmp/servicex.yaml"],
            ),
            patch("servicex_mcp.cli.serve", fake_serve),
        ):
            main()

        assert captured["config_path"] == "/tmp/servicex.yaml"

    def test_transport_defaults_to_stdio(self) -> None:
        captured: dict[str, object] = {}

        def fake_serve(**kwargs: object) -> None:
            captured.update(kwargs)

        with (
            patch("sys.argv", ["servicex-mcp", "serve"]),
            patch("servicex_mcp.cli.serve", fake_serve),
        ):
            main()

        assert captured["backend"] is None
        # transport itself isn't forwarded to serve() (stdio-only for now);
        # its effect is dispatch, verified by test_serve_calls_run above.

    def test_transport_http_exits_with_error(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with (
            patch("sys.argv", ["servicex-mcp", "serve", "--transport", "http"]),
            pytest.raises(SystemExit) as exc_info,
        ):
            main()
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "http" in captured.err.lower()

    def test_transport_rejects_invalid_value(self) -> None:
        with (
            patch("sys.argv", ["servicex-mcp", "serve", "--transport", "bogus"]),
            pytest.raises(SystemExit) as exc_info,
        ):
            main()
        assert exc_info.value.code != 0

    def test_log_level_defaults_to_info(self) -> None:
        with (
            patch("sys.argv", ["servicex-mcp", "serve"]),
            patch("servicex_mcp.cli.serve"),
            patch("logging.basicConfig") as mock_basic_config,
        ):
            main()
        assert mock_basic_config.call_args.kwargs["level"] == 20  # logging.INFO

    def test_log_level_flag_forwarded(self) -> None:
        with (
            patch("sys.argv", ["servicex-mcp", "serve", "--log-level", "debug"]),
            patch("servicex_mcp.cli.serve"),
            patch("logging.basicConfig") as mock_basic_config,
        ):
            main()
        assert mock_basic_config.call_args.kwargs["level"] == 10  # logging.DEBUG

    def test_log_level_rejects_invalid_value(self) -> None:
        with (
            patch("sys.argv", ["servicex-mcp", "serve", "--log-level", "bogus"]),
            pytest.raises(SystemExit) as exc_info,
        ):
            main()
        assert exc_info.value.code != 0

    def test_no_command_prints_help_and_exits_zero(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with (
            patch("sys.argv", ["servicex-mcp"]),
            pytest.raises(SystemExit) as exc_info,
        ):
            main()
        assert exc_info.value.code == 0
        captured = capsys.readouterr()
        assert "usage" in captured.out.lower()

    def test_help_does_not_crash(self, capsys: pytest.CaptureFixture[str]) -> None:
        with (
            patch("sys.argv", ["servicex-mcp", "--help"]),
            pytest.raises(SystemExit) as exc_info,
        ):
            main()
        assert exc_info.value.code == 0
        captured = capsys.readouterr()
        assert "usage" in captured.out.lower()

    def test_serve_help_does_not_crash(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with (
            patch("sys.argv", ["servicex-mcp", "serve", "--help"]),
            pytest.raises(SystemExit) as exc_info,
        ):
            main()
        assert exc_info.value.code == 0
        captured = capsys.readouterr()
        assert "usage" in captured.out.lower()
