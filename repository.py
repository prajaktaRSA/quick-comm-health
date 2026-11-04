"""In-memory storage backed by a dict.

The service talks to this small interface rather than to raw dicts, so a
database-backed repository with the same methods can replace it later.
"""

from __future__ import annotations

from typing import Dict, Generic, List, Optional, TypeVar

T = TypeVar("T")


class InMemoryRepository(Generic[T]):
    def __init__(self) -> None:
        self._items: Dict[str, T] = {}

    def add(self, key: str, item: T) -> None:
        self._items[key] = item

    def get(self, key: str) -> Optional[T]:
        return self._items.get(key)

    def remove(self, key: str) -> Optional[T]:
        return self._items.pop(key, None)

    def all(self) -> List[T]:
        return list(self._items.values())

    def __contains__(self, key: object) -> bool:
        return key in self._items
