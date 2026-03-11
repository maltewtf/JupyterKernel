# Jupyter kernel for SaC

This repository contains Jupyter-related tools for SaC.

## Prerequisites

- [sac2c and the standard library](https://sac-home.org/download:main)
- [Jupyter notebook](https://jupyter.org/install)

## Automatic installation

```bash
make install
```

## Manual installation

1. Get the Jupyter data directory path using `jupyter --data-dir`.
2. Within this director, create a new directory `kernels`.

```bash
mkdir -p <jupyter-path>/kernels
```

3. Copy the `sac` directory to the newly created `kernels` directory.

```bash
cp -r sac <jupyter-path>/kernels
```

4. Adjust the path in `<jupyter-path>/kernels/sac/kernel.json` to
   point to the location of the `kernel.py` file in this repository.

```bash
echo $PWD
$ <repository-path>
```

## Running Jupyter

To start the Jupyter notebook, run:

```bash
jupyter notebook
```

In the web interface you set the kernel language to SaC.
