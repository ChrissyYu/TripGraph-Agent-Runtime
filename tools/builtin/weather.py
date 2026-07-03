"""Weather forecast tool (mock)."""

from pydantic import BaseModel, Field

from tools.decorator import tool


class WeatherInput(BaseModel):
    city: str = Field(..., description="City name, e.g. Tokyo")
    date: str = Field(default="today", description="Date in YYYY-MM-DD or 'today'")


@tool(
    name="weather",
    description="Get weather forecast for a city on a given date.",
    input_schema=WeatherInput,
)
async def weather_tool(city: str, date: str = "today") -> dict:
    """Return mock weather data for development and testing."""
    conditions = ["sunny", "cloudy", "rainy", "partly cloudy"]
    idx = abs(hash(f"{city}:{date}")) % len(conditions)
    temp_c = 15 + (abs(hash(city)) % 20)
    return {
        "city": city,
        "date": date,
        "temp_c": temp_c,
        "condition": conditions[idx],
        "humidity_pct": 40 + (abs(hash(date)) % 40),
        "source": "mock",
    }
