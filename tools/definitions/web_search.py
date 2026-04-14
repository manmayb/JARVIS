import httpx
from tools.registry import register_tool

@register_tool(
    name="web_search",
    description="Search the web using DuckDuckGo. Returns up to 5 results with title, URL, and snippet.",
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query, 3-10 words"}
        },
        "required": ["query"]
    },
    permission_tier="read",
    task_types=["research", "general", "news"],
    timeout_seconds=10,
)
async def web_search(query: str) -> dict:
    url    = "https://api.duckduckgo.com/"
    params = {"q": query, "format": "json", "no_html": 1, "skip_disambig": 1}
    async with httpx.AsyncClient(timeout=9.0) as client:
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        data = resp.json()

    results = []
    for item in data.get("RelatedTopics", [])[:5]:
        if "Text" in item and "FirstURL" in item:
            results.append({
                "title":   item.get("Text", "")[:100],
                "url":     item.get("FirstURL", ""),
                "snippet": item.get("Text", ""),
            })
    if not results and data.get("AbstractText"):
        results.append({
            "title":   data.get("Heading", ""),
            "url":     data.get("AbstractURL", ""),
            "snippet": data.get("AbstractText", ""),
        })
    return {"results": results, "query": query, "count": len(results)}
