"""
stdlib types 代理模块
======================
此文件名为 types.py，会遮蔽 Python 标准库的 types 模块。
为避免循环导入，本文件通过 __getattr__ 透明代理到真实的 stdlib types。

ERP 自定义类型请从 app_types.py 导入，不要在此文件添加任何类定义。
"""
import sys as _sys
import os as _os

_STDLIB_TYPES = None


def _load_stdlib_types():
    """加载真实的 stdlib types 模块（跳过本文件）"""
    global _STDLIB_TYPES
    if _STDLIB_TYPES is not None:
        return _STDLIB_TYPES

    import importlib.util as _iu

    _this = _os.path.abspath(__file__)
    for _p in _sys.path:
        if not _p:
            continue
        _candidate = _os.path.join(_p, "types.py")
        if not _os.path.isfile(_candidate):
            continue
        if _os.path.abspath(_candidate) == _this:
            continue
        # 找到真实的 stdlib types.py
        _spec = _iu.spec_from_file_location("__stdlib_types__", _candidate)
        _mod = _iu.module_from_spec(_spec)  # type: ignore[arg-type]
        _spec.loader.exec_module(_mod)  # type: ignore[union-attr]
        _STDLIB_TYPES = _mod
        # 替换 sys.modules['types'] 为真实模块，后续导入不再经过本文件
        _sys.modules["types"] = _mod
        return _mod

    return None


def __getattr__(name: str):
    """代理未找到的属性到 stdlib types 模块"""
    mod = _load_stdlib_types()
    if mod is not None and hasattr(mod, name):
        return getattr(mod, name)
    raise AttributeError(f"module 'types' has no attribute {name!r}")
