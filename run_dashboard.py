#!/usr/bin/env python3
"""Run the dashboard: `python run_dashboard.py`."""
import uvicorn

from common.config import config
from common.logging_setup import configure_logging

configure_logging()

if __name__ == "__main__":
    uvicorn.run(
        "dashboard.app:app",
        host=config.dashboard_host,
        port=config.dashboard_port,
        reload=False,
        # Trust X-Forwarded-* from the reverse proxy so requests behindnginx correctly resolve as https:// (matters for the OAutredirect_uri and secure cookies) instead of appearing as plain http:// from uvicorn's point of view.
        proxy_headers=True,
        forwarded_allow_ips=config.trusted_proxy_ips,
    )
