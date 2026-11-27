"""Stage an authenticated ZIP in a fresh directory outside the live tree."""

from contextlib import contextmanager
from io import BytesIO
from pathlib import Path
import shutil
import stat
import tempfile
import zipfile

from xbot.services.release_signature import verify_release


@contextmanager
def staged_release(item, payload, public_key, parent: Path):
    if len(payload) > 128 << 20:
        raise ValueError('发行包过大')
    verify_release(item, payload, public_key)
    with tempfile.TemporaryDirectory(dir=parent) as directory, zipfile.ZipFile(BytesIO(payload)) as archive:
        root = Path(directory)
        entries = archive.infolist()
        if not entries or len(entries) > 50000 or sum(e.file_size for e in entries) > 512 << 20:
            raise ValueError('发行包展开规模无效')
        for entry in entries:
            parts = entry.filename.removesuffix('/').split('/')
            mode = stat.S_IFMT(entry.external_attr >> 16)
            if (len(entry.filename) > 1024 or any(p in {'', '.', '..'} for p in parts)
                    or any(c in entry.filename for c in ('\\', ':', '\0'))
                    or mode not in {0, stat.S_IFDIR if entry.is_dir() else stat.S_IFREG}):
                raise ValueError('发行包路径无效')
            path = root.joinpath(*parts)
            if entry.is_dir():
                path.mkdir(parents=True, exist_ok=True)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(entry) as source, path.open('xb') as target:
                    shutil.copyfileobj(source, target)
        yield root
