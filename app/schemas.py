from pydantic import BaseModel, Field


class ScrapeRequest(BaseModel):
    business_type: str = Field(min_length=1, max_length=255)
    location: str = Field(min_length=1, max_length=255)
    requested_count: int = Field(ge=1, le=200)


class LeadResponse(BaseModel):
    name: str
    phone: str | None = None
    address: str | None = None
    website: str | None = None
    rating: float | None = None
    reviews_count: int | None = None
    google_maps_url: str | None = None

    class Config:
        from_attributes = True


class JobStatusResponse(BaseModel):
    id: str
    status: str
    progress: int
    requested_count: int
    business_type: str
    location: str
    error_message: str | None = None
    leads: list[LeadResponse] = []

    class Config:
        from_attributes = True
