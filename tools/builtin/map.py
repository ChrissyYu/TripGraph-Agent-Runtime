"""Route planning tool (mock)."""

from pydantic import BaseModel, Field

from tools.decorator import tool


class MapInput(BaseModel):
    origin: str = Field(..., description="Starting location")
    destination: str = Field(..., description="Destination location")
    mode: str = Field(default="driving", description="Travel mode: driving, walking, transit")


@tool(
    name="map",
    description="Plan a route between two locations.",
    input_schema=MapInput,
)
async def map_tool(origin: str, destination: str, mode: str = "driving") -> dict:
    """Return mock route planning data."""
    distance_km = 5 + abs(hash(f"{origin}:{destination}")) % 495
    duration_min = int(distance_km * (3 if mode == "walking" else 1.2))
    return {
        "origin": origin,
        "destination": destination,
        "mode": mode,
        "distance_km": distance_km,
        "duration_min": duration_min,
        "steps": [
            f"Depart from {origin}",
            f"Head toward {destination}",
            f"Arrive at {destination}",
        ],
        "source": "mock",
    }
