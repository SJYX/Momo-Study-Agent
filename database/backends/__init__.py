from ._protocol import TursoBackend

# ── 集中探针：唯一的 HAS_LIBSQL / HAS_PYTURSO 来源 ──
try:
    import turso.sync  # noqa: F401
    HAS_PYTURSO = True
except ImportError:
    HAS_PYTURSO = False

try:
    import libsql  # noqa: F401
    HAS_LIBSQL = True
except ImportError:
    HAS_LIBSQL = False


_backend_singleton: TursoBackend | None = None


def get_active_backend() -> TursoBackend:
    global _backend_singleton
    if _backend_singleton is not None:
        return _backend_singleton

    from database.utils import _debug_log

    if HAS_PYTURSO:
        _debug_log("Backend: pyturso (turso.sync)", level="INFO", module="database.backends")
        from ._pyturso import PytursoBackend
        _backend_singleton = PytursoBackend()
    elif HAS_LIBSQL:
        _debug_log("Backend: libsql (embedded replica)", level="INFO", module="database.backends")
        from ._libsql import LibsqlBackend
        _backend_singleton = LibsqlBackend()
    else:
        raise RuntimeError("Neither pyturso nor libsql is available")
    return _backend_singleton
