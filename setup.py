# -*- coding: utf-8 -*-
import setuptools

with open("requirements.txt") as fp:
    requirements = fp.read().splitlines()


with open("README.md") as fp:
    long_description = fp.read()


setuptools.setup(
    name="alibabacloud-ros-iact3",
    version="0.1.12",

    description="Iact3 is a tool that tests Terraform and ROS(Resource Orchestration Service) templates.",
    long_description=long_description,
    long_description_content_type="text/markdown",

    author="AlibabaCloud",
    packages=[
        "iact3",
        "iact3.cli_modules",
        "iact3.plugin",
        "iact3.report",
        "iact3.testing"
    ],

    install_requires=requirements,

    python_requires=">=3.7",
    classifiers=[
        "Development Status :: 2 - Pre-Alpha",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: Apache Software License",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Topic :: Software Development :: Libraries",
        "Topic :: Software Development :: Testing",
        "Operating System :: POSIX :: Linux",
        "Operating System :: MacOS :: MacOS X ",
    ],
    entry_points={
        "console_scripts": [
            "iact3 = iact3.__main__:sync_run",
        ]
    },
    include_package_data=True
)
