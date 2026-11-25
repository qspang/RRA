"""Run an old experiment with its recorded outputs/<case> paths temporarily visible."""
from contextlib import contextmanager
import fcntl
import os
from pathlib import Path
import subprocess
import sys


@contextmanager
def legacy_paths(outputs):
    archive = outputs/'archive'
    created = []
    with (archive/'.replay.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            for group in ('runs', 'packages', 'logs'):
                for source in (archive/group).glob('*'):
                    link = outputs/source.name
                    if link.is_symlink() and link.resolve() == source.resolve():
                        continue
                    if link.exists() or link.is_symlink():
                        raise FileExistsError(f'历史入口与现有文件重名：{link}')
                    target = source.relative_to(outputs)
                    link.symlink_to(target, target_is_directory=source.is_dir())
                    created.append((link, str(target)))
            yield
        finally:
            for link, target in created:
                if link.is_symlink() and os.readlink(link) == target:
                    link.unlink()


if __name__ == '__main__':
    if len(sys.argv) < 2:
        sys.exit('用法：python tools/with_archived_outputs.py <历史命令> [参数...]')
    root = Path(__file__).resolve().parents[1]
    with legacy_paths(root/'outputs'):
        sys.exit(subprocess.run(sys.argv[1:], cwd=root).returncode)
