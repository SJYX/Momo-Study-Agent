from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class TursoBackend(Protocol):
    name: str

    def connect(
        self, db_path: str, url: str, token: str,
        *, do_sync: bool = False,
    ) -> Any: ...

    def do_push_only(self, conn: Any) -> None: ...

    def do_pull_only(self, conn: Any) -> None: ...

    def do_sync_on(self, conn: Any) -> None: ...
