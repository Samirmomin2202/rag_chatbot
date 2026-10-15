import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.config import settings


def search_web(query: str) -> dict:
    if not settings.TAVILY_API_KEY:
        return {"error": "Web search is not configured. Set TAVILY_API_KEY in backend/.env."}

    body = json.dumps({
        "query": query,
        "search_depth": settings.TAVILY_SEARCH_DEPTH,
        "topic": "general",
        "max_results": 5,
        "chunks_per_source": 2,
        "include_answer": False,
        "include_raw_content": False,
        "include_images": False,
    }).encode("utf-8")
    request = Request(
        "https://api.tavily.com/search",
        data=body,
        headers={
            "Authorization": f"Bearer {settings.TAVILY_API_KEY}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=12) as response:
            data = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        return {"error": f"Web search provider returned HTTP {exc.code}. Check the Tavily key and usage limits."}
    except (URLError, TimeoutError, json.JSONDecodeError):
        return {"error": "Web search is temporarily unavailable."}

    return {
        "results": [
            {
                "title": item.get("title", "Web result"),
                "url": item.get("url", ""),
                "content": item.get("content", ""),
                "published_date": item.get("published_date"),
            }
            for item in data.get("results", [])
            if item.get("url", "").startswith(("https://", "http://"))
        ]
    }
