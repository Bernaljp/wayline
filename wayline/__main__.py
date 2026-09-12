"""`python -m wayline` is the same command as `bin/wayline`."""

import sys

from wayline.cli import main

if __name__ == "__main__":
    sys.exit(main())
