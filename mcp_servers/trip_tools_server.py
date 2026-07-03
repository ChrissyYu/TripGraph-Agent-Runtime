"""Minimal mock MCP server for TripPlan Phase 9B (stdio transport)."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("trip-tools")


@mcp.tool(name="mcp_weather")
def mcp_weather(city: str, date: str = "today") -> dict:
    """Get weather forecast for a city (mock MCP tool)."""
    conditions = ["sunny", "cloudy", "rainy", "partly cloudy"]
    idx = abs(hash(f"{city}:{date}")) % len(conditions)
    temp_c = 15 + (abs(hash(city)) % 20)
    return {
        "city": city,
        "date": date,
        "condition": conditions[idx],
        "temp_c": temp_c,
        "source": "mcp_mock",
    }


@mcp.tool(name="mcp_map")
def mcp_map(destination: str, origin: str = "酒店", day: int = 1) -> dict:
    """Plan a travel route for a day (mock MCP tool)."""
    duration_min = 20 + abs(hash(f"{origin}:{destination}:{day}")) % 180
    places = [origin, destination, f"{destination}景点{day}"]
    return {
        "origin": origin,
        "destination": destination,
        "route": f"{origin} → {destination}",
        "duration_min": duration_min,
        "places": places,
        "day": day,
        "source": "mcp_mock",
    }


@mcp.tool(name="mcp_budget")
def mcp_budget(city: str, days: int, currency: str = "CNY") -> dict:
    """Estimate trip budget (mock MCP tool)."""
    daily = 650.0 + (abs(hash(city)) % 200)
    breakdown = {
        "food": round(daily * 0.35, 1),
        "transport": round(daily * 0.15, 1),
        "accommodation": round(daily * 0.40, 1),
        "activities": round(daily * 0.10, 1),
    }
    total = round(daily * days, 1)
    return {
        "city": city,
        "total": total,
        "currency": currency,
        "days": days,
        "breakdown": breakdown,
        "source": "mcp_mock",
    }


if __name__ == "__main__":
    mcp.run(transport="stdio")
