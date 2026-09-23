"""`python -m sphinx -b html -E -a -q -d <doctrees> -w <warnings> <source> <out>`, answered by the fake."""

import argparse
import os
import sys

from tests.sphinx_fake import FakeSphinx

parser = argparse.ArgumentParser(prog="sphinx")
parser.add_argument("-b", dest="builder", required=True)
parser.add_argument("-E", action="store_true")
parser.add_argument("-a", action="store_true")
parser.add_argument("-q", action="store_true")
parser.add_argument("-d", dest="doctrees", required=True)
parser.add_argument("-w", dest="warnings", required=True)
parser.add_argument("source")
parser.add_argument("out")
options = parser.parse_args()
if options.builder != "html":
    sys.exit("the fake builds html only, asked for %s" % options.builder)
code, _ = FakeSphinx()(sys.executable, options.source, options.out, options.doctrees, options.warnings, dict(os.environ), 60)
sys.exit(code)
