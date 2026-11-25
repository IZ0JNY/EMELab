# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ivan De Cesaris, IZ0JNY
"""HTTPS with the Windows certificate store when available (truststore), then the system store, then certifi."""
from __future__ import annotations


def _contexts():
    import ssl
    try:
        import truststore
        yield "truststore", truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    except Exception:
        pass
    yield "system", None
    try:
        import certifi
        yield "certifi", ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return
