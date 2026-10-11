"""Publish staged files together; restore previous files on ordinary failures."""
import json
import os
from pathlib import Path
import shutil
import tempfile


def publish_batch(files, *, overwrite=False):
    files = [(Path(source),Path(destination)) for source,destination in files]
    if not files:return
    if len({p.resolve() for _,p in files})!=len(files):
        raise ValueError('Duplicate batch destinations')
    recovery = Path(tempfile.mkdtemp(prefix='.pdf2ai-recovery-',dir=files[0][1].parent))
    entries = []
    published = []
    retain_recovery = False
    try:
        # Back up everything before publishing the first file.
        for index,(source,destination) in enumerate(files):
            if not source.is_file() or destination.is_dir():
                raise ValueError('Batch publication requires files')
            exists = os.path.lexists(destination)
            if exists and not overwrite:raise FileExistsError(str(destination))
            backup = recovery/str(index) if exists else None
            if backup is not None:shutil.copy2(destination,backup,follow_symlinks=False)
            entries.append((source,destination,backup))
        (recovery/'manifest.json').write_text(json.dumps([
            {'destination':str(p.absolute()),'backup':str(b) if b is not None else None}
            for _,p,b in entries],ensure_ascii=False,indent=2),encoding='utf-8')
        for source,destination,backup in entries:
            if overwrite:os.replace(source,destination)
            else:os.link(source,destination)  # Reject files created after preflight.
            published.append((destination,backup))
    except BaseException:
        failures = []
        for destination,backup in reversed(published):
            try:
                if backup is None:destination.unlink()
                else:os.replace(backup,destination)
            except OSError as error:failures.append(f'{destination}: {error}')
        if failures:
            retain_recovery = True
            raise RuntimeError('出力の復元に失敗しました。バックアップを保持しています: '
                               +str(recovery)+'\n'+'\n'.join(failures))
        raise
    finally:
        if not retain_recovery:shutil.rmtree(recovery,ignore_errors=True)
