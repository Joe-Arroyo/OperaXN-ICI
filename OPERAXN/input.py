"""
Input Module for Data Processing
"""

import logging
import re
import tempfile
import threading
import zipfile
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from functools import lru_cache
from typing import Callable, List, Optional, Tuple, Union, Any, Dict

import h5py
import numpy as np
import pandas as pd

from .config import *

try:
    import fabio

    FABIO_AVAILABLE = True
except ImportError:
    FABIO_AVAILABLE = False


# ============================================================================
# Logging Configuration
# ============================================================================

logger = logging.getLogger(__name__)


# ============================================================================
# Data Models and Enums
# ============================================================================

class FileType(Enum):
    """Enumeration of supported file types."""
    DAT = ".dat"
    EDF = ".edf"
    TXT = ".txt"
    HDF = ".hdf"
    NXS = ".nxs"
    XY = ".xy"
    ZIP = ".zip"


class DataType(Enum):
    """Types of scientific data."""
    ONED = "oned"
    TWOD = "twod"
    ECHEM = "echem"
    NEUTRON_META = "neutron_meta"
    NEUTRON_TOF = "neutron_tof"
    NEUTRON_D = "neutron_d"


class TimeMethod(Enum):
    """Time correlation methods."""
    ABSOLUTE = "absolute"
    RELATIVE = "relative"


@dataclass
class FileRecord:
    """Represents a processed file record."""
    path: str
    original_path: str
    oned: Optional[str] = None
    twod: Optional[str] = None
    echem: Optional[str] = None
    neutron_meta: Optional[str] = None
    neutron_files: Optional[Dict[str, Dict[str, str]]] = None
    timestamp: Optional[str] = None
    exposure_time: Optional[float] = None
    file_hash: Optional[str] = None


