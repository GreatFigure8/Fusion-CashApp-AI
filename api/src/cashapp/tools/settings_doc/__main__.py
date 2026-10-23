"""``python -m cashapp.tools.settings_doc [--out PATH]``: print or write the settings reference."""

import argparse
from pathlib import Path

from cashapp.tools.settings_doc.render import render_settings_doc


def main() -> None:
    parser = argparse.ArgumentParser(description="Render docs/reference/settings.md.")
    parser.add_argument("--out", type=Path, default=None, help="Write here instead of stdout.")
    args = parser.parse_args()
    text = render_settings_doc()
    if args.out is None:
        print(text, end="")
    else:
        args.out.write_text(text, encoding="utf-8", newline="\n")


main()
