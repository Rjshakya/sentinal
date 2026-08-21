"""In-sandbox indexing scripts (uploaded as files; host does not import).

The two sibling files in this directory are shipped as bytes into the
indexing sandbox by :func:`uploadScriptsToSandbox` and never imported
from this package on the host:

- :mod:`chunking` -- tree-sitter chunking generator.
- :mod:`ingestion` -- LanceDB writer that consumes the generator.

The host's parser for the in-sandbox summary line lives in
:mod:`app.services.indexing.helpers`.
"""
