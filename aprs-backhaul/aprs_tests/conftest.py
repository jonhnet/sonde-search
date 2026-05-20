import os
import sys

# Make `lib`, `pi`, `cloud` importable as top-level packages
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
# And make sibling tests/ modules importable by name (e.g. `helpers`).
HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
