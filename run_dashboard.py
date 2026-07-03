#!/usr/bin/env python3
"""Run the dashboard: `python run_dashboard.py`."""
import uvicorn

from common.config import config

if __name__ == "__main__":
    uvicorn.run(
        "dashboard.app:app",
        host=config.dashboard_host,
        port=config.dashboard_port,
        reload=False,
    )
