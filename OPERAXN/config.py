"""
Configuration Module for OPERAXN
"""

import multiprocessing
import os
import platform
import tkinter as tk
from enum import Enum

# ============================================================================
# Debug Mode
# ============================================================================

DEBUG_MODE = os.environ.get("XRD_DEBUG", "0") == "1"
LOG_LEVEL = "DEBUG" if DEBUG_MODE else "INFO"
LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
LOG_FILE = "OPERAXN.log" if DEBUG_MODE else None
ENABLE_PERFORMANCE_MONITORING = DEBUG_MODE
PERFORMANCE_LOG_THRESHOLD_MS = 1000


# ============================================================================
# Data Source Types
# ============================================================================

class DataSourceType(Enum):
    """Types of data sources."""
    SYNCHROTRON = "synchrotron"
    INHOUSE = "inhouse"
    NEUTRON = "neutron"


# ============================================================================
# Theme Configuration
# ============================================================================

class OPERAXNTheme:
    """Centralised theme configuration for the entire application."""

    COLORS = {
        'bg_primary': '#1a1f2e',
        'bg_secondary': '#2c3445',
        'bg_tertiary': '#3a4556',
        'accent_primary': '#00d4ff',
        'accent_secondary': '#4ecdc4',
        'accent_hover': '#00a8cc',
        'danger': '#ff6b6b',
        'success': '#51cf66',
        'warning': '#ffd43b',
        'text_primary': '#ffffff',
        'text_secondary': '#a0a8b8',
        'text_dim': '#6c7583',
        'border': '#404859',
        'canvas_bg': '#242938',
        'input_bg': '#2c3445',
        'button_bg': '#00d4ff',
        'button_text': '#1a1f2e',
        'button_hover': '#00a8cc',
        'disabled_bg': '#3a4556',
        'disabled_text': '#6c7583'
    }

    FONTS = {
        'title': ('Segoe UI', 12, 'bold'),
        'heading': ('Segoe UI', 11, 'bold'),
        'body': ('Segoe UI', 10),
        'small': ('Segoe UI', 9),
        'button': ('Segoe UI', 10, 'bold'),
        'mono': ('Consolas', 10)
    }

    PADDING = {
        'small': 5,
        'medium': 10,
        'large': 15
    }

    BUTTON_CONFIG = {
        'relief': tk.FLAT if 'tk' in dir() else 'flat',
        'cursor': 'hand2',
        'padx': 12,
        'pady': 4
    }


# ============================================================================
# Performance Settings
# ============================================================================

# Cache and Processing
CACHE_ENABLED = True
MAX_CACHE_SIZE_MB = 1000
PARALLEL_PROCESSING = True
MAX_WORKERS = min(multiprocessing.cpu_count(), 8)
BATCH_SIZE = 20

# Display Quality
SYNCHROTRON_MAX_DISPLAY_SIZE = 4096  # 2048 recommended
FIGURE_DPI = 95
EXPORT_DPI = 300
INTERPOLATION_METHOD = "bilinear"

# Data Processing
LARGE_IMAGE_THRESHOLD = 2_000_000
INTENSITY_SAMPLE_SIZE = 20_000

# Plot Appearance
COLORMAP = "YlGnBu_r"
LINE_WIDTH = 1.5
GRID_ALPHA = 0.3
PLOT_UPDATE_DELAY_MS = 50

# Plot Font Settings
PLOT_FONTS = {
    'title': 12,
    'label': 10,
    'tick': 10
}
TITLE_FONT_SIZE = PLOT_FONTS['title']
LABEL_FONT_SIZE = PLOT_FONTS['label']
TICK_FONT_SIZE = PLOT_FONTS['tick']

# Cropping Defaults
DEFAULT_TWOD_YMIN_PERCENT = 0
DEFAULT_TWOD_YMAX_PERCENT = 100
DEFAULT_TWOD_XMIN_PERCENT = 0
DEFAULT_TWOD_XMAX_PERCENT = 100

# GIF Settings
DEFAULT_GIF_FPS = 5
DEFAULT_GIF_DPI = 100
DEFAULT_GIF_LOOP = 0

# ============================================================================
# Window Sizes
# ============================================================================

WINDOW_SIZES = {
    'main': "1150x750",
    'upload': "400x150",
    'plot_settings': "400x375",
    'export_neutron': "400x375",
    'export_xrd': "400x425",
    'gif': "400x425",
    'progress': "300x100",
    'time': "400x200"
}

# ============================================================================
# Scientific Constants
# ============================================================================

XRAY_WAVELENGTH = 1.5406  # Cu K-alpha Angstroms
SYNCHROTRON_WAVELENGTH = 0.495
ECHEM_TIME_TOLERANCE = 300  # 5 minutes

# ============================================================================
# Export Settings
# ============================================================================

EXCEL_ENGINE = "openpyxl"
CSV_ENCODING = "utf-8"
SUPPORTED_IMAGE_FORMATS = [".png", ".pdf", ".svg", ".jpg", ".tiff"]
DEFAULT_IMAGE_FORMAT = ".png"

# ============================================================================
# File Type Settings
# ============================================================================

SUPPORTED_EXTENSIONS = {
    "xrd_1d": [".dat", ".xy"],
    "xrd_2d": [".edf", ".hdf"],
    "metadata": [".nxs"],
    "echem": [".txt"],
    "archive": [".zip"],
}

ALL_SUPPORTED_EXTENSIONS = []
for exts in SUPPORTED_EXTENSIONS.values():
    ALL_SUPPORTED_EXTENSIONS.extend(exts)

# ============================================================================
# Application Info
# ============================================================================

APP_NAME = "OPERAXN"
APP_VERSION = "1.0.0"
APP_AUTHOR = "Matthew Powell"
APP_COPYRIGHT = "2025"
DOCUMENTATION_URL = ""
SUPPORT_EMAIL = "matthewarlopowell@icloud.com"

# ============================================================================
# Platform Settings
# ============================================================================

PLATFORM = platform.system()

# ============================================================================
# Debug Output
# ============================================================================

if DEBUG_MODE:
    print("\n" + "=" * 60)
    print("OPERAXN Configuration")
    print("=" * 60)
    print(f"Platform: {PLATFORM}")
    print(f"CPU Cores: {multiprocessing.cpu_count()}")
    print(f"Max Workers: {MAX_WORKERS}")
    print(f"Cache Size: {MAX_CACHE_SIZE_MB} MB")
    print(f"Display Size: {SYNCHROTRON_MAX_DISPLAY_SIZE}×{SYNCHROTRON_MAX_DISPLAY_SIZE}")
    print(f"Interpolation: {INTERPOLATION_METHOD}")
    print("=" * 60 + "\n")
