"""A `sphinx` package that is not Sphinx: `python -m sphinx -b html ...` answered by `tests.sphinx_fake`.

With this directory on `PYTHONPATH`, `wayline.docs.run_sphinx` runs the real subprocess it runs on a
project, `import sphinx` probe included, and the argv it builds is parsed here the way Sphinx parses it.
"""

__version__ = "0.0.0-fake"
