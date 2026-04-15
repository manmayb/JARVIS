"""Notion integration tool.

Gated behind NOTION_TOKEN env var — if not set, this tool is never
registered and the LLM never sees it.
"""

from tools.registry import register_tool
from core.config import settings


@register_tool(
    name="notion_search",
    description="Search for a document or page in the user's Notion workspace. Returns titles and URLs.",
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "The search query string"}
        },
        "required": ["query"]
    },
    permission_tier="base",
    task_types=["query"],
    cache_ttl_seconds=300,
    requires=["NOTION_TOKEN"]
)
async def notion_search(query: str) -> str:
    """Search the Notion workspace using the Notion API.

    The NOTION_TOKEN env var must be a valid Notion Integration Token.
    The integration must be connected to the target workspace pages.
    """
    try:
        import httpx

        headers = {
            "Authorization": f"Bearer {settings.notion_token}",
            "Notion-Version": "2022-06-28",
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "https://api.notion.com/v1/search",
                headers=headers,
                json={"query": query, "page_size": 5},
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()

        results = data.get("results", [])
        if not results:
            return f"No Notion pages found matching '{query}'."

        lines = [f"Found {len(results)} Notion page(s) for '{query}':"]
        for page in results:
            title_prop = (
                page.get("properties", {})
                .get("title", {})
                .get("title", [{}])
            )
            title = title_prop[0].get("plain_text", "Untitled") if title_prop else "Untitled"
            url = page.get("url", "")
            lines.append(f"  • {title} — {url}")
        return "\n".join(lines)

    except Exception as exc:
        return f"TOOL_ERROR: Notion search failed — {exc}"


@register_tool(
    name="notion_create_page",
    description="Create a new page in a Notion workspace. Provide title, content, and parent_page_id (UUID, not URL).",
    parameters={
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "content": {"type": "string", "description": "Page body text. Lines separated by newlines become paragraph blocks."},
            "parent_page_id": {"type": "string", "description": "UUID of the parent page (NOT a URL)"}
        },
        "required": ["title", "content", "parent_page_id"]
    },
    permission_tier="user",
    task_types=["action"],
    requires=["NOTION_TOKEN"]
)
async def notion_create_page(title: str, content: str,
                              parent_page_id: str) -> str:
    """Create a new Notion page under the specified parent.

    Content is split by newlines into paragraph blocks.
    Lines longer than 2000 characters are split into multiple blocks.
    parent_page_id must be a Notion page UUID, not a URL.
    """
    try:
        import httpx

        # Build paragraph blocks from content lines
        children = []
        for line in content.split("\n"):
            # Split lines > 2000 chars
            chunks = [line[i:i+2000] for i in range(0, max(len(line), 1), 2000)]
            for chunk in chunks:
                children.append({
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {
                        "rich_text": [{"type": "text", "text": {"content": chunk}}]
                    }
                })

        headers = {
            "Authorization": f"Bearer {settings.notion_token}",
            "Notion-Version": "2022-06-28",
            "Content-Type": "application/json",
        }
        payload = {
            "parent": {"page_id": parent_page_id},
            "properties": {
                "title": [{"text": {"content": title}}]
            },
            "children": children[:100],  # Notion API max 100 blocks per request
        }

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "https://api.notion.com/v1/pages",
                headers=headers,
                json=payload,
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()

        return f"Page created: '{title}' — {data.get('url', 'no URL')}"

    except Exception as exc:
        return f"TOOL_ERROR: Notion page creation failed — {exc}"
