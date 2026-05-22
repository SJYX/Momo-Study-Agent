from ._protocol import TursoBackend

# ── 集中探针：唯一的 HAS_PYTURSO 来源 ──
try:
    import turso.sync  # noqa: F401
    HAS_PYTURSO = True
except ImportError:
    HAS_PYTURSO = False

# libsql backend removed — kept as False for compatibility during cleanup (Phase 2)
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
    else:
        raise RuntimeError("pyturso (turso.sync) is required but not installed")
    return _backend_singleton
