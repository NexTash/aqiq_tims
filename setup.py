from setuptools import setup, find_packages

with open("requirements.txt") as f:
	install_requires = f.read().strip().split("\n")

# get version from __version__ variable in aqiq_tims/__init__.py
from aqiq_tims import __version__ as version

setup(
    name="aqiq_tims",
    version=version,
    description="KRA TIMS Integration for ERPNext",
    author="RONOH",
    author_email="ronoelisha625@gmail.com",
    packages=find_packages(),
    zip_safe=False,
    include_package_data=True,
    install_requires=[]
)
