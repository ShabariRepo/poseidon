# PyInstaller spec — builds a standalone `poseidon` binary (onedir: starts
# fast, and the whole folder is what gets tarred/signed). Run from the repo
# root: pyinstaller packaging/poseidon.spec
#
# The static UI ships as data files; uvicorn's dynamically-imported workers
# are declared as hidden imports (PyInstaller can't see them).

from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

root = Path(SPECPATH).parent

a = Analysis(
    [str(root / "packaging" / "launcher.py")],
    pathex=[str(root)],
    datas=[(str(root / "poseidon" / "static"), "poseidon/static")],
    hiddenimports=[
        *collect_submodules("uvicorn"),
        "poseidon",
    ],
    excludes=["tkinter", "test", "unittest"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="poseidon",
    console=True,  # v1: console app; menu-bar/tray launcher is the v2 nicety
    upx=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    name="poseidon",
)
