"""Run one agent: python -m teleport [--port N] [--home DIR] [--sim-profile NAME] [--name NAME]."""

from __future__ import annotations

import argparse
import logging
import os

import uvicorn


def main() -> None:
    p = argparse.ArgumentParser(prog="teleport", description="Teleport device agent")
    p.add_argument("--host", help="bind address (env TELEPORT_HOST, default 127.0.0.1)")
    p.add_argument("--port", type=int, help="port (env TELEPORT_PORT, default 8765)")
    p.add_argument("--home", help="state folder (env TELEPORT_HOME, default ~/.teleport)")
    p.add_argument("--sim-profile", help="simulated device profile (env TELEPORT_SIM_PROFILE)")
    p.add_argument("--name", help="device display name (env TELEPORT_NAME)")
    p.add_argument("--reload", action="store_true", help="auto-reload on code changes")
    args = p.parse_args()

    # CLI flags override env; Settings.from_env() reads the result.
    for flag, env in [
        ("host", "TELEPORT_HOST"),
        ("port", "TELEPORT_PORT"),
        ("home", "TELEPORT_HOME"),
        ("sim_profile", "TELEPORT_SIM_PROFILE"),
        ("name", "TELEPORT_NAME"),
    ]:
        if (value := getattr(args, flag)) is not None:
            os.environ[env] = str(value)

    from .core.settings import Settings

    settings = Settings.from_env()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    uvicorn.run(
        "teleport.core.app:create_app",
        factory=True,
        host=settings.host,
        port=settings.port,
        reload=args.reload,
    )


if __name__ == "__main__":
    main()
