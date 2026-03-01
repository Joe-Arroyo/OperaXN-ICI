"""
OperaXN - __init__.py
"""

from .config import APP_VERSION, APP_AUTHOR, SUPPORT_EMAIL

__version__ = APP_VERSION
__author__ = APP_AUTHOR
__email__ = SUPPORT_EMAIL
__license__ = "MIT"

from .config import (
    DataSourceType,
    DEFAULT_TWOD_YMIN_PERCENT,
    DEFAULT_TWOD_YMAX_PERCENT,
    DEFAULT_TWOD_XMIN_PERCENT,
    DEFAULT_TWOD_XMAX_PERCENT,
    CACHE_ENABLED,
    PARALLEL_PROCESSING,
    MAX_CACHE_SIZE_MB,
    EXPORT_DPI,
    FIGURE_DPI,
    OPERAXNTheme,
    DEBUG_MODE,
    APP_NAME,
    APP_COPYRIGHT,
    DOCUMENTATION_URL
)

from .gui import OPERAXN, UIState, VisualiserConfig

from .input import (
    process_paths,
    make_oned_arrays,
    make_twod_arrays,
    make_echem_arrays,
    get_correlated_data,
    FileType,
    DataType,
    TimeMethod
)

from .output import (
    plot_oned_data,
    plot_twod_data,
    plot_echem_data,
    plot_neutron_data,
    create_figure_layout,
    export_single_scan,
    clear_plot_cache,
    get_scan_time_positions,
    PlotConfig
)

from .dialog import (
    DataSourceSelectionDialog,
    PlotSettingsDialog,
    ExportOptionsDialog,
    GIFSettingsDialog,
    ProgressDialog
)

# Package metadata
__all__ = [
    # Main application
    'OPERAXN',

    # Configuration classes
    'VisualiserConfig',
    'PlotConfig',
    'OPERAXNTheme',

    # Data processing
    'process_paths',
    'make_oned_arrays',
    'make_twod_arrays',
    'make_echem_arrays',
    'get_correlated_data',
    'get_scan_time_positions',

    # Plotting
    'plot_oned_data',
    'plot_twod_data',
    'plot_echem_data',
    'plot_neutron_data',
    'create_figure_layout',
    'export_single_scan',
    'clear_plot_cache',

    # Dialogs
    'DataSourceSelectionDialog',
    'PlotSettingsDialog',
    'ExportOptionsDialog',
    'GIFSettingsDialog',
    'ProgressDialog',

    # Enums
    'DataSourceType',
    'UIState',
    'FileType',
    'DataType',
    'TimeMethod',

    # Version info
    '__version__',
    '__author__',
    '__email__',
    '__license__',

    # Application info
    'APP_NAME',
    'APP_COPYRIGHT',
    'DEBUG_MODE',

    # System info
    'CACHE_ENABLED',
    'PARALLEL_PROCESSING',
    'MAX_CACHE_SIZE_MB',
]


def get_version():
    """Get the current version of OperaXN."""
    return __version__


def get_system_info():
    """Get system information for debugging."""
    return {
        'app_name': APP_NAME,
        'version': __version__,
        'cache_enabled': CACHE_ENABLED,
        'parallel_processing': PARALLEL_PROCESSING,
        'max_cache_mb': MAX_CACHE_SIZE_MB,
        'debug_mode': DEBUG_MODE
    }
