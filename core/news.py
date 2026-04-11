"""
NewsManager — fetches and curates news via RSS feeds.
Replaces DuckDuckGo search with feedparser RSS to avoid rate limits,
work offline (once cached), and require no API key.
"""

import json
import datetime
import requests
from config import OLLAMA_URL, RESPONDER_MODEL

# ---------------------------------------------------------------------------
# RSS feed sources — mirrors the feeds already used in gui/tabs/briefing.py
# ---------------------------------------------------------------------------
RSS_FEEDS = {
    "Top Stories": [
        ("https://www.abc.net.au/news/feed/10719986/rss.xml", "ABC News"),
    ],
    "Technology": [
        ("https://feeds.arstechnica.com/arstechnica/index",   "Ars Technica"),
    ],
    "Science": [
        ("https://www.sciencedaily.com/rss/top/science.xml",  "Science Daily"),
    ],
    "World": [
        ("https://www.abc.net.au/news/feed/104217382/rss.xml","ABC News"),
    ],
    "Space": [
        ("https://www.universetoday.com/feed/",               "Universe Today"),
    ],
}

MAX_PER_FEED = 5


def _parse_feed(url: str, category: str, source_name: str, max_items: int = MAX_PER_FEED) -> list:
    """Parse a single RSS feed URL and return a list of article dicts."""
    try:
        import feedparser
        feed = feedparser.parse(url)
        articles = []
        for entry in feed.entries[:max_items]:
            pub = entry.get("published_parsed") or entry.get("updated_parsed")
            if pub:
                dt = datetime.datetime(*pub[:6])
                date_str = dt.strftime("%d %b %Y, %H:%M")
                fetched_iso = dt.isoformat()
            else:
                date_str = "Recently"
                fetched_iso = datetime.datetime.now().isoformat()

            image_url = None
            if hasattr(entry, "media_thumbnail") and entry.media_thumbnail:
                image_url = entry.media_thumbnail[0].get("url")
            elif hasattr(entry, "media_content") and entry.media_content:
                image_url = entry.media_content[0].get("url")

            articles.append({
                "title":       entry.get("title", "No title"),
                "source":      source_name,
                "date":        date_str,
                "fetched_iso": fetched_iso,
                "category":    category,
                "url":         entry.get("link", ""),
                "image":       image_url,
                "body":        entry.get("summary", ""),
            })
        return articles
    except Exception as e:
        print(f"[NewsManager] Error fetching feed '{category}' ({url}): {e}")
        return []


class NewsManager:
    """Fetches and curates news from RSS feeds for the dashboard briefing."""

    def __init__(self):
        self.cache = {}
        self.cache_duration = datetime.timedelta(minutes=15)

    def get_briefing(self, status_callback=None, use_ai: bool = True) -> list:
        """
        Return a curated news briefing from RSS feeds.
        Optionally curates titles with the local LLM.
        Falls back to raw RSS data if AI curation fails or is disabled.
        Returns cached data if last fetch was within cache_duration.
        """
        cache_key = "briefing_ai" if use_ai else "briefing_raw"
        cached = self._get_from_cache(cache_key)
        if cached:
            return cached

        # Fetch from RSS feeds
        if status_callback:
            status_callback("Fetching RSS feeds...")

        raw_news = []
        for category, feeds in RSS_FEEDS.items():
            for url, source_name in feeds:
                if status_callback:
                    status_callback(f"Reading {category}...")
                raw_news.extend(_parse_feed(url, category, source_name))

        if not raw_news:
            print("[NewsManager] All RSS feeds failed or returned no articles.")
            return []

        # Optional AI curation via local Ollama
        curated = None
        if use_ai:
            if status_callback:
                status_callback("AI is reading and curating stories...")
            curated = self._curate_with_ai(raw_news)

        # Fall back to raw RSS if AI curation fails or is disabled
        if not curated:
            curated = self._format_raw(raw_news)

        self.cache[cache_key] = {
            "timestamp": datetime.datetime.now(),
            "data": curated,
        }

        return curated

    def _get_from_cache(self, key: str):
        """Return cached data if still within cache_duration, else None."""
        if key in self.cache:
            entry = self.cache[key]
            if datetime.datetime.now() - entry["timestamp"] < self.cache_duration:
                return entry["data"]
        return None

    def _format_raw(self, raw_news: list) -> list:
        """Deduplicate and return raw RSS articles without AI processing."""
        seen_urls = set()
        formatted = []
        for item in raw_news:
            url = item.get("url", "")
            if url and url in seen_urls:
                continue
            seen_urls.add(url)
            formatted.append({
                "title":    item.get("title"),
                "source":   item.get("source"),
                "date":     item.get("date"),
                "category": item.get("category", "General"),
                "url":      url,
                "image":    item.get("image"),
                "body":     item.get("body", ""),
            })
        return formatted[:10]

    def _curate_with_ai(self, raw_news: list):
        """Send raw RSS articles to local Ollama LLM to select and rewrite titles."""
        news_input = [
            {
                "id":       i,
                "title":    n.get("title"),
                "source":   n.get("source"),
                "category": n.get("category"),
            }
            for i, n in enumerate(raw_news)
        ]

        prompt = f"""You are an expert News Editor.
Here is a list of raw news articles:
{json.dumps(news_input, indent=2)}

Task:
1. Select the 6 most important and diverse stories.
2. Rewrite the titles to be punchy and short (under 10 words).
3. Assign a category: 'Technology', 'Science', 'Space', 'World', or 'Top Stories'.
4. Return ONLY a JSON array. Format:
   [{{"id": <original_id>, "title": "<new_title>", "category": "<category>"}}]

Do NOT add any markdown or extra text. Just the JSON array."""

        try:
            response = requests.post(
                f"{OLLAMA_URL}/chat",
                json={
                    "model":    RESPONDER_MODEL,
                    "messages": [{"role": "user", "content": prompt}],
                    "stream":   False,
                    "options":  {"temperature": 0.3},
                },
                timeout=60,
            )

            if response.status_code == 200:
                content = response.json()["message"]["content"]
                if "```json" in content:
                    content = content.split("```json")[1].split("```")[0].strip()
                elif "```" in content:
                    content = content.split("```")[1].strip()

                selected = json.loads(content)

                final_list = []
                for s in selected:
                    original = raw_news[s["id"]]
                    final_list.append({
                        "title":    s["title"],
                        "source":   original.get("source"),
                        "date":     original.get("date"),
                        "category": s["category"],
                        "url":      original.get("url"),
                        "image":    original.get("image"),
                        "body":     original.get("body", ""),
                    })
                return final_list

        except Exception as e:
            print(f"[NewsManager] AI curation failed: {e}")
            return None

        return None


# Global singleton used by function_executor and dashboard
news_manager = NewsManager()
