"""Start the app: python -m grantbudget [data.db] [--port 8044]"""
import sys

from .fieldkit import main_cli
from .web import create_app

sys.exit(main_cli(create_app, "grant.db", 8044, sys.argv))
