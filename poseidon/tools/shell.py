import asyncio

COMMAND_TIMEOUT_SECS = 120
MAX_OUTPUT = 20_000


async def run_command(args: dict, ctx: dict) -> dict:
    proc = await asyncio.create_subprocess_shell(
        args["command"],
        cwd=str(ctx["workdir"]),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=COMMAND_TIMEOUT_SECS
        )
    except asyncio.TimeoutError:
        proc.kill()
        return {"error": f"command timed out after {COMMAND_TIMEOUT_SECS}s"}
    return {
        "exit_code": proc.returncode,
        "stdout": stdout.decode(errors="replace")[-MAX_OUTPUT:],
        "stderr": stderr.decode(errors="replace")[-MAX_OUTPUT:],
    }
