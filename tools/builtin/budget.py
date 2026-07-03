"""Trip budget calculation tool."""

from pydantic import BaseModel, Field

from tools.decorator import tool


class BudgetInput(BaseModel):
    days: int = Field(..., ge=1, description="Number of travel days")
    daily_food: float = Field(default=100.0, ge=0, description="Daily food budget")
    daily_transport: float = Field(default=50.0, ge=0, description="Daily transport budget")
    daily_accommodation: float = Field(default=300.0, ge=0, description="Daily accommodation budget")
    activities: float = Field(default=0.0, ge=0, description="One-time activities budget")
    currency: str = Field(default="CNY", description="Currency code")


@tool(
    name="budget",
    description="Calculate total trip budget based on daily costs and activities.",
    input_schema=BudgetInput,
)
async def budget_tool(
    days: int,
    daily_food: float = 100.0,
    daily_transport: float = 50.0,
    daily_accommodation: float = 300.0,
    activities: float = 0.0,
    currency: str = "CNY",
) -> dict:
    """Compute itemized and total trip budget."""
    daily_total = daily_food + daily_transport + daily_accommodation
    subtotal = daily_total * days
    total = subtotal + activities
    return {
        "days": days,
        "currency": currency,
        "breakdown": {
            "food": round(daily_food * days, 2),
            "transport": round(daily_transport * days, 2),
            "accommodation": round(daily_accommodation * days, 2),
            "activities": round(activities, 2),
        },
        "daily_total": round(daily_total, 2),
        "total": round(total, 2),
    }
