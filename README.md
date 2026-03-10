# OperaXN

**OPERAndo X-ray and Neutron diffraction data visualisation tool**

**OperaXN** is a Python-based desktop application for correlating, visualising and analysing *operando* diffraction data collected by laboratory XRD, synchrotron XRD or neutron diffraction sources. It also includes **Nexus Generator**, a companion tool for generating standardised NeXus (`.nxs`) files from raw electrochemical and diffraction data to facilitate easy data sharing in machine-readable formats.

## Features

### OperaXN
- Automated time-correlation of electrochemical (voltage and current) and diffraction datasets
- Simultaneous visualisation of X-ray (1D and 2D) and neutron diffraction data with electrochemical cycling
- Interactive GUI with scan navigation and visualisation controls
- Export publication-quality figures (PNG, PDF, SVG)
- Generate animated GIFs
- Currently supports `.dat`, `.xy`, `.edf`, `.hdf`, `.nxs`, `.txt`, and `.zip` files

### Nexus Generator
- Build Nexus files from raw diffraction and electrochemistry data
- Supports synchrotron, in-house, and neutron data types
- Embeds instrument metadata and time-correlated scan data
- Produces files compliant with the Nexus standard for seamless data sharing
  
## Installation

### From source

```bash
git clone https://github.com/matthewarlopowell/OperaXN.git
cd OperaXN
pip install .
```

### For development

```bash
pip install -e .
```

## Usage

### Launch OperaXN

```bash
operaxn
```

### Launch Nexus Generator

```bash
nexusgen
```

### Command line options

```bash
operaxn --help          # Show all options
operaxn --debug         # Enable debug logging
operaxn --check-deps    # Verify dependencies
```

## Time correlation

OperaXN correlates diffraction scans with electrochemistry data by timestamp. Two modes are available (selected at load time):

- **Absolute** — scan timestamps are matched directly to echem timestamps via nearest-neighbour lookup.
- **Relative** — both datasets are zeroed to their respective first timestamps and correlated by elapsed time. Useful when diffraction and echem clocks are not synchronised.

## Dependencies

- Python >= 3.9
- NumPy >= 1.20.0
- Pandas >= 2.0.0
- Matplotlib >= 3.4.0
- h5py >= 3.0.0
- Fabio >= 0.14.0
- OpenPyXL >= 3.0.0
- PSutil >= 5.8.0
- ImageIO >= 2.9.0

## Project Structure

```
OperaXN/
  bin/
    operaxn/       # Main visualisation application
    nexusgen/      # Nexus file generator
  examples/        # Example datasets
  pyproject.toml
  requirements.txt
```

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE) for details.

## AI Usage
This project was developed with the assistance of Claude (Anthropic).
