"""Allow running as: python -m mempalace_code"""

from .cli import _one_shot_main

# Name the command, not the file: argparse would otherwise report "__main__.py".
_one_shot_main(prog="mempalace-code")
