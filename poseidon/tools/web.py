import re

import httpx

MAX_TEXT = 8_000


async def web_fetch(args: dict, ctx: dict) -> dict:
    async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
        r = await client.get(args["url"], headers={"User-Agent": "poseidon-ai/0.1"})
    text = r.text
    if "html" in r.headers.get("content-type", ""):
        text = re.sub(r"(?is)<(script|style|noscript).*?</\1>", " ", text)
        text = re.sub(r"(?s)<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text)
    return {"status": r.status_code, "content": text[:MAX_TEXT].strip()}
