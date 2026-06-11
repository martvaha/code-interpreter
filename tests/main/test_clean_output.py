"""Tests for Docker multiplexed output demultiplexing."""

from app.services.docker_executor import docker_executor


def _frame(stream_type: int, payload: bytes) -> bytes:
    """Build a Docker multiplexed stream frame (8-byte header + payload)."""
    return bytes([stream_type, 0, 0, 0]) + len(payload).to_bytes(4, "big") + payload


def test_clean_output_separates_stdout_and_stderr():
    raw = (
        _frame(1, b"hello ")
        + _frame(2, b"warning: something\n")
        + _frame(1, b"world\n")
        + _frame(2, b"another warning\n")
    )

    stdout, stderr = docker_executor._clean_output(raw)

    assert stdout == "hello world"
    assert stderr == "warning: something\nanother warning"


def test_clean_output_stdout_only():
    stdout, stderr = docker_executor._clean_output(_frame(1, b"just output\n"))

    assert stdout == "just output"
    assert stderr == ""


def test_clean_output_stderr_only():
    stdout, stderr = docker_executor._clean_output(_frame(2, b"only errors\n"))

    assert stdout == ""
    assert stderr == "only errors"


def test_clean_output_handles_invalid_utf8():
    raw = _frame(1, b"binary \xff\xfe data") + _frame(2, b"err \xff")

    stdout, stderr = docker_executor._clean_output(raw)

    assert "binary" in stdout and "data" in stdout
    assert "\ufffd" in stdout  # replacement character instead of UnicodeDecodeError
    assert stderr.startswith("err")


def test_clean_output_empty_and_truncated_input():
    assert docker_executor._clean_output(b"") == ("", "")
    # Truncated header / payload must not raise
    assert docker_executor._clean_output(b"\x01\x00\x00") == ("", "")
    truncated = bytes([1, 0, 0, 0]) + (100).to_bytes(4, "big") + b"short"
    assert docker_executor._clean_output(truncated) == ("", "")
