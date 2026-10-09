import os
import tempfile

os.environ.setdefault("TDCM_DATA_DIR", tempfile.mkdtemp(prefix="tdcm-test-"))
