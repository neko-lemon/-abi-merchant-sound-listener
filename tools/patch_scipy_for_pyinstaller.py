# -*- coding: utf-8 -*-
"""Make the venv's scipy importable from a PyInstaller frozen build.

scipy.stats._distn_infrastructure ends with a module-level cleanup loop:

    for obj in [s for s in dir() if s.startswith('_doc_')]:
        exec('del ' + obj)
    del obj

Inside a PyInstaller-frozen module that block blows up with
    NameError: name 'obj' is not defined
while importing scipy.stats (reached from scipy.signal -> _peak_finding),
which kills the frozen exe at startup.  The equivalent helper form below
behaves identically.  Idempotent: run it after every requirements reinstall.
"""
import pathlib
import re
import sys

TARGET = pathlib.Path("scipy/stats/_distn_infrastructure.py")
PATTERN = re.compile(
    r"# clean up all the separate docstring elements, we do not need them anymore"
    r".*?del obj\r?\n",
    re.S,
)
REPLACEMENT = """# clean up all the separate docstring elements (patched for PyInstaller)
def _drop_docstring_help_globals():
    _g = globals()
    for _name in [k for k in list(_g.keys()) if k.startswith('_doc_')]:
        _g.pop(_name, None)


_drop_docstring_help_globals()
del _drop_docstring_help_globals
"""


def site_packages():
    for root in sys.path:
        cand = pathlib.Path(root) / TARGET
        if cand.is_file():
            return cand
    return None


def main():
    path = site_packages()
    if path is None:
        print("scipy not found in this interpreter; nothing to do")
        return 1
    text = path.read_text(encoding="utf-8")
    if "_drop_docstring_help_globals" in text:
        print("already patched:", path)
        return 0
    new_text, count = PATTERN.subn(REPLACEMENT, text)
    if count != 1:
        print("unexpected file shape (matches=%d): %s" % (count, path))
        return 2
    compile(new_text, str(path), "exec")  # syntax check before writing
    path.write_text(new_text, encoding="utf-8")
    print("patched:", path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
