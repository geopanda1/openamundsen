from distutils.util import convert_path
from setuptools import setup, find_packages


version_ns = {}
version_file = convert_path('openamundsen/_version.py')
with open(version_file) as f:
    exec(f.read(), version_ns)

setup(
    name='openamundsen',
    version=version_ns['__version__'],
    description='A spatially distributed snow and hydrological modeling framework',
    packages=find_packages(),
    include_package_data=True,
    scripts=['bin/openamundsen'],
    install_requires=[
        'loguru>=0.3.2',
        'munch>=2.5.0',
        'netCDF4>=1.5.2',
        'numba>=0.47.0',
        'numpy>=1.17.2',
        'pandas>=0.25.1',
        'pyproj>=2.4.0',
        'scipy>=1.2.0',
        'ruamel.yaml>=0.15.0',
        'rasterio>=1.1.0',
        'xarray>=0.14.0',
    ],
    extras_require={
        'liveview': [
            'PyQt5>=5.12',
            'pyqtgraph @ git+https://github.com/pyqtgraph/pyqtgraph@develop',
        ],
    },
)
