"""Simple item CRUD — backlog / quick-capture entries for the factory UI."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

router = APIRouter(prefix="/items", tags=["items"])

_items: list[dict] = []
_next_id = 1


class ItemCreate(BaseModel):
    title: str = Field(min_length=1, max_length=512)
    body: str = ""


class ItemUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=512)
    body: str | None = None


class Item(BaseModel):
    id: int
    title: str
    body: str


def _reset_items_for_tests() -> None:
    global _items, _next_id
    _items = []
    _next_id = 1


@router.get("", response_model=list[Item])
async def list_items() -> list[Item]:
    return [Item.model_validate(item) for item in _items]


@router.post("", response_model=Item, status_code=201)
async def create_item(body: ItemCreate) -> Item:
    global _next_id
    item = {"id": _next_id, "title": body.title, "body": body.body}
    _next_id += 1
    _items.append(item)
    return Item.model_validate(item)


@router.get("/{item_id}", response_model=Item)
async def get_item(item_id: int) -> Item:
    for item in _items:
        if item["id"] == item_id:
            return Item.model_validate(item)
    raise HTTPException(status_code=404, detail="Item not found")


@router.patch("/{item_id}", response_model=Item)
async def update_item(item_id: int, body: ItemUpdate) -> Item:
    for item in _items:
        if item["id"] == item_id:
            if body.title is not None:
                item["title"] = body.title
            if body.body is not None:
                item["body"] = body.body
            return Item.model_validate(item)
    raise HTTPException(status_code=404, detail="Item not found")


@router.delete("/{item_id}", status_code=204)
async def delete_item(item_id: int) -> None:
    for index, item in enumerate(_items):
        if item["id"] == item_id:
            _items.pop(index)
            return
    raise HTTPException(status_code=404, detail="Item not found")
