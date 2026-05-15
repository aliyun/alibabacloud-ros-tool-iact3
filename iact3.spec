# -*- mode: python ; coding: utf-8 -*-
#
# PyInstaller spec for the iact3 standalone binary.
#
# Maintenance notes:
#   - Recommended PyInstaller version: 6.11.1 (see build.py).
#   - Add new top-level Alibaba Cloud SDK packages to `_direct_sdk_packages`
#     when iact3 begins importing them directly.
#   - Add transitive runtime-only deps (those PyInstaller cannot detect via
#     static analysis) to `_transitive_sdk_packages`.
#   - Add third-party libraries imported dynamically (e.g. inside report
#     generation) to the explicit `hiddenimports` block below.
#   - Standard library modules do NOT need to be listed; PyInstaller bundles
#     them automatically.
#   - Static data files must be declared in `datas=` and resolved at runtime
#     via `sys._MEIPASS` when `sys.frozen` is True.
#   - Runtime hooks live under `hooks/`; register them in `runtime_hooks=`.

import sys
from PyInstaller.utils.hooks import collect_submodules

# Packages directly imported by iact3
_direct_sdk_packages = [
    'alibabacloud_ros20190910',
    'alibabacloud_ecs20140526',
    'alibabacloud_vpc20160428',
    'alibabacloud_credentials',
    'alibabacloud_tea_openapi',
    'alibabacloud_tea_util',
    'Tea',
    'oss2',
]

# Transitive dependencies required at runtime
_transitive_sdk_packages = [
    'alibabacloud_openapi_util',
    'alibabacloud_gateway_spi',
    'aliyunsdkcore',
    'aliyunsdkkms',
]

hiddenimports = collect_submodules('iact3')
for _pkg in _direct_sdk_packages + _transitive_sdk_packages:
    hiddenimports += collect_submodules(_pkg)

hiddenimports += [
    'xml.dom.minidom',
    'configparser',
    'dataclasses_jsonschema',
    'cgi',
    'tabulate',
    'yattag',
    'aiofiles',
]

a = Analysis(
    ['iact3/__main__.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('iact3/report/html.css', 'iact3/report'),
    ],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=['hooks/rthook_six.py'],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='iact3',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=['*.dll', '*.dylib', '*.so'],
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
