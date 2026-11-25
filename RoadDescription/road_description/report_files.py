"""Report filenames shared by the workbench and the local delivery directory."""
import os
from pathlib import Path
from uuid import uuid4


GROUPS = {
    'description': ('route_description', ['路径方案描述_联调样章']),
    'comparison': ('route_comparison', ['agents/route_comparison/路径方案比选']),
    'compliance': ('route_compliance', ['agents/route_compliance/upper/北方案_路径合规性分析',
                                       'agents/route_compliance/lower/南方案_路径合规性分析']),
    'assembly': ('assembly', ['agents/assembly/完整报告_路径描述_方案比选_南北方案合规分析']),
}

DELIVERY_NAMES = {
    'description': ['路径描述'],
    'comparison': ['路径方案比选'],
    'compliance': ['北方案合规分析', '南方案合规分析'],
    'assembly': ['完整报告'],
}


def publish_workbench_files(folder):
    """Point the local shortcut at a complete set; keep all provenance in the job."""
    folder = Path(folder)
    files = {}
    for group, (plugin, stems) in GROUPS.items():
        if not (folder/'output'/'agents'/plugin/'result.json').is_file():
            return False
        for stem, name in zip(stems, DELIVERY_NAMES[group]):
            for ext in ('.pdf', '.docx'):
                source = folder/'output'/(stem+ext)
                if not source.is_file():
                    return False
                files[name+ext] = source
    delivery = folder/'成稿'
    delivery.mkdir(exist_ok=True)
    for name, source in files.items():
        link = delivery/name
        target = os.path.relpath(source, delivery)
        if not link.is_symlink():
            link.symlink_to(target)
        elif os.readlink(link) != target:
            raise FileExistsError(link)
    parent = folder.parent.parent
    shortcut = parent/'最近成稿'
    if shortcut.exists() and not shortcut.is_symlink():
        raise FileExistsError(shortcut)
    pending = parent/('.最近成稿-'+uuid4().hex)
    pending.symlink_to(os.path.relpath(delivery, parent), target_is_directory=True)
    try:
        pending.replace(shortcut)
    finally:
        pending.unlink(missing_ok=True)
    return True
