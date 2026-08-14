from datetime import datetime

from pydantic import BaseModel, Field


class ItemCreate(BaseModel):
    title: str
    body: str = ""


class Item(BaseModel):
    id: int
    title: str
    body: str


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    idea: str = ""


class ProjectEventOut(BaseModel):
    id: int
    message: str
    level: str
    created_at: datetime

    model_config = {"from_attributes": True}


class ProjectOut(BaseModel):
    id: int
    name: str
    idea: str
    status: str
    phase: str
    progress_pct: int
    created_at: datetime
    updated_at: datetime
    events: list[ProjectEventOut] = []

    model_config = {"from_attributes": True}


class ProjectSummary(BaseModel):
    id: int
    name: str
    idea: str
    status: str
    phase: str
    progress_pct: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
