### packages/api/src/app/services/indexing/incremental/scripts/__init__.py

```diff

deleted file mode 100644
index f8b2d9a..0000000
--- a/packages/api/src/app/services/indexing/incremental/scripts/__init__.py
+++ /dev/null
@@ -1,13 +0,0 @@
    2       -"""In-sandbox incremental ingestion scripts (uploaded as files; host does not import).
    3       -
    4       -Uploaded by :func:`uploadIncrementalScripts` into the indexing sandbox
    5       -and never imported from this package on the host:
    6       -
    7       -- :mod:`incremental_ingestion` -- append-only LanceDB writer for a
    8       -  given list of repo-relative file paths.
    9       -
   10       -The sibling :mod:`chunking` module lives in the shared
   11       -``indexing/scripts/`` directory and is uploaded alongside this file;
   12       -the upload step guarantees both land in the same sandbox ``context/``
   13       -directory so the ``sys.path.insert`` sibling import works.
   14       -"""

```
