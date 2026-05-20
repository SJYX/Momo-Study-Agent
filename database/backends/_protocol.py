from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class TursoBackend(Protocol):
    name: str

    def connect(
        self, db_path: str, url: str, token: str, *, do_sync: bool = False
    ) -> Any: ...

    def do_sync_on(self, conn: Any) -> None: ...

    def is_supported(self) -> bool: ...
