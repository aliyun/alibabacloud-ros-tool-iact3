# -*- coding: utf-8 -*-
import re
import setuptools
import sys


def _read_version():
    with open("iact3/__init__.py") as fp:
        match = re.search(r"^__version__\s*=\s*['\"]([^'\"]+)['\"]", fp.read(), re.M)
        if not match:
            raise RuntimeError("Unable to find __version__ in iact3/__init__.py")
        return match.group(1)


if sys.version_info >= (3, 11):
    import tomllib
else:
    try:
        import tomllib
    except ImportError:
        import tomli as tomllib


with open("pyproject.toml", "rb") as fp:
    pyproject = tomllib.load(fp)


project = pyproject["project"]
author = project["authors"][0]


with open("README.md") as fp:
    long_description = fp.read()


setuptools.setup(
    name=project["name"],
    version=_read_version(),
    description=project["description"],
    long_description=long_description,
    long_description_content_type="text/markdown",
    author=author["name"],
    author_email=author["email"],
    url=project["urls"]["Homepage"],
    keywords=project["keywords"],
    packages=setuptools.find_packages(exclude=["tests*", "build*", "dist*"]),
    python_requires=project["requires-python"],
    classifiers=project["classifiers"],
    entry_points={
        "console_scripts": [
            "iact3 = iact3.__main__:sync_run",
        ]
    },
    include_package_data=True,
)
