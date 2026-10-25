"""Unpack Ubuntu LibreOffice into this project; never installs system packages."""
import argparse
from pathlib import Path
import subprocess


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--skip-download',action='store_true')
    args=parser.parse_args()
    base=Path(__file__).resolve().parents[1]/'.tools/office'
    archives=base/'debs';root=base/'root'
    (archives/'partial').mkdir(parents=True,exist_ok=True)
    if not args.skip_download:
        subprocess.run(['apt-get','--download-only','-o','Dir::Cache::archives='+str(archives),
                        '-o','Debug::NoLocking=1','install','--no-install-recommends','libreoffice-writer','-y'],check=True)
    files=sorted(archives.glob('*.deb'))
    if not files:
        raise RuntimeError('未找到LibreOffice下载包')
    root.mkdir(parents=True,exist_ok=True)
    for package in files:
        subprocess.run(['dpkg-deb','-x',str(package),str(root)],check=True)
    # Debian absolute symlinks need to resolve inside the unpacked root.
    for path in root.rglob('*'):
        if path.is_symlink():
            target=path.readlink()
            if target.is_absolute() and (root/str(target).lstrip('/')).exists():
                path.unlink();path.symlink_to(root/str(target).lstrip('/'))
    program=root/'usr/lib/libreoffice/program'
    config=program/'fundamentalrc'
    text=config.read_text()
    text=text.replace('file:///usr/lib/libreoffice',(root/'usr/lib/libreoffice').as_uri())
    text=text.replace('file:///etc/libreoffice/registry',(root/'usr/lib/libreoffice/share/.registry').as_uri())
    config.write_text(text)
    # Debian's package post-install normally populates registry/ and multiarch
    # UNO paths. Reproduce only the required user-space lookup paths.
    for name in ('unorc','bootstraprc'):
        path=program/name
        if path.exists():
            text=path.read_text().replace('file:///usr/lib/libreoffice',(root/'usr/lib/libreoffice').as_uri())
            text=text.replace('file:///etc/libreoffice/registry',(root/'usr/lib/libreoffice/share/.registry').as_uri())
            path.write_text(text)
    if (program/'unorc').exists():
        (root/'usr/lib/x86_64-linux-gnu/unorc').write_text((program/'unorc').read_text()
            .replace('${ORIGIN}',program.as_uri()).replace('$ORIGIN',program.as_uri()))
    print('LibreOffice root:',root)


if __name__=='__main__':
    main()
