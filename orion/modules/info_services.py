"""External information service integrations (Wikipedia & Weather).

Designed as modular extensions aligned with Synopsis Section 15 (Future Scope).
Works cleanly offline/without credentials and upgrades automatically when
OPENWEATHER_API_KEY is configured in `.env`.
"""

from __future__ import annotations

from urllib.parse import quote

import httpx

from orion.config import OrionConfig


class InfoServices:
    """Fetches Wikipedia summaries and weather reports via HTTP."""

    def __init__(self, config: OrionConfig, timeout: float = 7.0) -> None:
        self.config = config
        self.timeout = timeout
        self._headers = {
            "User-Agent": "ORION-Desktop-Virtual-Assistant/1.0 (Academic Project)"
        }

    def fetch_wikipedia_summary(self, topic: str) -> dict[str, str]:
        """Fetch a concise summary from Wikipedia's REST API."""
        cleaned = topic.strip()
        if not cleaned:
            raise ValueError("Please provide a topic to search on Wikipedia.")

        # First try exact summary endpoint; fall back to search API if needed
        with httpx.Client(timeout=self.timeout, headers=self._headers, follow_redirects=True) as client:
            summary_url = (
                f"https://en.wikipedia.org/api/rest_v1/page/summary/{quote(cleaned.replace(' ', '_'))}"
            )
            resp = client.get(summary_url)
            if resp.status_code == 200:
                payload = resp.json()
                extract = (payload.get("extract") or "").strip()
                if extract and payload.get("type") != "disambiguation":
                    return {
                        "title": payload.get("title", cleaned),
                        "summary": self._trim_sentences(extract, 2),
                        "url": payload.get("content_urls", {})
                        .get("desktop", {})
                        .get("page", f"https://en.wikipedia.org/wiki/{quote(cleaned)}"),
                    }

            # Fallback search API to resolve fuzzy phrasing
            search_resp = client.get(
                "https://en.wikipedia.org/w/api.php",
                params={
                    "action": "opensearch",
                    "search": cleaned,
                    "limit": 1,
                    "namespace": 0,
                    "format": "json",
                },
            )
            if search_resp.status_code == 200:
                data = search_resp.json()
                if len(data) >= 4 and data[1]:
                    matched_title = data[1][0]
                    matched_url = data[3][0] if data[3] else ""
                    s2 = client.get(
                        f"https://en.wikipedia.org/api/rest_v1/page/summary/{quote(matched_title.replace(' ', '_'))}"
                    )
                    if s2.status_code == 200:
                        p2 = s2.json()
                        extract = (p2.get("extract") or "").strip()
                        if extract:
                            return {
                                "title": p2.get("title", matched_title),
                                "summary": self._trim_sentences(extract, 2),
                                "url": p2.get("content_urls", {})
                                .get("desktop", {})
                                .get("page", matched_url),
                            }

        raise LookupError(f"No Wikipedia article found for '{cleaned}'.")

    def fetch_weather(self, city: str | None = None) -> dict[str, str]:
        """Fetch current weather using OpenWeatherMap (if configured) or wttr.in."""
        target_city = (city or self.config.default_city or "Delhi").strip()
        if self.config.openweather_api_key:
            return self._fetch_openweather(target_city)
        return self._fetch_wttr(target_city)

    def _fetch_openweather(self, city: str) -> dict[str, str]:
        with httpx.Client(timeout=self.timeout, headers=self._headers) as client:
            resp = client.get(
                "https://api.openweathermap.org/data/2.5/weather",
                params={
                    "q": city,
                    "appid": self.config.openweather_api_key,
                    "units": "metric",
                },
            )
            if resp.status_code == 401:
                raise RuntimeError(
                    "OpenWeatherMap API key is invalid. Check OPENWEATHER_API_KEY in .env."
                )
            if resp.status_code == 404:
                raise LookupError(f"Could not find weather data for '{city}'.")
            resp.raise_for_status()
            data = resp.json()
            temp = round(float(data["main"]["temp"]), 1)
            feels = round(float(data["main"]["feels_like"]), 1)
            humidity = int(data["main"]["humidity"])
            desc = str(data["weather"][0]["description"]).capitalize()
            name = str(data.get("name") or city)
            return {
                "city": name,
                "temperature_c": str(temp),
                "feels_like_c": str(feels),
                "humidity": f"{humidity}%",
                "condition": desc,
                "source": "OpenWeatherMap",
                "summary": (
                    f"Weather in {name}: {desc}, {temp}°C "
                    f"(feels like {feels}°C), humidity {humidity}%."
                ),
            }

    def _fetch_wttr(self, city: str) -> dict[str, str]:
        with httpx.Client(timeout=self.timeout, headers=self._headers) as client:
            resp = client.get(f"https://wttr.in/{quote(city)}", params={"format": "j1"})
            resp.raise_for_status()
            data = resp.json()
            current = data["current_condition"][0]
            temp = current.get("temp_C", "?")
            feels = current.get("FeelsLikeC", "?")
            humidity = current.get("humidity", "?")
            desc_list = current.get("weatherDesc") or [{"value": "Clear"}]
            desc = str(desc_list[0].get("value", "Clear"))
            return {
                "city": city,
                "temperature_c": str(temp),
                "feels_like_c": str(feels),
                "humidity": f"{humidity}%",
                "condition": desc,
                "source": "wttr.in",
                "summary": (
                    f"Weather in {city}: {desc}, {temp}°C "
                    f"(feels like {feels}°C), humidity {humidity}%."
                ),
            }

    @staticmethod
    def _trim_sentences(text: str, max_sentences: int = 2) -> str:
        parts = [p.strip() for p in text.replace("\n", " ").split(". ") if p.strip()]
        if not parts:
            return text
        selected = ". ".join(parts[:max_sentences])
        if not selected.endswith("."):
            selected += "."
        return selected
