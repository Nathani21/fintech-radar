"""Lets `python -m radar` run the command line in radar/cli.py."""

import sys

from radar.cli import main

if __name__ == "__main__":
    sys.exit(main())