"""Cython build configuration for TrueNAS Scale RPi.

Build with:
    python setup.py build_ext --inplace

Or for optimized release build:
    python setup.py build_ext --inplace --define CYTHON_OPTIMIZE
"""
import os
from setuptools import setup, Extension
from Cython.Build import cythonize
from Cython.Compiler import Options

try:
    import Cython
    HAS_CYTHON = True
except ImportError:
    HAS_CYTHON = False

# Source directories
TRUENAS_DIR = "truenas"

PURE_PYTHON_MODULES = [
    f"{TRUENAS_DIR}.server",
    f"{TRUENAS_DIR}.config",
    f"{TRUENAS_DIR}.rpc",
    f"{TRUENAS_DIR}.auth",
    f"{TRUENAS_DIR}.jobs",
    f"{TRUENAS_DIR}.query",
    f"{TRUENAS_DIR}.subscriptions",
    f"{TRUENAS_DIR}.modules.core",
    f"{TRUENAS_DIR}.modules.system",
    f"{TRUENAS_DIR}.modules.storage",
    f"{TRUENAS_DIR}.modules.network",
    f"{TRUENAS_DIR}.modules.service",
    f"{TRUENAS_DIR}.modules.sharing",
    f"{TRUENAS_DIR}.modules.alert",
    f"{TRUENAS_DIR}.modules.filesystem",
    f"{TRUENAS_DIR}.modules.users",
    f"{TRUENAS_DIR}.modules.app",
    f"{TRUENAS_DIR}.modules.vm",
    f"{TRUENAS_DIR}.modules.dataprotection",
    f"{TRUENAS_DIR}.modules.misc",
    f"{TRUENAS_DIR}.backends.linux",
    f"{TRUENAS_DIR}.backends.zfs",
    f"{TRUENAS_DIR}.backends.config_store",
    f"{TRUENAS_DIR}.shell.terminal",
]

Extensions = []

if HAS_CYTHON:
    Options.annotate = False
    Options.fast_fail = True

    compiler_directives = {
        "language_level": "3",
        "boundscheck": False,
        "wraparound": False,
        "initializedcheck": False,
        "nonecheck": False,
        "optimize.use_switch": True,
    }

    Extensions = [
        Extension(
            module.replace(".", os.sep),
            [module.replace(".", os.sep) + ".py"],
        )
        for module in PURE_PYTHON_MODULES
        if os.path.exists(module.replace(".", os.sep) + ".py")
    ]

    extensions = cythonize(
        Extensions,
        compiler_directives=compiler_directives,
        nthreads=os.cpu_count() or 4,
    )
else:
    extensions = []
    print(
        "WARNING: Cython not found. "
        "Install with: pip install cython"
    )
    print("Falling back to pure Python mode.")

setup(
    name="truenas-scale-rpi",
    version="0.1.0",
    description="TrueNAS Scale Backend for Raspberry Pi",
    author="TrueNAS RPi Project",
    packages=[
            "truenas",
            "truenas.modules",
            "truenas.backends",
            "truenas.shell",
        ],
    ext_modules=extensions,
    zip_safe=False,
    python_requires=">=3.10",
    install_requires=[
        "websockets>=12.0",
        "aiohttp>=3.9",
        "orjson>=3.9",
        "psutil>=5.9",
        "bcrypt>=4.1",
    ],
    entry_points={
        "console_scripts": [
            "truenas-rpi=truenas.server:main",
        ],
    },
)
