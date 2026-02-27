"""stm32-serial — readline CLI client for the serial bridge."""

import readline  # noqa: F401 — enables arrow keys and history
import socket
import sys


def main():
    host = "127.0.0.1"
    port = 8765

    try:
        sock = socket.create_connection((host, port), timeout=3)
    except (ConnectionRefusedError, OSError) as e:
        print(f"Could not connect to bridge at {host}:{port}: {e}")
        print("Is the MCP server running?")
        sys.exit(1)

    f = sock.makefile("rb")

    # Read welcome banner (everything up to and including the first "> ")
    banner = b""
    while not banner.endswith(b"> "):
        chunk = f.read(1)
        if not chunk:
            break
        banner += chunk
    print(banner.decode("utf-8", errors="replace"), end="", flush=True)

    # If a port path or nickname was given on the command line, send a connect command
    # Supports: stm32-serial /dev/cu.usbmodem1234
    #           stm32-serial "dev ccb"
    #           stm32-serial yellow
    if len(sys.argv) > 1:
        target = " ".join(sys.argv[1:])  # handles multi-word nicknames
        sock.sendall(f"connect {target}\n".encode())
        resp = _read_until_prompt(f)
        print(resp, end="", flush=True)

    try:
        while True:
            try:
                line = input()
            except EOFError:
                break

            sock.sendall((line + "\n").encode())

            if line.strip().lower() in ("quit", "exit"):
                resp = _read_until_prompt(f)
                print(resp, end="", flush=True)
                break

            resp = _read_until_prompt(f)
            print(resp, end="", flush=True)
    except KeyboardInterrupt:
        print()
    finally:
        sock.close()


def _read_until_prompt(f) -> str:
    """Read from the socket file until we see '> ' prompt or EOF."""
    buf = b""
    while not buf.endswith(b"> "):
        chunk = f.read(1)
        if not chunk:
            break
        buf += chunk
    return buf.decode("utf-8", errors="replace")


if __name__ == "__main__":
    main()
