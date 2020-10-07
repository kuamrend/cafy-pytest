'''
Created on Feb 16, 2017

@author: Cafy
'''
# sample ./setup.py file
from setuptools import setup

from pytest_cafy.__version__ import __version__
#__version__ = "0.1.0"  

setup(
    name="pytest_cafy",
    packages=['pytest_cafy'],
    package_data={'pytest_cafy': ['resources/*']},
    author='Cafy',
    author_email='cafy-support@cisco.com',
    version=__version__,
    license="GPLv2",
    url='https://github.com/kuamrend/cafy-pytest',
    description='Pytest Cafy Plugin', 	
    install_requires=['pytest>=2.3', 'jinja2'],
    scripts=['bin/cafyrun'],
    # the following makes a plugin available to pytest
    entry_points={
        'pytest11': ['pytest_cafy = pytest_cafy.plugin']
    },
    # custom PyPI classifier for pytest plugins
    classifiers=[
        "Framework :: Pytest",
    ],
)
