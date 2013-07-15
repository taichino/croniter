# -*- coding: utf-8 -*-
from setuptools import setup

__version__, __doc__, __license__, __author__ = None, None, None, None
# get __version__, __doc__, __license__, __author__

exec(open("croniter/_release.py").read())

setup(
    packages         = ('croniter',),
    name             = 'croniter',
    version          = __version__,
    py_modules       = ['croniter', 'croniter_test'],
    description      = 'croniter provides iteration for datetime object with cron like format',
    long_description = __doc__,
    author           = __author__,
    author_email     = 'taichino@gmail.com',
    url              = 'http://github.com/taichino/croniter',
    keywords         = 'datetime, iterator, cron',
    install_requires = ["python-dateutil"],
    license          = __license__,
    classifiers      = ["Development Status :: 4 - Beta",
                        "Intended Audience :: Developers",
                        "License :: OSI Approved :: MIT License",
                        "Operating System :: POSIX",
                        "Programming Language :: Python",
                        "Topic :: Software Development :: Libraries :: Python Modules"]
)
