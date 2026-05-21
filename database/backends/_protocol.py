from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator, Protocol, runtime_checkable


@runtime_checkable
class TursoBackend(Protocol):
    name: str

    @contextmanager
    def op_lock_for(self, conn: Any) -> Iterator[None]: ...

    def connect(
        self, db_path: str, url: str, token: str, *, do_sync: bool = False
    ) -> Any: ...

    def do_sync_on(self, conn: Any) -> None: ...

    def is_supported(self) -> bool: ...
