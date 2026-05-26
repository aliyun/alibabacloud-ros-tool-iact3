#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Build iact3 binary using PyInstaller and package as archive."""

import os
import platform
import shutil
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

from iact3 import __version__

PYINSTALLER_REQUIRED_VERSION = '6.11.1'
BUILD_VERSION = os.environ.get('IACT3_BUILD_VERSION', '').strip() or __version__


def main():
    root = Path(__file__).parent
    spec_file = root / 'iact3.spec'
    dist_dir = root / 'dist'
    build_dir = root / 'build'

    try:
        import PyInstaller
    except ImportError:
        print(
            f'Error: PyInstaller is required. Install with: '
            f'pip install pyinstaller=={PYINSTALLER_REQUIRED_VERSION}',
            file=sys.stderr,
        )
        sys.exit(1)

    if PyInstaller.__version__ != PYINSTALLER_REQUIRED_VERSION:
        print(
            f'Warning: PyInstaller {PyInstaller.__version__} detected; '
            f'recommended version is {PYINSTALLER_REQUIRED_VERSION}. '
            f'Build artifacts may differ from those produced by CI.',
            file=sys.stderr,
        )

    if build_dir.exists():
        shutil.rmtree(build_dir)
    if dist_dir.exists():
        shutil.rmtree(dist_dir)

    system = platform.system().lower()
    machine = _normalize_arch(platform.machine())

    print(f'Building iact3 on {system} {machine}...')
    subprocess.check_call([
        sys.executable, '-m', 'PyInstaller',
        str(spec_file),
        '--distpath', str(dist_dir),
        '--workpath', str(build_dir),
        '--clean',
        '--noconfirm',
    ])

    binary_name = 'iact3.exe' if system == 'windows' else 'iact3'
    binary_path = dist_dir / binary_name

    if not binary_path.exists():
        print('\nBuild failed: binary not found.', file=sys.stderr)
        sys.exit(1)

    size_mb = binary_path.stat().st_size / (1024 * 1024)
    print(f'\nBuild succeeded: {binary_path} ({size_mb:.1f} MB)')

    archive_path = _create_archive(dist_dir, binary_path, system, machine)
    archive_size_mb = archive_path.stat().st_size / (1024 * 1024)
    print(f'Archive created: {archive_path} ({archive_size_mb:.1f} MB)')

    version_file = dist_dir / 'version.txt'
    version_file.write_text(BUILD_VERSION)
    print(f'Version file created: {version_file}')


def _normalize_arch(machine):
    mapping = {
        'x86_64': 'amd64',
        'amd64': 'amd64',
        'i386': 'i386',
        'i686': 'i386',
        'aarch64': 'arm64',
        'arm64': 'arm64',
    }
    return mapping.get(machine.lower(), machine.lower())


def _create_archive(dist_dir, binary_path, system, machine):
    archive_name = f'iact3-{BUILD_VERSION}-{system}-{machine}'

    if system == 'windows':
        archive_path = dist_dir / f'{archive_name}.zip'
        with zipfile.ZipFile(archive_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            zf.write(binary_path, binary_path.name)
    else:
        archive_path = dist_dir / f'{archive_name}.tar.gz'
        with tarfile.open(archive_path, 'w:gz') as tf:
            tf.add(binary_path, arcname=binary_path.name)

    return archive_path


if __name__ == '__main__':
    main()
