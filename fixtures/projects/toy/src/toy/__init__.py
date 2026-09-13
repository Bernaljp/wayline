"""The toy project's own package: `generate`, `train`, and `eval` (Implementation Decisions 14).

Kept dependency-light on purpose: `generate` and `eval` are stdlib only, so the suite can call them
with the same interpreter that runs `python -m unittest`. `train` is the one module that needs
torch, and it is only ever run through the tools venv (`wayline tools install`) or on the GPU live.
"""
