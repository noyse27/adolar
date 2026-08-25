# PyInstaller spec for AdolarRadio – single-file exe
# Build: pyinstaller adolar_radio.spec
#
# pywebview's Windows backend (webview.platforms.winforms) bridges to .NET
# via pythonnet -> clr_loader. clr_loader's ffi layer does `import cffi` and
# ships its own native ClrLoader.dll (under clr_loader/ffi/dlls/<arch>/) —
# PyInstaller's static analysis does not discover either on its own, which
# used to make the frozen exe fail at startup with
# "ModuleNotFoundError: No module named 'cffi'" even though cffi is
# installed and works fine when run from source. Collect them explicitly.

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules

block_cipher = None

clr_loader_datas, clr_loader_binaries = [], []
for pkg in ('clr_loader', 'cffi'):
    clr_loader_datas += collect_data_files(pkg)
    clr_loader_binaries += collect_dynamic_libs(pkg)

a = Analysis(
    ['adolar_radio.py'],
    pathex=[],
    binaries=clr_loader_binaries,
    datas=[
        ('logo.svg', '.'),
        ('logo.png', '.'),
    ] + clr_loader_datas,
    hiddenimports=[
        'webview',
        'webview.platforms.winforms',
        'clr',
        'cffi',
        '_cffi_backend',
        'pythonnet',
    ] + collect_submodules('clr_loader'),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='AdolarRadio',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='logo.ico',
    onefile=True,
)
