# 插件注册表：装饰器登记 + 按名取用，四个模块共用
from __future__ import annotations

from typing import Callable, Dict, Generic, List, Optional, TypeVar

T = TypeVar("T")


class Registry(Generic[T]):
    def __init__(self, kind: str) -> None:
        self._kind = kind
        self._items: Dict[str, T] = {}

    def register(self, name: Optional[str] = None) -> Callable[[T], T]:
        def decorate(obj: T) -> T:
            key = _key_of(obj, name)
            if key in self._items:
                raise KeyError(f"{self._kind} '{key}' 已被注册，勿重复登记")
            self._items[key] = obj
            return obj

        return decorate

    def get(self, name: str) -> T:
        key = str(name).strip().lower()
        if key not in self._items:
            raise KeyError(
                f"未知的 {self._kind}: '{name}'；可用项为 {self.names()}"
            )
        return self._items[key]

    def names(self) -> List[str]:
        return sorted(self._items)

    def __contains__(self, name: object) -> bool:
        return str(name).strip().lower() in self._items


def _key_of(obj: object, name: Optional[str]) -> str:
    key = name or getattr(obj, "name", None) or getattr(obj, "__name__", None)
    if not key:
        raise ValueError("注册项必须提供 name")
    return str(key).strip().lower()
