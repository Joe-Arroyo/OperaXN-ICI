# OperaXN

**OPERAndo X-ray and Neutron diffraction data visualisation tool**

OperaXN is a Python desktop application for visualising and analysing operando diffraction data from synchrotron, in-house, and neutron sources. It also includes **nexusgen**, a companion tool for generating standardised NeXus (`.nxs`) files from raw experimental data.

## Features

### OperaXN
- Visualise 1D and 2D X-ray and neutron diffraction patterns
- Overlay electrochemistry data with time-correlated diffraction scans
- Interactive GUI with scan navigation, cropping, and intensity controls
- Export publication-quality figures (PNG, PDF, SVG)
- Generate animated GIFs of diffraction sequences
- Supports `.dat`, `.xy`, `.edf`, `.hdf`, `.nxs`, `.txt`, and `.zip` files

### Nexus Generator
- Build Nexus files from raw diffraction and electrochemistry data
- Supports synchrotron, in-house, and neutron source types
- Embeds instrument metadata and time-correlated scan data
- Produces files compliant with the Nexus standard for seemless data sharing
  
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

### Launch the visualiser

```bash
operaxn
```

### Launch the NeXus file generator

```bash
nexusgen
```

### Command line options

```bash
operaxn --help          # Show all options
operaxn --debug         # Enable debug logging
operaxn --no-splash     # Skip splash screen
operaxn --check-deps    # Verify dependencies
operaxn --info          # Show configuration
```

## Preffered data formats

### In-House

```bash
...
```

### Synchrotron

```bash
...
```

### Neutron

```bash
...
```

### Echem

```bash
...
```

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
  tests/
    operaxn/
    nexusgen/
  pyproject.toml
  requirements.txt
```

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE) for details.
