# Data Directory

This directory stores runtime-generated user data and local databases.

Policy:
- Do not commit credential files or database snapshots.
- Keep only directory skeleton files in version control.
- Use `tools/preflight_check.py` and the setup wizard to regenerate required runtime files.
