"""serial_sequence — run multi-step serial command sequences in a single tool call."""

import asyncio
import json
import time
from concurrent.futures import ThreadPoolExecutor

from .serial_tools import _connections, _read_with_polling, LINE_ENDINGS
from .serial_bridge import _get_send_lock

_executor = ThreadPoolExecutor(max_workers=2)


def _do_serial_sequence(
    steps_json: str,
    on_failure: str,
    filter_responses: bool,
) -> str:
    """Run a sequence of send/delay steps synchronously. Returns formatted report."""
    try:
        steps = json.loads(steps_json)
    except json.JSONDecodeError as e:
        return f"ERROR: Invalid JSON in steps: {e}"

    if not isinstance(steps, list):
        return "ERROR: steps must be a JSON array."

    lines: list[str] = []
    send_count = 0
    send_ok = 0
    assert_count = 0
    assert_pass = 0
    stopped = False

    for i, step in enumerate(steps, 1):
        if not isinstance(step, dict):
            lines.append(f"Step {i} ERROR: expected object, got {type(step).__name__}")
            continue

        # --- Delay step ---
        if "delay_ms" in step:
            ms = int(step["delay_ms"])
            lines.append(f"Step {i} DELAY: {ms}ms")
            time.sleep(ms / 1000.0)
            continue

        # --- Send step ---
        if "send" not in step or "to" not in step:
            lines.append(f"Step {i} ERROR: send step requires 'send' and 'to' fields")
            continue

        data = step["send"]
        cid = step["to"]
        expect = step.get("expect")
        read_timeout = float(step.get("read_timeout", 2.0))
        line_ending = step.get("line_ending", "lf")

        send_count += 1

        ser = _connections.get(cid)
        if ser is None or not ser.is_open:
            lines.append(f"Step {i} [{cid}] SEND: {data}")
            lines.append(f"  ERROR: No active connection '{cid}'. Call serial_connect first.")
            if on_failure == "stop":
                stopped = True
                break
            continue

        ending = LINE_ENDINGS.get(line_ending, "\n")
        payload = (data + ending).encode("utf-8")

        lock = _get_send_lock(cid)
        with lock:
            try:
                ser.reset_input_buffer()
                ser.write(payload)
                ser.flush()
            except Exception as e:
                lines.append(f"Step {i} [{cid}] SEND: {data}")
                lines.append(f"  ERROR: Write failed: {e}")
                if on_failure == "stop":
                    stopped = True
                    break
                continue

            raw = _read_with_polling(ser, timeout=read_timeout)

        # Decode response
        if raw:
            response_text = raw.decode("utf-8", errors="replace").strip()
        else:
            response_text = "(no data received)"

        lines.append(f"Step {i} [{cid}] SEND: {data}")
        lines.append(f"  Response: {response_text}")
        send_ok += 1

        # Check expect
        if expect is not None:
            assert_count += 1
            if filter_responses and response_text:
                # Match only against >-prefixed lines
                check_lines = [
                    ln for ln in response_text.splitlines() if ln.startswith(">")
                ]
                check_text = "\n".join(check_lines)
            else:
                check_text = response_text

            if expect in check_text:
                assert_pass += 1
                lines.append(f'  Expect "{expect}": PASS')
            else:
                lines.append(f'  Expect "{expect}": FAIL')
                if on_failure == "stop":
                    stopped = True
                    break

        lines.append("")

    # Summary
    summary_parts = [f"{send_ok}/{send_count} sends OK"]
    if assert_count > 0:
        summary_parts.append(f"{assert_pass}/{assert_count} assertions PASS")
    if stopped:
        summary_parts.append("STOPPED on failure")
    lines.append(f"Summary: {', '.join(summary_parts)}")

    return "\n".join(lines)


async def serial_sequence(
    steps: str,
    on_failure: str = "continue",
    filter_responses: bool = False,
) -> str:
    """Run a multi-step serial command sequence in one tool call.

    Executes a list of send and delay steps sequentially with real timing
    (no tool-call overhead between steps). Useful for hardware test sequences
    that are timing-sensitive.

    Args:
        steps: JSON array of step objects. Step types:
            Send: {"send": "CMD", "to": "/dev/cu.usbmodemXXXX", "expect": "OK", "read_timeout": 2.0, "line_ending": "lf"}
            Delay: {"delay_ms": 500}
            The "to" field is the connection_id (port path) from serial_connect.
            "expect", "read_timeout", and "line_ending" are optional on send steps.
        on_failure: "continue" (default) to run all steps, or "stop" to abort on first failure.
        filter_responses: If true, expect patterns match only >-prefixed VCP response lines.

    Returns:
        Formatted report with per-step results and a summary line.
    """
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        _executor,
        lambda: _do_serial_sequence(steps, on_failure, filter_responses),
    )
