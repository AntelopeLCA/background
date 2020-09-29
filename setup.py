from setuptools import setup

requires = [
    "antelope_core",
    "scipy"
]

VERSION = '0.1.0'

setup(
    name="antelope_background",
    version=VERSION,
    author="Brandon Kuczenski",
    author_email="bkuczenski@ucsb.edu",
    license=open('LICENSE').read(),
    install_requires=requires,
    url="https://github.com/AntelopeLCA/background",
    summary="A background LCI implementation that performs a partial ordering of LCI databases",
    long_description=open('README.md').read(),
    packages=['antelope_background']
)
