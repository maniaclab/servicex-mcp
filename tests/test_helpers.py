"""Tests for shared helper functions in _helpers.py."""

from __future__ import annotations

from unittest.mock import MagicMock

from servicex_mcp.auth.factory import EnvBasedClientFactory
from servicex_mcp.tools._helpers import (
    _format_markdown_table,
    build_hints,
    check_write_allowed,
    classify_error,
    format_dict,
    format_list,
    get_servicex_client,
    human_bytes,
    paginate_iter,
)


class TestHumanBytes:
    def test_none_returns_na(self) -> None:
        assert human_bytes(None) == "N/A"

    def test_zero_returns_0_b(self) -> None:
        assert human_bytes(0) == "0 B"

    def test_bytes_under_1024_no_decimal(self) -> None:
        assert human_bytes(500) == "500 B"

    def test_exactly_1024_rolls_over_to_kb(self) -> None:
        assert human_bytes(1024) == "1.00 KB"

    def test_mb_boundary(self) -> None:
        assert human_bytes(1024 * 1024) == "1.00 MB"

    def test_gb_boundary(self) -> None:
        assert human_bytes(1024**3) == "1.00 GB"

    def test_tb_boundary(self) -> None:
        assert human_bytes(1024**4) == "1.00 TB"

    def test_large_value_docstring_example(self) -> None:
        assert human_bytes(50000000000000) == "45.47 TB"

    def test_pb_does_not_roll_over_further(self) -> None:
        assert human_bytes(1024**5) == "1.00 PB"

    def test_negative_value_is_prefixed_with_minus(self) -> None:
        assert human_bytes(-500) == "-500 B"

    def test_negative_value_above_1024(self) -> None:
        assert human_bytes(-1024) == "-1.00 KB"

    def test_float_input_is_truncated_to_int(self) -> None:
        assert human_bytes(500.9) == "500 B"


class TestPaginateIter:
    def test_under_limit_returns_all_items_with_no_footer(self) -> None:
        items, footer = paginate_iter(iter([1, 2, 3]), limit=10)
        assert items == [1, 2, 3]
        assert footer == ""

    def test_exactly_at_limit_returns_no_footer(self) -> None:
        items, footer = paginate_iter(iter([1, 2, 3]), limit=3)
        assert items == [1, 2, 3]
        assert footer == ""

    def test_over_limit_truncates_and_adds_footer(self) -> None:
        items, footer = paginate_iter(iter([1, 2, 3, 4]), limit=3)
        assert items == [1, 2, 3]
        assert "Showing 3 results (offset=0)" in footer
        assert "offset=3" in footer

    def test_offset_skips_leading_items(self) -> None:
        items, footer = paginate_iter(iter([1, 2, 3, 4, 5]), limit=2, offset=2)
        assert items == [3, 4]
        assert "offset=2" in footer
        assert "offset=4" in footer

    def test_offset_with_remaining_under_limit_has_no_footer(self) -> None:
        items, footer = paginate_iter(iter([1, 2, 3]), limit=10, offset=1)
        assert items == [2, 3]
        assert footer == ""


class TestBuildHints:
    def test_empty_list_returns_empty_string(self) -> None:
        assert build_hints([]) == ""

    def test_single_hint_formats_as_bullet(self) -> None:
        result = build_hints(["Do the thing"])
        assert "**Next steps:**" in result
        assert "- Do the thing" in result

    def test_multiple_hints_each_get_own_bullet(self) -> None:
        result = build_hints(["First hint", "Second hint"])
        assert "- First hint" in result
        assert "- Second hint" in result


class TestFormatDict:
    def test_produces_markdown_bullet_per_key(self) -> None:
        result = format_dict({"request_id": "req-1", "status": "Complete"})
        assert "- **request_id:** req-1" in result
        assert "- **status:** Complete" in result

    def test_skips_none_values(self) -> None:
        result = format_dict({"a": "yes", "b": None, "c": "also"})
        assert "b" not in result
        assert "- **a:** yes" in result

    def test_empty_dict_returns_empty_string(self) -> None:
        assert format_dict({}) == ""

    def test_all_none_values_returns_empty_string(self) -> None:
        assert format_dict({"x": None, "y": None}) == ""

    def test_include_keys_filters_and_orders(self) -> None:
        result = format_dict({"a": 1, "b": 2, "c": 3}, include_keys=["c", "a"])
        lines = result.split("\n")
        assert lines == ["- **c:** 3", "- **a:** 1"]

    def test_include_keys_skips_missing_keys_silently(self) -> None:
        result = format_dict({"a": 1}, include_keys=["a", "missing"])
        assert result == "- **a:** 1"

    def test_byte_key_is_humanized(self) -> None:
        result = format_dict({"size": 1024})
        assert "- **size:** 1.00 KB" in result

    def test_non_default_byte_keys_can_be_passed(self) -> None:
        result = format_dict({"custom": 1024}, byte_keys=frozenset({"custom"}))
        assert "- **custom:** 1.00 KB" in result


class TestFormatMarkdownTable:
    def test_renders_header_separator_and_rows(self) -> None:
        items = [
            {"request_id": "req-1", "size": 1024, "files": 5},
            {"request_id": "req-2", "size": 2048, "files": 10},
        ]
        result = _format_markdown_table(items, keys=["request_id", "size", "files"])
        assert "| request_id | size | files |" in result
        assert "| --- | --- | --- |" in result
        assert "| req-1 | 1.00 KB | 5 |" in result
        assert "| req-2 | 2.00 KB | 10 |" in result

    def test_missing_key_renders_empty_cell(self) -> None:
        result = _format_markdown_table([{"a": 1}], keys=["a", "b"])
        assert "| 1 |  |" in result

    def test_none_value_renders_empty_cell(self) -> None:
        result = _format_markdown_table([{"a": None}], keys=["a"])
        assert "|  |" in result


