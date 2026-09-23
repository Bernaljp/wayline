import os
import sys

sys.path.insert(0, os.path.abspath("../src"))

project = "tinydocs"
extensions = ["sphinx.ext.autodoc", "sphinx.ext.napoleon"]
html_theme = "alabaster"
