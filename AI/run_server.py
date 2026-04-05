#!/usr/bin/env python3
"""Запуск сервера аналитики."""

import uvicorn
from analytics_server import (
    CFG_LOG_LEVEL,
    CFG_SERVER_HOST,
    CFG_SERVER_PORT,
)

if __name__ == "__main__":
    log_level = CFG_LOG_LEVEL.lower()
    if log_level not in ("debug", "info", "warning", "error", "critical"):
        log_level = "info"

    uvicorn.run(
        "analytics_server:app",
        host=CFG_SERVER_HOST,
        port=CFG_SERVER_PORT,
        reload=False,
        log_level=log_level,
    )