class TestFormatList:
    def test_uniform_dicts_render_as_markdown_table(self) -> None:
        items = [
            {"request_id": "req-1", "size": 1000, "files": 5},
            {"request_id": "req-2", "size": 2000, "files": 10},
        ]
        result = format_list(items)
        # Header row
        assert "| request_id | size | files |" in result
        # Separator row
        assert "| --- | --- | --- |" in result
        # Data rows — size field is humanized by default _DEFAULT_BYTE_KEYS
        assert "| req-1 | 1000 B | 5 |" in result
        assert "| req-2 | 1.95 KB | 10 |" in result

    def test_dicts_with_different_keys_render_as_bullet_list(self) -> None:
        items = [
            {"a": 1, "b": 2},
            {"a": 3, "c": 4},
        ]
        result = format_list(items)
        # No table header
        assert "| a |" not in result
        # Bullet format
        assert result.startswith("- ")

    def test_non_dict_items_render_as_bullet_list(self) -> None:
        result = format_list(["req-1", "req-2"])
        assert "- req-1" in result
        assert "- req-2" in result

    def test_empty_list_returns_empty_string(self) -> None:
        assert format_list([]) == ""

    def test_single_dict_renders_as_table(self) -> None:
        result = format_list([{"key": "value"}])
        assert "| key |" in result
        assert "| value |" in result

    def test_include_keys_filters_table_columns(self) -> None:
        items = [{"a": 1, "b": 2, "c": 3}, {"a": 4, "b": 5, "c": 6}]
        result = format_list(items, include_keys=["c", "a"])
        assert "| c | a |" in result
        assert "b" not in result

    def test_include_keys_filters_bullet_fallback(self) -> None:
        items = [{"a": 1, "b": 2}, {"a": 3, "c": 4}]
        result = format_list(items, include_keys=["a"])
        assert "b" not in result
        assert "c" not in result
        assert "**a:** 1" in result

    def test_bullet_fallback_humanizes_byte_keys(self) -> None:
        items = [{"a": 1, "b": 2}, {"a": 3, "c": 4, "file_size": 1024}]
        result = format_list(items)
        assert "**file_size:** 1.00 KB" in result

    def test_bullet_fallback_skips_none_values(self) -> None:
        items = [{"a": 1, "b": None}, {"a": 2, "c": 3}]
        result = format_list(items)
        assert "b" not in result


class TestGetServicexClient:
    def test_returns_client_from_factory(self) -> None:
        expected = MagicMock(name="servicex_client")
        factory = EnvBasedClientFactory(client=expected)
        ctx = MagicMock()
        ctx.request_context.lifespan_context = {
            "client_factory": factory,
            "read_only": False,
        }
        assert get_servicex_client(ctx) is expected

    def test_calls_factory_get_client_with_ctx(self) -> None:
        factory = MagicMock()
        ctx = MagicMock()
        ctx.request_context.lifespan_context = {
            "client_factory": factory,
            "read_only": False,
        }
        get_servicex_client(ctx)
        factory.get_client.assert_called_once_with(ctx)


def test_get_servicex_client_reads_lifespan_context() -> None:
    client = MagicMock()
    ctx = MagicMock()
    ctx.request_context.lifespan_context = {
        "client_factory": EnvBasedClientFactory(client=client),
        "read_only": False,
    }
    assert get_servicex_client(ctx) is client


class TestClassifyError:
    def test_authorization_error_by_type_name(self) -> None:
        class AuthorizationError(Exception):
            pass

        result = classify_error(AuthorizationError("nope"))
        assert result.startswith("Error: nope")
        assert "**Recovery:**" in result
        assert "servicex_info" in result

    def test_authorization_error_by_message(self) -> None:
        result = classify_error(Exception("You are not authorized to do this"))
        assert "**Recovery:**" in result
        assert "refresh token" in result

    def test_not_found_category(self) -> None:
        result = classify_error(Exception("Transform request-xyz not found"))
        assert "**Recovery:**" in result
        assert "servicex_list_transforms" in result
        assert "servicex_list_datasets" in result

    def test_invalid_transform_request_category(self) -> None:
        result = classify_error(ValueError("Invalid transform request: bad codegen"))
        assert "**Recovery:**" in result
        assert "servicex_list_code_generators" in result

    def test_connection_error_by_type_name(self) -> None:
        result = classify_error(ConnectionError("boom"))
        assert "**Recovery:**" in result
        assert "servicex_info" in result

    def test_timeout_category_via_message(self) -> None:
        result = classify_error(Exception("request timeout exceeded"))
        assert "**Recovery:**" in result
        assert "servicex_info" in result

    def test_timeout_error_by_type_name_with_no_matching_message(self) -> None:
        # asyncio.TimeoutError's __name__ is "TimeoutError"; its message may not
        # contain the literal substring "timeout" (e.g. raised with no args).
        result = classify_error(TimeoutError())
        assert "**Recovery:**" in result
        assert "servicex_info" in result

    def test_other_category_has_no_recovery_block(self) -> None:
        result = classify_error(Exception("something completely unexpected"))
        assert result == "Error: something completely unexpected"
        assert "Recovery" not in result


class TestCheckWriteAllowed:
    def test_read_only_true_returns_error_string(self) -> None:
        result = check_write_allowed({"read_only": True})
        assert result is not None
        assert "read-only mode" in result

    def test_read_only_false_returns_none(self) -> None:
        assert check_write_allowed({"read_only": False}) is None

    def test_missing_key_defaults_to_writable(self) -> None:
        assert check_write_allowed({}) is None
