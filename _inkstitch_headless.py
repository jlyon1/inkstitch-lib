"""
Import this before importing anything from lib.extensions or lib.elements to
run Ink/Stitch headlessly without wxPython installed.

wxPython has no prebuilt wheel for this Python/platform and isn't worth a
from-source build (needs system GTK dev headers) just to get a batch
converter working -- Ink/Stitch only actually needs it for GUI dialogs
(About, the tartan palette editor, the sew-stack layer editor, the stitch
simulator) that a script like this never opens. Three patches, applied in
order:

1. lib.extensions's __init__.py eagerly imports every extension, including
   About (which needs wx) -- stub it with a module whose __path__ points at
   the real directory, so `from lib.extensions.output import Output` still
   resolves the real file, it just skips the package's own eager imports.
2. Same idea for lib.gui, which lib/update.py pulls in for an "update this
   old-version SVG?" dialog we'll never trigger (we always write
   current-version inkstitch-metadata ourselves).
3. wx itself: a meta path finder intercepts any "wx" or "wx.x.y" import and
   hands back a permissive fake -- usable as a base class, a constructor
   call, a bare constant, or chained further attribute access. New wx.*
   submodule imports kept surfacing one at a time (wx.html, wx.lib.intctrl,
   ...) as deeper Ink/Stitch features were touched, so this catches all of
   them rather than needing a new entry per submodule discovered.
"""

import importlib.abc
import importlib.util
import os
import sys
import types

_HERE = os.path.dirname(os.path.abspath(__file__))


def _stub_package(dotted_name, real_subpath):
    stub = types.ModuleType(dotted_name)
    stub.__path__ = [os.path.join(_HERE, *real_subpath)]
    sys.modules.setdefault(dotted_name, stub)


_stub_package("lib.extensions", ["lib", "extensions"])
_stub_package("lib.gui", ["lib", "gui"])


class _WxMeta(type):
    def __getattr__(cls, name):
        return _WxAny


class _WxAny(metaclass=_WxMeta):
    def __init__(self, *args, **kwargs):
        pass

    def __getattr__(self, name):
        return _WxAny()

    def __call__(self, *args, **kwargs):
        return _WxAny()


class _WxLoader(importlib.abc.Loader):
    def create_module(self, spec):
        mod = types.ModuleType(spec.name)
        mod.__path__ = []  # looks like a package, so wx.sub.sub also resolves
        mod.__getattr__ = lambda name: _WxAny
        return mod

    def exec_module(self, module):
        pass


class _WxFinder(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path, target=None):
        if fullname == "wx" or fullname.startswith("wx."):
            return importlib.util.spec_from_loader(fullname, _WxLoader())
        return None


sys.meta_path.insert(0, _WxFinder())

if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
