"""Entry point for the open-source clone route: bin/dope runs this module."""
import sys

from .__main__ import main

if __name__ == '__main__':
    sys.exit(main(product='dobe', checkout=True))
