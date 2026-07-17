"""Root conftest for watertwin-api.

Present so pytest anchors its rootdir at the service directory; the import
paths (service root + shared ``packages/``) are configured in ``pytest.ini``.

Authentication defaults to the explicit dev-mode bypass for the test-suites so
the existing (pre-identity) suites and local dev keep working unchanged. The
dedicated ``tests/test_auth.py`` suite flips this per-test to exercise the
enforced Keycloak-validation path. ``setdefault`` means an outer environment
that has already chosen a mode always wins.
"""

import os

os.environ.setdefault("WATERTWIN_AUTH_DISABLED", "true")
