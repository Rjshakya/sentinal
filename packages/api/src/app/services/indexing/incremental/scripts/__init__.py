"""In-sandbox incremental ingestion scripts (uploaded as files; host does not import).

Uploaded by :func:`uploadIncrementalScripts` into the indexing sandbox
and never imported from this package on the host:

- :mod:`incremental_ingestion` -- append-only LanceDB writer for a
  given list of repo-relative file paths.

The sibling :mod:`chunking` module lives in the shared
``indexing/scripts/`` directory and is uploaded alongside this file;
the upload step guarantees both land in the same sandbox ``context/``
directory so the ``sys.path.insert`` sibling import works.
"""
