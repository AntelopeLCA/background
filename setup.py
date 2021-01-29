from setuptools import setup, find_packages

requires = [
    "antelope_core>=0.1.4",
    "scipy>=1.5",
    "numpy>=1.19"
]

"""
Change Log
0.1.4 - 2021-01-29 - bugfixes to get CI passing.  match consistent versions with other packages.

0.1.0 - 2021-01-06 - first published release
"""


VERSION = '0.1.4'

setup(
    name="antelope_background",
    version=VERSION,
    author="Brandon Kuczenski",
    author_email="bkuczenski@ucsb.edu",
    license="BSD 3-clause",
    install_requires=requires,
    url="https://github.com/AntelopeLCA/background",
    summary="A background LCI implementation that performs a partial ordering of LCI databases",
    long_description_content_type='text/markdown',
    long_description=open('README.md').read(),
    packages=find_packages()
)
