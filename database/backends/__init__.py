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


def get_active_backend() -> TursoBackend:
    if HAS_PYTURSO:
        from ._pyturso import PytursoBackend
        return PytursoBackend()
    if HAS_LIBSQL:
        from ._libsql import LibsqlBackend
        return LibsqlBackend()
    raise RuntimeError("Neither pyturso nor libsql is available")
