from pathlib import Path

MAX_READ = 100_000


def resolve_path(workdir: Path, p: str) -> Path:
    path = Path(p)
    path = path.resolve() if path.is_absolute() else (workdir / path).resolve()
    if not path.is_relative_to(workdir):
        raise ValueError(f"{p} is outside the working directory")
    return path


async def list_dir(args: dict, ctx: dict) -> dict:
    path = resolve_path(ctx["workdir"], args.get("path", "."))
    if not path.is_dir():
        return {"error": f"not a directory: {args.get('path')}"}
    entries = []
    for child in sorted(path.iterdir(), key=lambda c: (not c.is_dir(), c.name.lower())):
        if child.name.startswith(".") and child.name not in (".env.example",):
            continue
        entries.append(
            {
                "name": child.name,
                "dir": child.is_dir(),
                "size": child.stat().st_size if child.is_file() else None,
            }
        )
    return {"path": str(path.relative_to(ctx["workdir"])) or ".", "entries": entries[:500]}


async def read_file(args: dict, ctx: dict) -> dict:
    path = resolve_path(ctx["workdir"], args["path"])
    if not path.is_file():
        return {"error": f"not a file: {args['path']}"}
    data = path.read_text(errors="replace")
    truncated = len(data) > MAX_READ
    return {"content": data[:MAX_READ], "truncated": truncated}


async def write_file(args: dict, ctx: dict) -> dict:
    path = resolve_path(ctx["workdir"], args["path"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(args["content"])
    return {"ok": True, "bytes": len(args["content"].encode())}


async def edit_file(args: dict, ctx: dict) -> dict:
    path = resolve_path(ctx["workdir"], args["path"])
    if not path.is_file():
        return {"error": f"not a file: {args['path']}"}
    text = path.read_text(errors="replace")
    count = text.count(args["old_string"])
    if count == 0:
        return {"error": "old_string not found in file"}
    if count > 1:
        return {"error": f"old_string appears {count} times; make it unique"}
    path.write_text(text.replace(args["old_string"], args["new_string"], 1))
    return {"ok": True}
