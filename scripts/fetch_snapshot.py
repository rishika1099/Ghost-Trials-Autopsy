"""At container start: if the snapshot isn't in the image and DATA_GCS_URI is set, download it from GCS.

The snapshot is committed when it is under GitHub's 100 MB limit, so usually this does nothing.
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ghost.config import DB_PATH  # noqa: E402

uri = os.environ.get("DATA_GCS_URI")
if DB_PATH.exists():
    print(f"snapshot: {DB_PATH} ({DB_PATH.stat().st_size / 1e6:.1f} MB)")
elif uri:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    from google.cloud import storage  # ships with google-cloud-aiplatform

    bucket, _, blob = uri.removeprefix("gs://").partition("/")
    storage.Client().bucket(bucket).blob(blob).download_to_filename(DB_PATH)
    print(f"snapshot: downloaded {uri}")
else:
    print("snapshot: missing, and DATA_GCS_URI is not set. Live tools still work.", file=sys.stderr)