@dataclass
class Scan:
    """Represents a complete scan with all associated data."""
    scan_num: int
    oned: Optional[str] = None
    twod: Optional[str] = None
    echem: Optional[float] = None
    current: Optional[float] = None
    echem_timestamp: Optional[str] = None
    neutron_meta: Optional[str] = None
    neutron_files: Optional[Dict[str, Dict[str, str]]] = None
    timestamp: Optional[str] = None
    original_timestamp: Optional[str] = None
    exposure_time: Optional[float] = None
    oned_exposure: Optional[float] = None
    twod_exposure: Optional[float] = None
    neutron_start: Optional[str] = None
    neutron_end: Optional[str] = None
    timestamp_for_correlation: Optional[pd.Timestamp] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert scan to dictionary."""
        return {
            "scan_num": self.scan_num,
            "oned": self.oned,
            "twod": self.twod,
            "echem": self.echem,
            "current": self.current,
            "echem_timestamp": self.echem_timestamp,
            "neutron_meta": self.neutron_meta,
            "neutron_files": self.neutron_files,
            "timestamp": self.timestamp,
            "original_timestamp": self.original_timestamp,
            "exposure_time": self.exposure_time,
            "oned_exposure": self.oned_exposure,
            "twod_exposure": self.twod_exposure,
            "neutron_start": self.neutron_start,
            "neutron_end": self.neutron_end,
            "timestamp_for_correlation": self.timestamp_for_correlation
        }


# ============================================================================
# Cache Management
# ============================================================================

class FileCache:
    """Thread-safe file data cache."""

    def __init__(self, max_size_mb: int = MAX_CACHE_SIZE_MB):
        self.cache = {}
        self.max_size_bytes = max_size_mb * 1024 * 1024
        self.current_size = 0
        self.lock = threading.Lock()
        self.access_count = {}

    def get(self, key: str) -> Optional[Any]:
        """Get item from cache."""
        with self.lock:
            if key in self.cache:
                self.access_count[key] = self.access_count.get(key, 0) + 1
                return self.cache[key]
        return None

    def put(self, key: str, value: Any, size_bytes: int = None) -> None:
        """Put item in cache with size management."""
        with self.lock:
            if size_bytes is None:
                import sys
                size_bytes = sys.getsizeof(value)

            while self.current_size + size_bytes > self.max_size_bytes and self.cache:
                self._evict_lru()

            self.cache[key] = value
            self.current_size += size_bytes
            self.access_count[key] = 1

    def _evict_lru(self) -> None:
        """Evict least recently used item."""
        if not self.cache:
            return

        lru_key = min(self.access_count.keys(), key=lambda k: self.access_count.get(k, 0))

        if lru_key in self.cache:
            value = self.cache.pop(lru_key)
            import sys
            self.current_size -= sys.getsizeof(value)
            self.access_count.pop(lru_key, None)

    def clear(self) -> None:
        """Clear the cache."""
        with self.lock:
            self.cache.clear()
            self.access_count.clear()
            self.current_size = 0


# Global cache instance
_file_cache = FileCache()


# ============================================================================
# Data Readers
# ============================================================================

class DataReader(ABC):
    """Abstract base class for data readers with caching."""

    @abstractmethod
    def _read_impl(self, path: str) -> np.ndarray:
        """Implementation of file reading."""
        pass

    def read(self, path: str, use_cache: bool = True) -> np.ndarray:
        """Read data from file with optional caching."""
        if not use_cache or not CACHE_ENABLED:
            return self._read_impl(path)

        cache_key = self._get_cache_key(path)
        cached_data = _file_cache.get(cache_key)
        if cached_data is not None:
            return cached_data

        data = self._read_impl(path)
        _file_cache.put(cache_key, data)
        return data

    def _get_cache_key(self, path: str) -> str:
        """Generate cache key for file."""
        import os
        stat = os.stat(path)
        return f"{path}_{stat.st_size}_{stat.st_mtime}"


class DATReader(DataReader):
    """Enhanced DAT reader for both XRD and neutron data."""

    def __init__(self, data_type: str = "xrd"):
        super().__init__()
        self.data_type = data_type

    def _read_impl(self, path: str) -> np.ndarray:
        """Read DAT file as 2-column array."""
        try:
            # Try fast numpy loading first
            try:
                data = np.loadtxt(path, comments='#')
                if data.ndim == 1:
                    data = data.reshape(-1, 2)
                return data
            except (ValueError, IOError, OSError) as e:
                logger.debug(f"NumPy loadtxt failed for {path}: {e}")

            # Fallback to manual parsing
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()

            # Find data start (skip comments)
            data_start = 0
            for i, line in enumerate(lines):
                if not line.strip().startswith("#") and line.strip():
                    data_start = i
                    break

            # Parse data
            data = []
            for line in lines[data_start:]:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue

                parts = line.split()
                if len(parts) >= 2:
                    try:
                        x_val = float(parts[0])
                        y_val = float(parts[1])
                        data.append([x_val, y_val])
                    except ValueError:
                        continue

            if not data:
                file_type = "neutron" if self.data_type == "neutron" else "DAT"
                raise ValueError(f"No valid data found in {file_type} file: {path}")

            return np.array(data, dtype=float)

        except Exception as e:
            file_type = "neutron DAT" if self.data_type == "neutron" else "DAT"
            raise IOError(f"Error reading {file_type} file {path}: {e}")


class EDFReader(DataReader):
    """Reader for EDF files."""

    def _read_impl(self, path: str) -> np.ndarray:
        """Read EDF file as 2D array."""
        if not FABIO_AVAILABLE:
            raise ImportError("fabio is required to read EDF files")

        try:
            arr = np.asarray(fabio.open(path).data.astype(float))
            pos = arr > 0
            floor = float(arr[pos].min()) if pos.any() else 0.0
            return np.clip(arr, floor, None)
        except Exception as e:
            raise IOError(f"Error reading EDF file {path}: {e}")


class XYReader(DataReader):
    """Reader for XY files (synchrotron integrated data)."""

    def _read_impl(self, path: str) -> np.ndarray:
        """Read XY file as 2-column array."""
        try:
            data = np.loadtxt(path)
            if data.ndim == 1:
                data = data.reshape(-1, 2)
            return data
        except Exception as e:
            raise IOError(f"Error reading XY file {path}: {e}")


class HDFReader(DataReader):
    """Reader for HDF5 files with optional downsampling for display."""

    COMMON_DATA_PATHS = [
        '/entry/instrument/detector/data',
        '/entry1/instrument/detector/data',
        '/entry/data/data',
        '/entry1/data/data',
        '/entry/data',
        '/entry1/data',
        '/data',
    ]

    DETECTOR_SIZES = [
        (2880, 2881),  # Pixium detector
        (2048, 2048),
        (1024, 1024),
        (512, 512),
    ]

    def __init__(self):
        super().__init__()
        self.max_display_size = SYNCHROTRON_MAX_DISPLAY_SIZE
        self.downsample_enabled = True

    def _read_impl(self, path: str) -> np.ndarray:
        """Read HDF file as 2D array."""
        try:
            with h5py.File(path, 'r', swmr=True) as f:
                data = self._find_data_array(f)

                if data is None:
                    raise ValueError(f"No suitable data found in HDF file")

                data = self._process_data_shape(data)
                data = self._apply_floor_clipping(data)

                if self.downsample_enabled:
                    data = self._downsample_if_needed(data)

                return data
        except Exception as e:
            raise IOError(f"Error reading HDF file {path}: {e}")

    def _find_data_array(self, h5file: h5py.File) -> Optional[np.ndarray]:
        """Find the main data array in HDF file."""
        for path in self.COMMON_DATA_PATHS:
            if path in h5file:
                dataset = h5file[path]
                if dataset.size > 50_000_000:
                    return self._sample_large_dataset(dataset)
                else:
                    return np.array(dataset)

        # Search for largest dataset
        largest_dataset = None
        largest_size = 0

        def find_largest(name, obj):
            nonlocal largest_dataset, largest_size
            if isinstance(obj, h5py.Dataset):
                if obj.size > largest_size and obj.ndim in [2, 3]:
                    largest_size = obj.size
                    largest_dataset = name

        h5file.visititems(find_largest)

        if largest_dataset:
            dataset = h5file[largest_dataset]
            if dataset.size > 50_000_000:
                return self._sample_large_dataset(dataset)
            else:
                return np.array(dataset)

        return None

    def _sample_large_dataset(self, dataset: h5py.Dataset) -> np.ndarray:
        """Sample very large dataset for initial loading."""
        shape = dataset.shape

        if dataset.ndim == 3:
            data = dataset[0]
        else:
            data = dataset

        if data.size > 50_000_000:
            height, width = data.shape[-2:]
            step = max(1, int(np.sqrt(data.size / (2048 * 2048))))
            if dataset.ndim == 2:
                return dataset[::step, ::step]
            else:
                return dataset[0, ::step, ::step]

        return np.array(data)

    def _process_data_shape(self, data: np.ndarray) -> np.ndarray:
        """Process data array to ensure 2D shape."""
        if data.ndim == 3:
            return data[0]
        elif data.ndim == 1:
            return self._reshape_1d_data(data)
        elif data.ndim == 2:
            return data
        else:
            raise ValueError(f"Unsupported data shape: {data.shape}")

    def _reshape_1d_data(self, data: np.ndarray) -> np.ndarray:
        """Reshape 1D data to 2D based on known detector sizes."""
        for height, width in self.DETECTOR_SIZES:
            if data.size == height * width:
                return data.reshape((height, width))

        sqrt_size = int(np.sqrt(data.size))
        if sqrt_size * sqrt_size == data.size:
            return data.reshape((sqrt_size, sqrt_size))

        raise ValueError(f"Cannot determine shape for 1D data of size {data.size}")

    def _apply_floor_clipping(self, data: np.ndarray) -> np.ndarray:
        """Apply floor clipping to remove noise."""
        pos = data > 0
        if pos.any():
            floor = float(data[pos].min())
            return np.clip(data, floor, None)
        return data

    def _downsample_if_needed(self, data: np.ndarray) -> np.ndarray:
        """Downsample data if larger than max display size."""
        height, width = data.shape

        if height > self.max_display_size or width > self.max_display_size:
            return self._downsample_for_display(data)

        return data

    def _downsample_for_display(self, data: np.ndarray) -> np.ndarray:
        """Downsample data to fit within max display size."""
        height, width = data.shape

        scale_factor = max(
            height / self.max_display_size,
            width / self.max_display_size
        )

        if scale_factor <= 1:
            return data

        step = int(np.ceil(scale_factor))
        downsampled = data[::step, ::step]

        return downsampled


# ============================================================================
# File Processing
# ============================================================================

class FileProcessor:
    """Enhanced file processing for all data types with better error handling."""

    def __init__(self, progress_callback: Optional[Callable] = None,
                 data_source: DataSourceType = DataSourceType.INHOUSE):
        self.progress_callback = progress_callback
        self.data_source = data_source
        self.tempdir = None
        self.processed_files = set()
        self.synchrotron_grouper = SynchrotronFileGrouper()
        self.nexus_extractor = NexusMetadataExtractor()

    def __enter__(self):
        self.tempdir = tempfile.mkdtemp()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.tempdir and os.path.exists(self.tempdir):
            import shutil
            shutil.rmtree(self.tempdir, ignore_errors=True)

    def update_progress(self, message: str) -> None:
        """Update progress callback if available."""
        if self.progress_callback:
            self.progress_callback(message)

    def process_paths(self, selected_paths: List[str]) -> List[FileRecord]:
        """Process selected paths with improved logic."""
        all_files = self._collect_all_files(selected_paths)

        if not all_files:
            return []

        file_dict = {extracted: original for extracted, original in all_files}

        if self.data_source == DataSourceType.NEUTRON:
            records = self._process_neutron_files(all_files)
        elif self.data_source == DataSourceType.SYNCHROTRON:
            synchrotron_groups = self.synchrotron_grouper.group_files(file_dict)
            records = self._process_synchrotron_groups(synchrotron_groups)
        else:
            records = []

        # Process remaining files
        remaining_files = []
        for extracted_path, original_path in all_files:
            if extracted_path not in self.processed_files:
                remaining_files.append((extracted_path, original_path))

        if remaining_files:
            if PARALLEL_PROCESSING and len(remaining_files) > 20:
                remaining_records = self._process_remaining_files_parallel(remaining_files)
            else:
                remaining_records = self._process_remaining_files_sequential(remaining_files)
            records.extend(remaining_records)

        return records

    def _process_neutron_files(self, all_files: List[Tuple[str, str]]) -> List[FileRecord]:
        """Process neutron-specific files."""
        records = []

        for extracted_path, original_path in all_files:
            basename = os.path.basename(extracted_path)
            ext = os.path.splitext(basename)[1].lower()

            self.processed_files.add(extracted_path)

            record = FileRecord(
                path=extracted_path,
                original_path=original_path
            )
            records.append(record)

            if ext == '.txt':
                logger.debug(f"Added potential metadata file: {basename}")
            elif ext == '.dat':
                logger.debug(f"Added neutron data file: {basename}")

        logger.info(f"Processed {len(records)} neutron-related files")
        return records

    def _collect_all_files(self, selected_paths: List[str]) -> List[Tuple[str, str]]:
        """Collect all files from selected paths."""
        all_files = []

        for path in selected_paths:
            if os.path.isfile(path):
                ext = os.path.splitext(path)[1].lower()
                if ext == FileType.ZIP.value:
                    extracted = self._extract_zip_files(path)
                    all_files.extend(extracted)
                else:
                    all_files.append((path, path))
            elif os.path.isdir(path):
                dir_files = self._collect_directory_files(path)
                all_files.extend(dir_files)

        logger.info(f"Collected {len(all_files)} total files")
        return all_files

    def _extract_zip_files(self, zip_path: str) -> List[Tuple[str, str]]:
        """Extract relevant files from ZIP."""
        extracted = []

        try:
            with zipfile.ZipFile(zip_path, "r") as archive:
                members = archive.namelist()

                for member in members:
                    if (member.endswith("/") or
                            member.startswith("__MACOSX") or
                            member.startswith(".")):
                        continue

                    member_ext = os.path.splitext(member)[1].lower()
                    supported_exts = [ft.value for ft in FileType if ft != FileType.ZIP]

                    if member_ext in supported_exts:
                        extracted_path = archive.extract(member, self.tempdir)
                        original_path = os.path.join(zip_path, member)
                        extracted.append((extracted_path, original_path))

        except Exception as e:
            logger.error(f"Error extracting ZIP file: {e}")

        return extracted

    def _collect_directory_files(self, directory: str) -> List[Tuple[str, str]]:
        """Collect all relevant files from directory."""
        import os
        files = []

        for root, dirs, filenames in os.walk(directory):
            dirs[:] = [d for d in dirs if not d.startswith(".")]

            for filename in filenames:
                if filename.startswith("."):
                    continue

                file_path = os.path.join(root, filename)
                ext = os.path.splitext(file_path)[1].lower()

                if ext == FileType.ZIP.value:
                    extracted = self._extract_zip_files(file_path)
                    files.extend(extracted)
                elif ext in [ft.value for ft in FileType]:
                    files.append((file_path, file_path))

        return files

    def _process_synchrotron_groups(self, synchrotron_groups: Dict[str, Dict[str, str]]) -> List[FileRecord]:
        """Process all synchrotron groups."""
        records = []

        for base_id, file_group in synchrotron_groups.items():
            if 'nxs' in file_group:
                record = self._create_synchrotron_record(base_id, file_group)
                if record:
                    records.append(record)
                    for file_path in file_group.values():
                        self.processed_files.add(file_path)

        return records

    def _process_remaining_files_parallel(self, files: List[Tuple[str, str]]) -> List[FileRecord]:
        """Process remaining files in parallel."""
        chunk_size = max(BATCH_SIZE, len(files) // MAX_WORKERS)
        chunks = [files[i:i + chunk_size]
                  for i in range(0, len(files), chunk_size)]

        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            chunk_results = list(executor.map(self._process_remaining_chunk, chunks))

        records = []
        for chunk_records in chunk_results:
            records.extend(chunk_records)

        return records

    def _process_remaining_files_sequential(self, files: List[Tuple[str, str]]) -> List[FileRecord]:
        """Process remaining files sequentially."""
        return self._process_remaining_chunk(files)

    def _process_remaining_chunk(self, files: List[Tuple[str, str]]) -> List[FileRecord]:
        """Process a chunk of remaining files."""
        records = []
        for extracted_path, original_path in files:
            ext = os.path.splitext(extracted_path)[1].lower()
            if ext in [FileType.DAT.value, FileType.EDF.value, FileType.TXT.value]:
                self.processed_files.add(extracted_path)
                records.append(FileRecord(
                    path=extracted_path,
                    original_path=original_path
                ))
        return records

    def _create_synchrotron_record(self, base_id: str, file_group: Dict[str, str]) -> Optional[FileRecord]:
        """Create record for synchrotron file group."""
        nxs_path = file_group.get('nxs')
        if not nxs_path:
            return None

        metadata = self.nexus_extractor.extract(nxs_path)
        if not metadata:
            return FileRecord(
                path=nxs_path,
                original_path=nxs_path,
                oned=file_group.get('xy'),
                twod=file_group.get('hdf'),
                timestamp=None,
                exposure_time=None
            )

        return FileRecord(
            path=nxs_path,
            original_path=nxs_path,
            oned=file_group.get('xy'),
            twod=file_group.get('hdf'),
            timestamp=metadata.get('timestamp'),
            exposure_time=metadata.get('exposure_time')
        )


# ============================================================================
# File Classification
# ============================================================================

class FileClassifierBase(ABC):
    """Abstract base class for file classifiers."""

    @abstractmethod
    def classify(self, path: str) -> Tuple[Optional[str], Optional[str], Optional[float]]:
        """Classify file and extract metadata."""
        pass


class DATClassifier(FileClassifierBase):
    """Classifier for DAT files."""

    @lru_cache(maxsize=128)
    def classify(self, path: str) -> Tuple[Optional[str], Optional[str], Optional[float]]:
        """Classify DAT file and extract metadata."""
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                lines = [f.readline() for _ in range(30)]

            timestamp = None
            exposure_time = None

            for line in lines:
                if not line:
                    break

                line_lower = line.lstrip().lower()

                if line_lower.startswith("# date"):
                    raw = line.strip().split()[-1]
                    timestamp = raw.replace("T", " ")

                elif "exposuretime" in line_lower.replace(" ", ""):
                    try:
                        exposure_str = line.strip().split()[-1]
                        exposure_time = float(exposure_str)
                    except (ValueError, IndexError):
                        pass

            if timestamp:
                return DataType.ONED.value, timestamp, exposure_time

        except Exception as e:
            logger.error(f"Error classifying DAT file {path}: {e}")

        return None, None, None


class EDFClassifier(FileClassifierBase):
    """Classifier for EDF files."""

    @lru_cache(maxsize=128)
    def classify(self, path: str) -> Tuple[Optional[str], Optional[str], Optional[float]]:
        """Classify EDF file and extract metadata."""
        if not FABIO_AVAILABLE:
            return None, None, None

        try:
            image = fabio.open(path)

            raw_date = image.header.get("Date")
            timestamp = raw_date.replace("T", " ") if raw_date else None

            exposure_time = None
            for key in ["ExposureTime", "Exposure_Time", "ExpTime", "Exposure"]:
                if key in image.header:
                    try:
                        exposure_time = float(image.header[key])
                        break
                    except (ValueError, TypeError):
                        pass

            if timestamp:
                return DataType.TWOD.value, timestamp, exposure_time

        except Exception as e:
            logger.error(f"Error classifying EDF file {path}: {e}")

        return None, None, None


class TXTClassifier(FileClassifierBase):
    """Classifier for TXT files (electrochemistry data OR neutron metadata)."""

    ECHEM_KEYWORDS = ["time", "ecell", "voltage", "current", "i/", "ewe", "v/"]

    @lru_cache(maxsize=128)
    def classify(self, path: str) -> Tuple[Optional[str], Optional[str], Optional[float]]:
        """Classify TXT file as echem or neutron metadata."""
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                lines = []
                for i in range(10):
                    line = f.readline()
                    if not line:
                        break
                    lines.append(line)

            if not lines:
                return None, None, None

            first_line_lower = lines[0].lower()
            if any(keyword in first_line_lower for keyword in self.ECHEM_KEYWORDS):
                return DataType.ECHEM.value, None, None

            # Check for neutron metadata format
            weekdays = ["Sat", "Sun", "Mon", "Tue", "Wed", "Thu", "Fri"]
            is_neutron_logbook = False

            for line in lines[:5]:
                parts = line.strip().split('\t')

                if len(parts) >= 8:
                    if parts[0].isdigit() and len(parts[0]) == 5:
                        line_text = ' '.join(parts)
                        if any(weekday in line_text for weekday in weekdays):
                            is_neutron_logbook = True
                            break

            if is_neutron_logbook:
                logger.debug(f"Identified {path} as neutron metadata")
                return DataType.NEUTRON_META.value, None, None

            return None, None, None

        except Exception as e:
            logger.error(f"Error classifying TXT file {path}: {e}")
            return None, None, None


class FileClassificationManager:
    """Manages file classification and metadata extraction."""

    def __init__(self, data_source: DataSourceType = DataSourceType.INHOUSE):
        self.data_source = data_source
        self.classifiers = {
            FileType.DAT: DATClassifier(),
            FileType.EDF: EDFClassifier(),
            FileType.TXT: TXTClassifier()
        }

    def classify_files(self, df: pd.DataFrame) -> pd.DataFrame:
        """Classify files and extract metadata."""
        df = df.copy()

        if "exposure_time" not in df.columns:
            df["exposure_time"] = None
        if "neutron_meta" not in df.columns:
            df["neutron_meta"] = None

        for idx, row in df.iterrows():
            if row["oned"] is not None or row["twod"] is not None or row["neutron_meta"] is not None:
                continue

            path = row["path"]
            ext = os.path.splitext(path)[1].lower()

            if self.data_source == DataSourceType.NEUTRON:
                if ext == '.txt':
                    file_type = FileType(ext) if ext in [ft.value for ft in FileType] else None
                    if file_type and file_type in self.classifiers:
                        classifier = self.classifiers[file_type]
                        data_type, timestamp, exposure_time = classifier.classify(path)

                        if data_type == DataType.NEUTRON_META.value:
                            df.at[idx, "neutron_meta"] = path
                        elif data_type == DataType.ECHEM.value:
                            df.at[idx, "echem"] = path

                        if timestamp:
                            df.at[idx, "timestamp"] = timestamp
                        if exposure_time is not None:
                            df.at[idx, "exposure_time"] = exposure_time

            else:
                file_type = FileType(ext) if ext in [ft.value for ft in FileType] else None
                if file_type and file_type in self.classifiers:
                    classifier = self.classifiers[file_type]
                    data_type, timestamp, exposure_time = classifier.classify(path)

                    if data_type:
                        df.at[idx, data_type] = path
                        if timestamp:
                            df.at[idx, "timestamp"] = timestamp
                        if exposure_time is not None:
                            df.at[idx, "exposure_time"] = exposure_time

        return df


# ============================================================================
# Neutron Data Processing
# ============================================================================

class NeutronMetadataParser:
    """Parser for neutron metadata files."""

    def parse(self, path: str) -> Optional[pd.DataFrame]:
        """Parse neutron metadata file and return DataFrame."""
        try:
            logger.debug(f"Parsing neutron metadata file: {path}")

            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()

            if not lines:
                logger.debug("No lines found in file")
                return None

            data = []
            weekdays = ["Sat", "Sun", "Mon", "Tue", "Wed", "Thu", "Fri"]

            for line_num, line in enumerate(lines):
                parts = line.strip().split('\t')

                if len(parts) >= 8:
                    try:
                        scan_id = parts[0].strip()

                        if not (scan_id.isdigit() and len(scan_id) == 5):
                            continue

                        start_time = None
                        end_time = None

                        for i in range(len(parts) - 1):
                            if any(day in parts[i] for day in weekdays):
                                if not start_time:
                                    start_time = parts[i].strip()
                                elif not end_time:
                                    end_time = parts[i].strip()
                                    break

                        if start_time and end_time:
                            start_dt = pd.to_datetime(start_time, format='%a %b %d %H:%M:%S %Y')
                            end_dt = pd.to_datetime(end_time, format='%a %b %d %H:%M:%S %Y')

                            data.append({
                                "scan_id": scan_id,
                                "start_time": start_dt,
                                "end_time": end_dt,
                                "full_line": line.strip()
                            })

                            if len(data) <= 3:
                                logger.debug(f"Parsed scan {scan_id}: {start_dt} -> {end_dt}")

                    except (ValueError, IndexError) as e:
                        if line_num < 3:
                            logger.debug(f"Error parsing line {line_num}: {e}")
                        continue

            if data:
                logger.info(f"Successfully parsed {len(data)} entries")
                return pd.DataFrame(data)
            else:
                logger.debug("No valid entries found")

            return None

        except Exception as e:
            logger.error(f"Error parsing neutron metadata: {e}")
            return None


class NeutronFileGrouper:
    """Groups neutron files by scan ID and measurement type."""

    def group_neutron_files(self, file_list: List[str]) -> Dict[str, Dict[str, Dict[str, str]]]:
        """Group neutron files by scan ID and measurement type."""
        groups = {}

        logger.debug(f"Processing {len(file_list)} neutron files")

        for filepath in file_list:
            basename = os.path.basename(filepath)

            if not basename.endswith('.dat'):
                continue

            scan_info = self._extract_neutron_file_info(basename)

            if scan_info:
                scan_id = scan_info['scan_id']
                measurement_num = scan_info['measurement']
                data_type = scan_info['type']

                if scan_id not in groups:
                    groups[scan_id] = {}

                if measurement_num not in groups[scan_id]:
                    groups[scan_id][measurement_num] = {}

                groups[scan_id][measurement_num][data_type] = filepath

        logger.info(f"Grouped {len(groups)} scans")
        return groups

    def _extract_neutron_file_info(self, filename: str) -> Optional[Dict[str, str]]:
        """Extract scan ID, measurement number, and type from neutron filename."""
        name_no_ext = filename[:-4] if filename.endswith('.dat') else filename
        is_dspacing = '-d-' in name_no_ext or '_d_' in name_no_ext or name_no_ext.endswith('_d')

        try:
            pattern = r'(\d{5})-(\d)'
            match = re.search(pattern, name_no_ext)

            if match:
                scan_id = match.group(1)
                measurement_num = match.group(2)

                # Max 6 measurements
                if 1 <= int(measurement_num) <= 5:
                    return {
                        'scan_id': scan_id,
                        'measurement': measurement_num,
                        'type': 'd' if is_dspacing else 'tof'
                    }

            if '-' in name_no_ext:
                parts = name_no_ext.split('-')
                if len(parts) >= 2:
                    if parts[0].isdigit() and len(parts[0]) == 5:
                        scan_id = parts[0]
                        if parts[1] and parts[1][0].isdigit():
                            measurement_num = parts[1][0]
                            if 1 <= int(measurement_num) <= 5:
                                return {
                                    'scan_id': scan_id,
                                    'measurement': measurement_num,
                                    'type': 'd' if is_dspacing else 'tof'
                                }

            return None

        except (ValueError, IndexError):
            return None


# ============================================================================
# Specialised Processors
# ============================================================================

class EchemParser:
    """Parser for electrochemistry data files."""

    COLUMN_PATTERNS = {
        "time": ["time", "date"],
        "voltage": ["voltage", "v/", "ecell", "ewe"],
        "current": ["current", "i/"]
    }

    def parse(self, path: str) -> Optional[pd.DataFrame]:
        """Parse echem file and return DataFrame."""
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()

            if not lines:
                return None

            has_header = any(h in lines[0].lower() for h in
                             ["time", "ecell", "voltage", "current", "i"])

            if has_header:
                columns = self._detect_columns(lines[0])
                data_lines = lines[1:]
            else:
                columns = {"time": 0, "voltage": 1, "current": 2}
                data_lines = lines

            data = self._parse_data_lines(data_lines, columns)

            if data:
                return pd.DataFrame(data)

            return None

        except Exception:
            return None

    def _detect_columns(self, header_line: str) -> Dict[str, int]:
        """Detect column indices from header."""
        header_parts = [part.strip().lower() for part in header_line.strip().split("\t")]

        columns = {"time": 0, "voltage": 1, "current": 2}

        column_mapping = {}
        for col_type, patterns in self.COLUMN_PATTERNS.items():
            for pattern in patterns:
                column_mapping[pattern] = col_type

        for i, part in enumerate(header_parts):
            clean_part = part.replace("(", "").replace(")", "").replace("/", "").replace(" ", "")

            if clean_part in column_mapping:
                columns[column_mapping[clean_part]] = i
                continue

            for key, value in column_mapping.items():
                if key in part:
                    columns[value] = i
                    break

        return columns

    def _parse_data_lines(self, lines: List[str], columns: Dict[str, int]) -> List[Dict[str, Any]]:
        """Parse data lines into records."""
        data = []

        for line in lines:
            parts = line.strip().split("\t")
            max_idx = max(columns.values())

            if len(parts) <= max_idx:
                continue

            ts_str = parts[columns["time"]]
            if ts_str.startswith("1970/01/01"):
                continue

            try:
                timestamp = pd.to_datetime(ts_str, dayfirst=True)
            except (ValueError, TypeError):
                continue

            try:
                voltage = float(parts[columns["voltage"]])
            except (ValueError, IndexError):
                continue

            current = None
            if len(parts) > columns["current"]:
                try:
                    current = float(parts[columns["current"]])
                except (ValueError, IndexError):
                    pass

            data.append({
                "timestamp": timestamp,
                "echem_data": voltage,
                "current": current
            })

        return data


class SynchrotronFileGrouper:
    """Groups synchrotron files (NXS, HDF, XY) by scan ID."""

    def group_files(self, file_dict: Dict[str, str]) -> Dict[str, Dict[str, str]]:
        """Group related synchrotron files by scan ID."""
        groups = {}
        nxs_to_id = {}

        # First pass: identify NXS files and their IDs
        for extracted_path, original_path in file_dict.items():
            basename = os.path.basename(extracted_path)
            ext = os.path.splitext(basename)[1].lower()

            if ext == '.nxs':
                scan_id = self._extract_scan_id(basename)
                if scan_id:
                    nxs_to_id[extracted_path] = scan_id

        # Second pass: group all files
        for extracted_path, original_path in file_dict.items():
            basename = os.path.basename(extracted_path)
            ext = os.path.splitext(basename)[1].lower()

            if ext in ['.hdf', '.nxs', '.xy']:
                group_id = self._determine_group_id(basename, ext, nxs_to_id)

                if group_id:
                    if group_id not in groups:
                        groups[group_id] = {}

                    if ext == '.hdf':
                        groups[group_id]['hdf'] = extracted_path
                    elif ext == '.nxs':
                        groups[group_id]['nxs'] = extracted_path
                    elif ext == '.xy':
                        groups[group_id]['xy'] = extracted_path

        return groups

    def _extract_scan_id(self, filename: str) -> Optional[str]:
        """Extract scan ID from filename."""
        base_name = os.path.splitext(filename)[0]
        base_name = base_name.replace('_integration', '')

        match = re.search(r'(\d+)(?!.*\d)', base_name)
        return match.group(1) if match else None

    def _determine_group_id(self, basename: str, ext: str, nxs_to_id: Dict[str, str]) -> Optional[str]:
        """Determine which group a file belongs to."""
        file_id = self._extract_scan_id(basename)

        if ext == '.hdf':
            if file_id:
                for nxs_path, nxs_id in nxs_to_id.items():
                    if nxs_id == file_id:
                        return nxs_id

        elif ext == '.nxs':
            return file_id

        elif ext == '.xy':
            base_parts = os.path.splitext(basename)[0]
            if '_integration_' in base_parts:
                base_without_integration = base_parts.split('_integration_')[0]
                xy_id = self._extract_scan_id(base_without_integration)
                if xy_id:
                    for nxs_path, nxs_id in nxs_to_id.items():
                        if nxs_id == xy_id:
                            return nxs_id
            else:
                if file_id:
                    for nxs_path, nxs_id in nxs_to_id.items():
                        if nxs_id == file_id:
                            return nxs_id

        return None


class NexusMetadataExtractor:
    """Extracts metadata from NeXus (NXS) files."""

    TIMESTAMP_PATHS = [
        '/entry1/start_time',
        '/entry/start_time',
        '/entry1/instrument/detector/start_time',
        '/entry1/end_time',
    ]

    TIME_PATH_PAIRS = [
        ('/entry1/start_time', '/entry1/end_time'),
        ('/entry/start_time', '/entry/end_time'),
    ]

    EXPOSURE_PATHS = [
        '/entry1/instrument/detector/exposure_time',
        '/entry/instrument/detector/exposure_time',
        '/entry1/instrument/detector/count_time',
        '/entry1/instrument/detector/preset',
    ]

    @lru_cache(maxsize=128)
    def extract(self, nxs_path: str) -> Optional[Dict[str, Any]]:
        """Extract timestamp and exposure time from NXS file."""
        try:
            with h5py.File(nxs_path, 'r') as f:
                metadata = {}

                timestamp = self._extract_timestamp(f)
                if timestamp:
                    metadata['timestamp'] = timestamp

                exposure_time = self._extract_exposure_time(f)
                if exposure_time:
                    metadata['exposure_time'] = exposure_time

                midpoint = self._calculate_midpoint_timestamp(f)
                if midpoint:
                    metadata['timestamp'] = midpoint

                return metadata if metadata else None

        except Exception:
            return None

    def _extract_timestamp(self, h5file: h5py.File) -> Optional[str]:
        """Extract timestamp from NXS file."""
        for path in self.TIMESTAMP_PATHS:
            if path in h5file:
                timestamp_str = self._decode_value(h5file[path][()])
                return self._parse_nexus_timestamp(timestamp_str)
        return None

    def _extract_exposure_time(self, h5file: h5py.File) -> Optional[float]:
        """Extract exposure time from NXS file."""
        for path in self.EXPOSURE_PATHS:
            if path in h5file:
                try:
                    exp_time = float(h5file[path][()])
                    if exp_time > 0:
                        return exp_time
                except:
                    pass

        # Calculate from start/end times
        for start_path, end_path in self.TIME_PATH_PAIRS:
            if start_path in h5file and end_path in h5file:
                start_str = self._decode_value(h5file[start_path][()])
                end_str = self._decode_value(h5file[end_path][()])

                start_time = self._parse_nexus_timestamp(start_str)
                end_time = self._parse_nexus_timestamp(end_str)

                if start_time and end_time:
                    start_dt = pd.to_datetime(start_time)
                    end_dt = pd.to_datetime(end_time)
                    exposure_seconds = (end_dt - start_dt).total_seconds()

                    if 0 < exposure_seconds < 3600:
                        return exposure_seconds

        return None

    def _calculate_midpoint_timestamp(self, h5file: h5py.File) -> Optional[str]:
        """Calculate midpoint timestamp from start and end times."""
        for start_path, end_path in self.TIME_PATH_PAIRS:
            if start_path in h5file and end_path in h5file:
                start_str = self._decode_value(h5file[start_path][()])
                end_str = self._decode_value(h5file[end_path][()])

                start_time = self._parse_nexus_timestamp(start_str)
                end_time = self._parse_nexus_timestamp(end_str)

                if start_time and end_time:
                    start_dt = pd.to_datetime(start_time)
                    end_dt = pd.to_datetime(end_time)
                    exposure_seconds = (end_dt - start_dt).total_seconds()

                    if exposure_seconds > 0:
                        midpoint = start_dt + pd.Timedelta(seconds=exposure_seconds / 2)
                        return midpoint.strftime('%Y-%m-%d %H:%M:%S')

        return None

    @staticmethod
    def _decode_value(value: Any) -> str:
        """Decode value from HDF5 file."""
        if isinstance(value, bytes):
            return value.decode()
        return str(value)

    @staticmethod
    def _parse_nexus_timestamp(timestamp_str: str) -> str:
        """Parse NeXus timestamp format to standard format."""
        if 'T' in timestamp_str:
            base_time = timestamp_str.split('+')[0].split('Z')[0]
            if '.' in base_time:
                base_time = base_time.split('.')[0]
            return base_time.replace('T', ' ')
        return timestamp_str


# ============================================================================
# Scan Processor
# ============================================================================

class ScanProcessor:
    """Enhanced scan processor with better timestamp correlation."""

    def __init__(self, time_method: TimeMethod = TimeMethod.ABSOLUTE,
                 data_source: DataSourceType = DataSourceType.INHOUSE):
        self.time_method = time_method
        self.data_source = data_source
        self.xrd_reference_time = None
        self.echem_reference_time = None
        self.neutron_reference_time = None
        self.echem_parser = EchemParser()
        self.neutron_parser = NeutronMetadataParser()

    def process_scans(self, df: pd.DataFrame) -> Tuple[List[Scan], pd.DataFrame]:
        """Process scans and correlate with echem data."""
        combined_echem_df = self._process_echem_data(df)

        neutron_metadata_df = None
        if self.data_source == DataSourceType.NEUTRON:
            neutron_metadata_df = self._process_neutron_metadata(df)
            logger.info(f"Processed neutron metadata: {neutron_metadata_df is not None}")
            if neutron_metadata_df is not None:
                logger.info(f"Found {len(neutron_metadata_df)} neutron scans")

        if self.time_method == TimeMethod.RELATIVE:
            self._set_reference_times(df, combined_echem_df, neutron_metadata_df)

        scan_list = self._create_scan_list(df, neutron_metadata_df)

        self._adjust_for_exposure_time(scan_list)

        if not combined_echem_df.empty:
            self._correlate_with_echem(scan_list, combined_echem_df)

        if self.time_method == TimeMethod.RELATIVE:
            self._apply_relative_time(scan_list, combined_echem_df)

        return scan_list, combined_echem_df

    def _process_neutron_metadata(self, df: pd.DataFrame) -> Optional[pd.DataFrame]:
        """Process neutron metadata files."""
        neutron_meta_paths = df[df["neutron_meta"].notna()]["neutron_meta"].tolist()

        logger.info(f"Found {len(neutron_meta_paths)} neutron metadata files")

        if not neutron_meta_paths:
            return None

        neutron_dfs = []
        for path in neutron_meta_paths:
            logger.debug(f"Parsing metadata file: {path}")
            meta_df = self.neutron_parser.parse(path)
            if meta_df is not None:
                meta_df["source_file"] = path
                neutron_dfs.append(meta_df)
                logger.debug(f"Successfully parsed {len(meta_df)} entries")
            else:
                logger.debug("Failed to parse metadata")

        if neutron_dfs:
            combined_df = pd.concat(neutron_dfs, ignore_index=True)
            logger.info(f"Combined neutron metadata: {len(combined_df)} total entries")
            return combined_df

        return None

    def _process_echem_data(self, df: pd.DataFrame) -> pd.DataFrame:
        """Process all echem files and combine data."""
        echem_paths = df[df["echem"].notna()]["echem"].tolist()
        echem_dfs = []

        for e_path in echem_paths:
            e_df = self.echem_parser.parse(e_path)
            if e_df is not None:
                e_df["source_file"] = e_path
                echem_dfs.append(e_df)

        if echem_dfs:
            combined_df = pd.concat(echem_dfs, ignore_index=True).sort_values("timestamp")

            logger.info(f"Echem data: {len(combined_df)} rows")
            if len(combined_df) > 0:
                logger.debug(f"First echem timestamp: {combined_df.iloc[0]['timestamp']}")
                logger.debug(f"Last echem timestamp: {combined_df.iloc[-1]['timestamp']}")

            return combined_df

        return pd.DataFrame(columns=["timestamp", "echem_data", "current", "source_file"])

    def _set_reference_times(self, df: pd.DataFrame, echem_df: pd.DataFrame,
                             neutron_df: Optional[pd.DataFrame] = None) -> None:
        """Set reference times for relative time mode."""
        # XRD reference time
        xrd_timestamps = []
        for idx, row in df.iterrows():
            if row["timestamp"] and (row["oned"] or row["twod"]):
                xrd_timestamps.append(pd.to_datetime(row["timestamp"]))

        if xrd_timestamps:
            self.xrd_reference_time = min(xrd_timestamps)

        # Echem reference time
        if not echem_df.empty:
            self.echem_reference_time = pd.to_datetime(echem_df["timestamp"]).min()

        # Neutron reference time
        if neutron_df is not None and not neutron_df.empty:
            neutron_timestamps = []
            for idx, row in neutron_df.iterrows():
                if row["start_time"]:
                    neutron_timestamps.append(pd.to_datetime(row["start_time"]))

            if neutron_timestamps:
                self.neutron_reference_time = min(neutron_timestamps)

    def _create_neutron_scan_list(self, df: pd.DataFrame,
                                  neutron_metadata_df: pd.DataFrame) -> List[Scan]:
        """Create scan list for neutron data."""
        scan_list = []

        neutron_files = []
        logger.debug(f"DataFrame has {len(df)} rows")

        for idx, row in df.iterrows():
            if pd.notna(row["path"]) and row["path"].endswith('.dat'):
                neutron_files.append(row["path"])
                if len(neutron_files) <= 5:
                    logger.debug(f"Found neutron data file: {os.path.basename(row['path'])}")

        logger.info(f"Found {len(neutron_files)} .dat files")

        grouper = NeutronFileGrouper()
        neutron_groups = grouper.group_neutron_files(neutron_files)
        logger.info(f"Created {len(neutron_groups)} neutron groups")

        scans_with_data = 0
        scans_without_data = 0

        for idx, meta_row in neutron_metadata_df.iterrows():
            scan_id = str(meta_row["scan_id"])

            neutron_data_files = neutron_groups.get(scan_id, {})

            if not neutron_data_files:
                scans_without_data += 1
                if scans_without_data <= 5:
                    logger.debug(f"Info: No data files for scan {scan_id} - skipping")
                continue

            scans_with_data += 1

            start_time = meta_row["start_time"]
            end_time = meta_row["end_time"]

            if isinstance(start_time, str):
                start_time = pd.to_datetime(start_time, format='%a %b %d %H:%M:%S %Y')
            if isinstance(end_time, str):
                end_time = pd.to_datetime(end_time, format='%a %b %d %H:%M:%S %Y')

            midpoint = start_time + (end_time - start_time) / 2

            if scans_with_data <= 3:
                logger.debug(f"Scan {scan_id}: Start: {start_time}, End: {end_time}, Midpoint: {midpoint}")

            scan = Scan(
                scan_num=0,
                neutron_meta=meta_row.get("source_file"),
                neutron_files=neutron_data_files,
                neutron_start=start_time.strftime('%Y-%m-%d %H:%M:%S'),
                neutron_end=end_time.strftime('%Y-%m-%d %H:%M:%S'),
                timestamp=midpoint.strftime('%Y-%m-%d %H:%M:%S'),
                original_timestamp=midpoint.strftime('%Y-%m-%d %H:%M:%S'),
                timestamp_for_correlation=midpoint
            )
            scan_list.append(scan)

        logger.info(f"Created {len(scan_list)} neutron scans with data")
        if scans_without_data > 5:
            logger.info(f"({scans_without_data} scans in metadata had no data files and were skipped)")

        return scan_list

    def _create_scan_list(self, df: pd.DataFrame,
                          neutron_metadata_df: Optional[pd.DataFrame] = None) -> List[Scan]:
        """Create list of scans from DataFrame."""
        scan_list = []

        if self.data_source == DataSourceType.NEUTRON and neutron_metadata_df is not None:
            scan_list = self._create_neutron_scan_list(df, neutron_metadata_df)
        elif self.data_source == DataSourceType.SYNCHROTRON:
            synchrotron_df = df[(df["oned"].notna()) & (df["twod"].notna())]
            for idx, row in synchrotron_df.iterrows():
                scan = Scan(
                    scan_num=0,
                    oned=row["oned"],
                    twod=row["twod"],
                    timestamp=row["timestamp"],
                    original_timestamp=row["timestamp"],
                    exposure_time=row.get("exposure_time"),
                    oned_exposure=row.get("exposure_time"),
                    twod_exposure=row.get("exposure_time")
                )
                scan_list.append(scan)
        else:
            traditional_one_d = df[(df["oned"].notna()) & (df["twod"].isna())]
            two_d_df = df[(df["twod"].notna()) & (df["oned"].isna())]

            for idx, row in traditional_one_d.iterrows():
                scan = Scan(
                    scan_num=0,
                    oned=row["oned"],
                    timestamp=row["timestamp"],
                    original_timestamp=row["timestamp"],
                    oned_exposure=row.get("exposure_time")
                )
                if row["timestamp"]:
                    match = two_d_df[two_d_df["timestamp"] == row["timestamp"]]
                    if not match.empty:
                        scan.twod = match.iloc[0]["twod"]
                        scan.twod_exposure = match.iloc[0].get("exposure_time")
                scan_list.append(scan)

        scan_list = self._sort_scan_list(scan_list)
        for num, scan in enumerate(scan_list, start=1):
            scan.scan_num = num

        return scan_list

    def _sort_scan_list(self, scan_list: List[Scan]) -> List[Scan]:
        """Sort scans by timestamp."""
        if self.data_source == DataSourceType.NEUTRON and self.neutron_reference_time:
            def get_relative_seconds(scan):
                if scan.timestamp:
                    ts = pd.to_datetime(scan.timestamp)
                    return (ts - self.neutron_reference_time).total_seconds()
                return float('inf')

            scan_list.sort(key=get_relative_seconds)
        elif self.time_method == TimeMethod.RELATIVE and self.xrd_reference_time:
            def get_relative_seconds(scan):
                if scan.timestamp:
                    ts = pd.to_datetime(scan.timestamp)
                    return (ts - self.xrd_reference_time).total_seconds()
                return float('inf')

            scan_list.sort(key=get_relative_seconds)
        else:
            scan_list.sort(key=lambda x: x.timestamp or "")

        return scan_list

    def _adjust_for_exposure_time(self, scan_list: List[Scan]) -> None:
        """Adjust timestamps to midpoint of exposure for echem correlation."""
        logger.debug("Adjusting timestamps to midpoint")
        for i, scan in enumerate(scan_list):
            exposure_time = self._determine_exposure_time(scan)
            scan.exposure_time = exposure_time

            if self.data_source == DataSourceType.NEUTRON:
                scan.timestamp_for_correlation = pd.to_datetime(scan.timestamp) if scan.timestamp else None
            else:
                if exposure_time and scan.timestamp:
                    original_ts = pd.to_datetime(scan.timestamp)
                    adjusted_ts = original_ts + pd.Timedelta(seconds=exposure_time / 2)
                    scan.timestamp_for_correlation = adjusted_ts
                else:
                    scan.timestamp_for_correlation = pd.to_datetime(scan.timestamp) if scan.timestamp else None

    def _determine_exposure_time(self, scan: Scan) -> Optional[float]:
        """Determine exposure time for a scan."""
        if self.data_source == DataSourceType.NEUTRON and scan.neutron_start and scan.neutron_end:
            start = pd.to_datetime(scan.neutron_start)
            end = pd.to_datetime(scan.neutron_end)
            return (end - start).total_seconds()

        if scan.oned and scan.twod:
            if scan.oned_exposure and scan.twod_exposure:
                return (scan.oned_exposure + scan.twod_exposure) / 2
        elif scan.oned and scan.oned_exposure:
            return scan.oned_exposure
        elif scan.twod and scan.twod_exposure:
            return scan.twod_exposure
        return None

    def _correlate_with_echem(self, scan_list: List[Scan], echem_df: pd.DataFrame) -> None:
        """Correlate scans with echem data."""
        if self.time_method == TimeMethod.RELATIVE:
            self._correlate_relative_time(scan_list, echem_df)
        else:
            self._correlate_absolute_time(scan_list, echem_df)

    def _correlate_relative_time(self, scan_list: List[Scan], echem_df: pd.DataFrame) -> None:
        """Correlate using relative time."""
        reference_time = None
        if self.data_source == DataSourceType.NEUTRON:
            reference_time = self.neutron_reference_time
        else:
            reference_time = self.xrd_reference_time

        if not reference_time or not self.echem_reference_time:
            logger.warning("No reference times available for relative correlation")
            return

        echem_timestamps = pd.to_datetime(echem_df["timestamp"])
        echem_relative_seconds = (echem_timestamps - self.echem_reference_time).dt.total_seconds()

        logger.debug(
            f"Relative Time Correlation - XRD/Neutron ref: {reference_time}, Echem ref: {self.echem_reference_time}")

        for i, scan in enumerate(scan_list):
            if not scan.timestamp_for_correlation:
                scan.echem_timestamp = None
                continue

            scan_relative_seconds = (scan.timestamp_for_correlation - reference_time).total_seconds()

            time_diffs = np.abs(echem_relative_seconds - scan_relative_seconds)
            nearest_idx = time_diffs.argmin()
            min_diff_seconds = time_diffs.iloc[nearest_idx]

            if min_diff_seconds < ECHEM_TIME_TOLERANCE:
                scan.echem = float(echem_df.iloc[nearest_idx]["echem_data"])
                current_val = echem_df.iloc[nearest_idx]["current"]
                scan.current = float(current_val) if pd.notna(current_val) else None
                scan.echem_timestamp = str(echem_df.iloc[nearest_idx]["timestamp"])
            else:
                scan.echem = None
                scan.current = None
                scan.echem_timestamp = None

    def _correlate_absolute_time(self, scan_list: List[Scan], echem_df: pd.DataFrame) -> None:
        """Correlate using absolute time."""
        echem_timestamps = None
        try:
            echem_timestamps = pd.to_datetime(echem_df["timestamp"])
        except:
            try:
                echem_timestamps = pd.to_datetime(echem_df["timestamp"], format='%d/%m/%Y %H:%M:%S.%f', dayfirst=True)
            except:
                try:
                    echem_timestamps = pd.to_datetime(echem_df["timestamp"], format='%d/%m/%Y %H:%M:%S', dayfirst=True)
                except:
                    logger.error("Could not parse echem timestamps")
                    return

        echem_start = echem_timestamps.min()
        echem_end = echem_timestamps.max()

        logger.debug(f"Absolute Time Correlation - Echem range: {echem_start} to {echem_end}")

        for i, scan in enumerate(scan_list):
            scan_time = scan.timestamp_for_correlation
            if not scan_time:
                scan.echem_timestamp = None
                continue

            if isinstance(scan_time, str):
                scan_time = pd.to_datetime(scan_time)

            if (scan_time < echem_start - pd.Timedelta(seconds=ECHEM_TIME_TOLERANCE) or
                    scan_time > echem_end + pd.Timedelta(seconds=ECHEM_TIME_TOLERANCE)):
                scan.echem = None
                scan.current = None
                scan.echem_timestamp = None
                continue

            time_diffs = abs(echem_timestamps - scan_time)
            nearest_idx = time_diffs.argmin()
            min_diff = time_diffs.iloc[nearest_idx]

            if min_diff.total_seconds() < ECHEM_TIME_TOLERANCE:
                scan.echem = float(echem_df.iloc[nearest_idx]["echem_data"])
                current_val = echem_df.iloc[nearest_idx]["current"]
                scan.current = float(current_val) if pd.notna(current_val) else None
                scan.echem_timestamp = str(echem_df.iloc[nearest_idx]["timestamp"])
            else:
                scan.echem = None
                scan.current = None
                scan.echem_timestamp = None

    def _apply_relative_time(self, scan_list: List[Scan], echem_df: pd.DataFrame) -> None:
        """Apply relative time formatting."""
        reference_time = None
        if self.data_source == DataSourceType.NEUTRON:
            reference_time = self.neutron_reference_time
        else:
            reference_time = self.xrd_reference_time

        if reference_time:
            for scan in scan_list:
                if scan.timestamp:
                    scan.original_timestamp = scan.timestamp
                    original_time = pd.to_datetime(scan.timestamp)
                    relative_seconds = (original_time - reference_time).total_seconds()
                    scan.timestamp = self._format_relative_time(relative_seconds)

        if not echem_df.empty and self.echem_reference_time:
            original_timestamps = pd.to_datetime(echem_df["timestamp"])
            relative_seconds = (original_timestamps - self.echem_reference_time).dt.total_seconds()

            echem_df["original_timestamp"] = echem_df["timestamp"].copy()
            echem_df["timestamp"] = [self._format_relative_time(s) for s in relative_seconds]

    @staticmethod
    def _format_relative_time(seconds: float) -> str:
        """Format seconds as HH:MM:SS."""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"


# ============================================================================
# Data Reader Factory
# ============================================================================

class DataReaderFactory:
    """Factory for creating appropriate data readers."""

    READERS = {
        FileType.EDF: EDFReader(),
        FileType.DAT: DATReader("xrd"),
        FileType.HDF: HDFReader(),
        FileType.XY: XYReader()
    }

    NEUTRON_READER = DATReader("neutron")

    @classmethod
    def get_reader(cls, file_path: str, is_neutron: bool = False) -> DataReader:
        """Get appropriate reader for file."""
        if is_neutron and file_path.endswith('.dat'):
            return cls.NEUTRON_READER

        ext = os.path.splitext(file_path)[1].lower()
        file_type = FileType(ext) if ext in [ft.value for ft in FileType] else None

        if file_type and file_type in cls.READERS:
            return cls.READERS[file_type]

        raise ValueError(f"No reader available for file type: {ext}")

    @classmethod
    def read_file(cls, file_path: str, use_cache: bool = True, is_neutron: bool = False) -> np.ndarray:
        """Read file using appropriate reader with caching."""
        reader = cls.get_reader(file_path, is_neutron)
        return reader.read(file_path, use_cache)


# ============================================================================
# Main API Functions
# ============================================================================

def process_paths(selected_paths: List[str],
                  progress_callback: Optional[Callable] = None,
                  time_method: Optional[TimeMethod] = None,
                  data_source: DataSourceType = DataSourceType.INHOUSE) -> Tuple[
                  List[Dict[str, Any]], pd.DataFrame, str]:
    """Main entry point for processing selected paths."""
    with FileProcessor(progress_callback, data_source) as processor:
        records = processor.process_paths(selected_paths)

    if not records:
        return [], pd.DataFrame(), TimeMethod.ABSOLUTE.value

    records_df = pd.DataFrame([r.__dict__ for r in records])

    if progress_callback:
        progress_callback("Classifying files...")

    classifier_manager = FileClassificationManager(data_source)
    sorted_df = classifier_manager.classify_files(records_df)

    if time_method is None:
        time_method = TimeSortingDialog.ask_method()

    if progress_callback:
        progress_callback("Processing scans and correlating with echem...")

    scan_processor = ScanProcessor(time_method, data_source)
    scans, echem_df = scan_processor.process_scans(sorted_df)

    scan_dicts = [scan.to_dict() for scan in scans]

    return scan_dicts, echem_df, time_method.value


def make_neutron_arrays(scans: List[Dict[str, Any]], state: Any = None) -> Dict[int, Dict[str, Dict[str, Any]]]:
    """Create neutron data arrays from scans."""
    plot_data = {}
    reader = DATReader("neutron")

    for scan in scans:
        if not scan.get("neutron_files"):
            continue

        scan_data = {}

        for measurement_num, measurement_files in scan["neutron_files"].items():
            measurement_data = {}

            if "tof" in measurement_files:
                try:
                    if state and hasattr(state, 'get_cached_data'):
                        data = state.get_cached_data(
                            measurement_files["tof"],
                            lambda: reader.read(measurement_files["tof"])
                        )
                    else:
                        data = reader.read(measurement_files["tof"])

                    measurement_data["tof"] = {
                        "x": data[:, 0],
                        "y": data[:, 1]
                    }
                except Exception as e:
                    logger.error(f"Error reading TOF file: {e}")

            if "d" in measurement_files:
                try:
                    if state and hasattr(state, 'get_cached_data'):
                        data = state.get_cached_data(
                            measurement_files["d"],
                            lambda: reader.read(measurement_files["d"])
                        )
                    else:
                        data = reader.read(measurement_files["d"])

                    measurement_data["d"] = {
                        "x": data[:, 0],
                        "y": data[:, 1]
                    }
                except Exception as e:
                    logger.error(f"Error reading d-spacing file: {e}")

            if measurement_data:
                scan_data[measurement_num] = measurement_data

        if scan_data:
            plot_data[scan["scan_num"]] = scan_data

    return plot_data


def make_oned_arrays(scans: List[Dict[str, Any]], state: Any = None) -> Dict[int, Dict[str, Any]]:
    """Create 1D data arrays from scans with caching."""
    plot_data = {}
    reader_factory = DataReaderFactory()

    for scan in scans:
        if not scan.get("oned"):
            continue

        try:
            if state and hasattr(state, 'get_cached_data'):
                data = state.get_cached_data(
                    scan["oned"],
                    lambda: reader_factory.read_file(scan["oned"])
                )
            else:
                data = reader_factory.read_file(scan["oned"])

            plot_data[scan["scan_num"]] = {
                "x": data[:, 0],
                "y": data[:, 1],
                "timestamp": scan["timestamp"],
                "echem": scan.get("echem"),
                "current": scan.get("current")
            }
        except Exception as e:
            logger.error(f"Error reading 1D data for scan {scan['scan_num']}: {e}")

    return plot_data


def make_twod_arrays(scans: List[Dict[str, Any]], state: Any = None) -> Dict[int, Dict[str, Any]]:
    """Create 2D data arrays from scans with caching."""
    plot_data = {}
    reader_factory = DataReaderFactory()

    for scan in scans:
        if not scan.get("twod"):
            continue

        try:
            if state and hasattr(state, 'get_cached_data'):
                image = state.get_cached_data(
                    scan["twod"],
                    lambda: reader_factory.read_file(scan["twod"])
                )
            else:
                image = reader_factory.read_file(scan["twod"])

            plot_data[scan["scan_num"]] = {
                "image": image,
                "timestamp": scan["timestamp"],
                "echem": scan.get("echem"),
                "current": scan.get("current")
            }
        except Exception as e:
            logger.error(f"Error reading 2D data for scan {scan['scan_num']}: {e}")

    return plot_data


def make_echem_arrays(echem_df: Optional[pd.DataFrame],
                      time_method: str = "absolute") -> Dict[str, Union[np.ndarray, List]]:
    """Create echem data arrays."""
    if echem_df is None or echem_df.empty:
        return {
            "x": np.array([]),
            "y": np.array([]),
            "current": np.array([]),
            "timestamps": []
        }

    if time_method == TimeMethod.RELATIVE.value or time_method == "relative":
        time_seconds = []
        for ts in echem_df["timestamp"]:
            if isinstance(ts, str) and ":" in ts and "-" not in ts:
                parts = ts.split(":")
                if len(parts) == 3:
                    try:
                        seconds = int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
                        time_seconds.append(seconds)
                    except ValueError:
                        time_seconds.append(0)
                else:
                    time_seconds.append(0)
            else:
                time_seconds.append(0)
        time_seconds = np.array(time_seconds)
    else:
        try:
            timestamps = pd.to_datetime(echem_df["timestamp"])
            time_seconds = (timestamps - timestamps.min()).dt.total_seconds().values
        except Exception as e:
            logger.error(f"Error processing timestamps: {e}")
            time_seconds = np.arange(len(echem_df))

    echem_values = echem_df["echem_data"].values
    current_values = (echem_df["current"].values if "current" in echem_df.columns
                      else np.full(len(echem_df), np.nan))

    return {
        "x": time_seconds,
        "y": echem_values,
        "current": current_values,
        "timestamps": echem_df["timestamp"].tolist()
    }


def get_correlated_data(scans: List[Dict[str, Any]],
                        echem_df: Optional[pd.DataFrame],
                        scan_num: int,
                        state: Any = None) -> Optional[Dict[str, Any]]:
    """Get all correlated data for a specific scan with caching (including neutron)."""
    scan = next((s for s in scans if s["scan_num"] == scan_num), None)
    if not scan:
        return None

    reader_factory = DataReaderFactory()

    result = {
        "scan_num": scan_num,
        "timestamp": scan["timestamp"],
        "echem_value": scan.get("echem"),
        "current_value": scan.get("current")
    }

    # Standard XRD data
    if scan.get("oned"):
        try:
            if state and hasattr(state, 'get_cached_data'):
                data = state.get_cached_data(
                    scan["oned"],
                    lambda: reader_factory.read_file(scan["oned"])
                )
            else:
                data = reader_factory.read_file(scan["oned"])

            result["oned"] = {
                "x": data[:, 0],
                "y": data[:, 1]
            }
        except Exception:
            result["oned"] = None
    else:
        result["oned"] = None

    if scan.get("twod"):
        try:
            if state and hasattr(state, 'get_cached_data'):
                result["twod"] = state.get_cached_data(
                    scan["twod"],
                    lambda: reader_factory.read_file(scan["twod"])
                )
            else:
                result["twod"] = reader_factory.read_file(scan["twod"])
        except Exception:
            result["twod"] = None
    else:
        result["twod"] = None

    # Neutron data
    if scan.get("neutron_files"):
        neutron_data = {}
        reader = DATReader("neutron")

        for measurement_num, measurement_files in scan["neutron_files"].items():
            measurement_data = {}

            if "tof" in measurement_files:
                try:
                    if state and hasattr(state, 'get_cached_data'):
                        data = state.get_cached_data(
                            measurement_files["tof"],
                            lambda: reader.read(measurement_files["tof"])
                        )
                    else:
                        data = reader.read(measurement_files["tof"])

                    measurement_data["tof"] = {
                        "x": data[:, 0],
                        "y": data[:, 1]
                    }
                except Exception:
                    pass

            if "d" in measurement_files:
                try:
                    if state and hasattr(state, 'get_cached_data'):
                        data = state.get_cached_data(
                            measurement_files["d"],
                            lambda: reader.read(measurement_files["d"])
                        )
                    else:
                        data = reader.read(measurement_files["d"])

                    measurement_data["d"] = {
                        "x": data[:, 0],
                        "y": data[:, 1]
                    }
                except Exception:
                    pass

            if measurement_data:
                neutron_data[measurement_num] = measurement_data

        if neutron_data:
            result["neutron"] = neutron_data

    # Find nearest echem
    if echem_df is not None and not echem_df.empty and scan.get("timestamp"):
        result["echem_nearest"] = _find_nearest_echem(scan, echem_df)
    else:
        result["echem_nearest"] = None

    return result


def _find_nearest_echem(scan: Dict[str, Any],
                        echem_df: pd.DataFrame) -> Optional[Dict[str, Any]]:
    """Find nearest echem measurement to scan."""
    if echem_df.empty:
        return None

    scan_timestamp = scan.get("timestamp")
    if not scan_timestamp:
        return None

    # Check if this is relative time format (HH:MM:SS)
    if ":" in str(scan_timestamp) and "-" not in str(scan_timestamp):
        # Relative time format
        try:
            scan_parts = scan_timestamp.split(":")
            if len(scan_parts) == 3:
                scan_seconds = int(scan_parts[0]) * 3600 + int(scan_parts[1]) * 60 + int(scan_parts[2])

                echem_seconds = []
                for ts in echem_df["timestamp"]:
                    if isinstance(ts, str) and ":" in ts and "-" not in ts:
                        parts = ts.split(":")
                        if len(parts) == 3:
                            seconds = int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
                            echem_seconds.append(seconds)
                        else:
                            echem_seconds.append(float('inf'))
                    else:
                        echem_seconds.append(float('inf'))

                echem_seconds = np.array(echem_seconds)
                time_diffs = np.abs(echem_seconds - scan_seconds)
                nearest_idx = time_diffs.argmin()

                if time_diffs[nearest_idx] <= 60:  # Within 60 seconds
                    row = echem_df.iloc[nearest_idx]
                    return {
                        "timestamp": row["timestamp"],
                        "value": row["echem_data"],
                        "current": row.get("current") if "current" in echem_df.columns else None
                    }
        except (ValueError, IndexError) as e:
            logger.error(f"Error parsing relative time: {e}")
            return None
    else:
        # Absolute time format
        try:
            scan_time = pd.to_datetime(scan_timestamp)
            echem_timestamps = pd.to_datetime(echem_df["timestamp"])

            time_diffs = abs(echem_timestamps - scan_time)
            nearest_idx = time_diffs.argmin()

            if time_diffs.iloc[nearest_idx].total_seconds() <= 60:
                row = echem_df.iloc[nearest_idx]
                return {
                    "timestamp": row["timestamp"],
                    "value": row["echem_data"],
                    "current": row.get("current") if "current" in echem_df.columns else None
                }
        except Exception as e:
            logger.error(f"Error parsing absolute time: {e}")
            return None

    return None


# ============================================================================
# UI Components
# ============================================================================

class TimeSortingDialog:
    """Dialog for selecting time sorting method with consistent theming."""

    @staticmethod
    def ask_method() -> TimeMethod:
        """Show dialog and return selected method."""
        import tkinter as tk

        dialog = tk.Toplevel()
        dialog.title("Time Sorting Method")
        dialog.geometry(WINDOW_SIZES['time'])
        dialog.transient()
        dialog.grab_set()

        dialog.configure(bg=OPERAXNTheme.COLORS['bg_primary'])

        dialog.protocol("WM_DELETE_WINDOW", lambda: [result.update({"method": None}), dialog.destroy()])

        dialog.update_idletasks()
        x = (dialog.winfo_screenwidth() // 2) - (dialog.winfo_width() // 2)
        y = (dialog.winfo_screenheight() // 2) - (dialog.winfo_height() // 2)
        dialog.geometry(f"+{x}+{y}")

        result = {"method": TimeMethod.ABSOLUTE}

        tk.Label(
            dialog,
            text="How should timestamps be handled?",
            font=OPERAXNTheme.FONTS['heading'],
            bg=OPERAXNTheme.COLORS['bg_primary'],
            fg=OPERAXNTheme.COLORS['text_primary']
        ).pack(pady=20)

        var = tk.StringVar(value=TimeMethod.ABSOLUTE.value)

        options = [
            (TimeMethod.ABSOLUTE.value, "Absolute time (use actual timestamps)"),
            (TimeMethod.RELATIVE.value, "Relative time (XRD and echem each start at 00:00:00)")
        ]

        for value, text in options:
            tk.Radiobutton(
                dialog,
                text=text,
                variable=var,
                value=value,
                font=OPERAXNTheme.FONTS['body'],
                bg=OPERAXNTheme.COLORS['bg_primary'],
                fg=OPERAXNTheme.COLORS['text_primary'],
                activebackground=OPERAXNTheme.COLORS['bg_primary'],
                activeforeground=OPERAXNTheme.COLORS['accent_primary'],
                selectcolor=OPERAXNTheme.COLORS['bg_tertiary']
            ).pack(anchor="w", padx=30, pady=5)

        def confirm():
            result["method"] = TimeMethod(var.get())
            dialog.destroy()

        button_frame = tk.Frame(dialog, bg=OPERAXNTheme.COLORS['bg_primary'])
        button_frame.pack(pady=10)

        confirm_btn = tk.Button(
            button_frame,
            text="OK",
            command=confirm,
            width=12,
            bg=OPERAXNTheme.COLORS['accent_primary'],
            fg=OPERAXNTheme.COLORS['bg_primary'],
            font=OPERAXNTheme.FONTS['button'],
            relief=tk.FLAT,
            cursor='hand2'
        )
        confirm_btn.pack()

        confirm_btn.bind("<Enter>", lambda e: confirm_btn.config(bg=OPERAXNTheme.COLORS['accent_hover']))
        confirm_btn.bind("<Leave>", lambda e: confirm_btn.config(bg=OPERAXNTheme.COLORS['accent_primary']))

        dialog.wait_window()
        return result["method"]


# ============================================================================
# Performance Utility Functions
# ============================================================================

def clear_global_cache():
    """Clear the global file cache."""
    global _file_cache
    _file_cache.clear()


def get_cache_stats() -> Dict[str, Any]:
    """Get cache statistics."""
    global _file_cache
    return {
        "size_bytes": _file_cache.current_size,
        "size_mb": _file_cache.current_size / (1024 * 1024),
        "num_items": len(_file_cache.cache),
        "max_size_mb": MAX_CACHE_SIZE_MB
    }
