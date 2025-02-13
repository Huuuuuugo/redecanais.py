from setuptools import setup

setup(
    name='redecanais',
    version='1.0.0',
    entry_points={
        'console_scripts': [
            'redecanais = redecanais.redecanais:main',
        ],
    },
)
