import argparse
import threading
import webbrowser
from pathlib import Path

import uvicorn

from . import __version__


def main():
    parser = argparse.ArgumentParser(
        prog="poseidon",
        description="Open-source agent harness that opens as a chat in your browser.",
    )
    parser.add_argument(
        "path", nargs="?", default=".", help="working directory for the agent (default: cwd)"
    )
    parser.add_argument("--port", type=int, default=4747)
    parser.add_argument("--no-browser", action="store_true", help="don't open the browser")
    parser.add_argument("--version", action="version", version=f"poseidon {__version__}")
    args = parser.parse_args()

    workdir = Path(args.path).expanduser().resolve()
    if not workdir.is_dir():
        parser.error(f"not a directory: {workdir}")

    from .server import create_app  # after arg parsing: fast --help/--version

    app = create_app(workdir)
    url = f"http://127.0.0.1:{args.port}"
    print(f"\n  \U0001f531 Poseidon {__version__}")
    print(f"     chat:    {url}")
    print(f"     workdir: {workdir}\n")
    if not args.no_browser:
        threading.Timer(0.8, webbrowser.open, args=(url,)).start()
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
