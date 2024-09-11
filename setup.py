from setuptools import setup, find_packages

VERSION = '0.2.7'

requires = [
    "antelope_core>=0.2.7",
    "scipy>=1.5",
    "numpy>=1.19"
]

"""
Change Log
0.2.7   2024-09-10 - correct directions of dependencies for treatment processes 
                     enable quell_biogenic_co2 on deep_lcia()
                     couple of bugs on context + index handling
                      
0.2.6.2 2024-06-11 - add deep_lcia()

0.2.6   2024-06-06 - factor out BackgroundLayer in preparation for dynamic background. 
 
0.2.4.1 2024-04-24 - refactor recursion out of Tarjan algorithm; write LciTester
                     depends on antelope_core 0.2.4.1 for search pagination

0.2.4 - 2024-04-17 - Remove antelope.ExteriorFlow in favor of antelope.models.ExteriorFlow

0.2.3 - 2024-03-21 - Correct dependencies

0.2.2 - 2024-03-12 - termination test; changed some exceptions

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
