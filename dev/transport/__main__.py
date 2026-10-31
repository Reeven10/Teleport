"""Entry point for python -m dev.transport."""

import sys

from .pairing_cli import run_pairing_cli

if __name__ == "__main__":
    sys.exit(run_pairing_cli())
