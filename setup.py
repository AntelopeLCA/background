from setuptools import setup, find_packages

requires = [
    "antelope_core>=0.2.1",
    "scipy>=1.5",
    "numpy>=1.19"
]

"""
Change Log
0.2.1 - 2023-04-10 - xdb passes benchmarks.
                     sys_lci running both locally and remotely.

0.2.0 - 2023-04-06 - Redefine sys_lci to omit spurious node argument. sync with virtualize branches upstream.
                     TODO: get rid of tail recursion in background Tarjan engine

0.1.8 - 2022-04-08 - version bump release to match core 0.1.8
 - Normalize how contexts are serialized and deserialized
 - add 'emitters' API route
 - preferred provider catch-all config
 - rename bg ordering file suffix to '.ordering.json.gz' and expose as a constant

0.1.6 - 2021-03-09 - compartment manager rework -> pass contexts as tuples
0.1.5 - 2021-02-05 - bump version to keep pace with antelope_core 
0.1.4 - 2021-01-29 - bugfixes to get CI passing.  match consistent versions with other packages.

0.1.0 - 2021-01-06 - first published release
"""


VERSION = '0.2.1'

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
