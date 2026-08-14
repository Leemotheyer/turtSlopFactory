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
    name: str = Field(default="", max_length=255)
    description: str = ""


class Project(BaseModel):
    id: int
    name: str
    description: str
    status: str
    iteration: int
    created_at: datetime
    updated_at: datetime


class ProjectEvent(BaseModel):
    id: int
    project_id: int
    message: str
    created_at: datetime
