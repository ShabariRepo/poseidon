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
    parser.add_argument("--host", default="127.0.0.1",
                        help="bind address; non-local (e.g. 0.0.0.0) enables team server mode with per-member tokens")
    parser.add_argument("--no-browser", action="store_true", help="don't open the browser")
    parser.add_argument("--version", action="version", version=f"poseidon {__version__}")
    args = parser.parse_args()

    workdir = Path(args.path).expanduser().resolve()
    if not workdir.is_dir():
        parser.error(f"not a directory: {workdir}")

    from .server import create_app  # after arg parsing: fast --help/--version

    allow_remote = args.host not in ("127.0.0.1", "localhost")
    app = create_app(workdir, allow_remote=allow_remote)
    url = f"http://127.0.0.1:{args.port}"
    print(f"\n  \U0001f531 Poseidon {__version__}", flush=True)
    print(f"     chat:    {url}")
    print(f"     workdir: {workdir}")
    if allow_remote:
        print("     team server mode — join links (share with each member):")
        for m in app.state.store.member_tokens():
            print(f"       {m['name']:14} http://<this-host>:{args.port}/?token={m['token']}")
    print(flush=True)
    if not args.no_browser:
        threading.Timer(0.8, webbrowser.open, args=(url,)).start()
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
