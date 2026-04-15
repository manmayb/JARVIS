"""Notion integration tool.

Use a Notion integration token to keep the tool visible to the model.
The page-creation tool requires a parent page UUID, not a URL.
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
    name="create_notion_page",
    description=(
        "Create a new page in Notion. `parent_page_id` must be a page UUID, "
        "not a URL. Content lines are converted to paragraph blocks."
    ),
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
async def create_notion_page(title: str, content: str, parent_page_id: str) -> dict:
    """Create a Notion page beneath an existing parent page.

    Args:
        title: Page title.
        content: Page body text. Newline-separated lines become paragraph
            blocks, and lines longer than 2000 characters are split into
            multiple blocks to satisfy Notion limits.
        parent_page_id: The UUID of the parent page. This must be a UUID,
            not a Notion page URL.

    Returns:
        ``{"status": "created", "page_id": ..., "url": ...}`` on
        success or a structured error dictionary on failure.
    """
    try:
        from notion_client import AsyncClient
        from notion_client.errors import APIResponseError

        children = []
        for line in content.split("\n"):
            chunks = [line[i:i + 2000] for i in range(0, max(len(line), 1), 2000)]
            for chunk in chunks:
                children.append({
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {
                        "rich_text": [{"type": "text", "text": {"content": chunk}}]
                    }
                })

        payload = {
            "parent": {"page_id": parent_page_id},
            "properties": {
                "title": {
                    "title": [{"text": {"content": title}}]
                }
            },
            "children": children,
        }

        client = AsyncClient(auth=settings.notion_token)
        response = await client.pages.create(**payload)
        return {"status": "created", "page_id": response["id"], "url": response["url"]}
    except APIResponseError as exc:
        return {"status": "error", "detail": str(exc)}
    except Exception as exc:
        return {"status": "error", "detail": str(exc)}
