"""
NXS Generator
"""

import logging
import os
import re
import tempfile
import threading
import tkinter as tk
import zipfile
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from enum import Enum
from tkinter import filedialog, messagebox, ttk
from typing import Any, Callable, Dict,  List, Optional, Tuple

import fabio
import h5py
import numpy as np
import pandas as pd


# ============================================================================
# Logging
# ============================================================================
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')


# ============================================================================
# Config
# ============================================================================
@dataclass
class NXSConfig:
    """Configuration constraints."""
    echem_time_tolerance: int = 300
    max_workers: int = 8
    parallel_processing: bool = True


# Global config instance
config = NXSConfig()


# ============================================================================
# Data Models and Enums
# ============================================================================
class DataSourceType(Enum):
    """Types of data sources."""
    INHOUSE = "inhouse"
    SYNCHROTRON = "synchrotron"
    NEUTRON = "neutron"


class FileType(Enum):
    """Supported file types."""
    DAT = ".dat"
    EDF = ".edf"
    TXT = ".txt"
    HDF = ".hdf"
    NXS = ".nxs"
    XY = ".xy"
    ZIP = ".zip"


class DataType(Enum):
    """Types of data."""
    ONED = "oned"
    TWOD = "twod"
    ECHEM = "echem"
    NEUTRON_META = "neutron_meta"


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
# GUI
# ============================================================================
class NXSGeneratorGUI:
    """Tkinter GUI for NXS file generation."""

    def __init__(self, root):
        self.progress_label = None
        self.generate_btn = None
        self.progress_bar = None
        self.root = root
        self.root.title("NXS File Generator")
        self.root.geometry("600x480")

        # Variables
        self.input_path = tk.StringVar()
        self.output_path = tk.StringVar()
        self.data_source = tk.StringVar(value="inhouse")
        self.time_method = tk.StringVar(value="absolute")
        self.progress_text = tk.StringVar(value="Ready")

        self.setup_ui()

    def setup_ui(self):
        """Create the GUI layout."""

        # Main container
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))

        # Configure grid weights
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main_frame.columnconfigure(1, weight=1)

        # Title
        title = ttk.Label(main_frame, text="NXS File Generator",
                          font=('Helvetica', 16, 'bold'))
        title.grid(row=0, column=0, columnspan=3, pady=(0, 10))

        # Input selection
        ttk.Label(main_frame, text="Input Path:", font=('Helvetica', 10, 'bold')).grid(
            row=1, column=0, sticky=tk.W, pady=(10, 5))

        input_frame = ttk.Frame(main_frame)
        input_frame.grid(row=2, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=(0, 10))
        input_frame.columnconfigure(0, weight=1)

        ttk.Entry(input_frame, textvariable=self.input_path).grid(
            row=0, column=0, sticky=(tk.W, tk.E), padx=(0, 5))

        ttk.Button(input_frame, text="Select File",
                   command=self.select_file).grid(row=0, column=1, padx=(0, 5))

        ttk.Button(input_frame, text="Select Directory",
                   command=self.select_directory).grid(row=0, column=2)

        # Output selection
        ttk.Label(main_frame, text="Output NXS File:", font=('Helvetica', 10, 'bold')).grid(
            row=3, column=0, sticky=tk.W, pady=(10, 5))

        output_frame = ttk.Frame(main_frame)
        output_frame.grid(row=4, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=(0, 10))
        output_frame.columnconfigure(0, weight=1)

        ttk.Entry(output_frame, textvariable=self.output_path).grid(
            row=0, column=0, sticky=(tk.W, tk.E), padx=(0, 5))

        ttk.Button(output_frame, text="Save As...",
                   command=self.select_output).grid(row=0, column=1)

        # Data source selection
        ttk.Label(main_frame, text="Data Source Type:", font=('Helvetica', 10, 'bold')).grid(
            row=5, column=0, sticky=tk.W, pady=(10, 5))

        source_frame = ttk.Frame(main_frame)
        source_frame.grid(row=6, column=0, columnspan=3, sticky=tk.W, pady=(0, 10))

        ttk.Radiobutton(source_frame, text="In-House",
                        variable=self.data_source, value="inhouse").grid(row=0, column=0, padx=5)
        ttk.Radiobutton(source_frame, text="Synchrotron",
                        variable=self.data_source, value="synchrotron").grid(row=0, column=1, padx=5)
        ttk.Radiobutton(source_frame, text="Neutron",
                        variable=self.data_source, value="neutron").grid(row=0, column=2, padx=5)

        # Time method selection
        ttk.Label(main_frame, text="Time Sorting Method:", font=('Helvetica', 10, 'bold')).grid(
            row=7, column=0, sticky=tk.W, pady=(10, 5))

        time_frame = ttk.Frame(main_frame)
        time_frame.grid(row=8, column=0, columnspan=3, sticky=tk.W, pady=(0, 10))

        ttk.Radiobutton(time_frame, text="Absolute Time (use actual timestamps)",
                        variable=self.time_method, value="absolute").grid(row=0, column=0, padx=5)
        ttk.Radiobutton(time_frame, text="Relative Time (start from 00:00:00)",
                        variable=self.time_method, value="relative").grid(row=0, column=1, padx=5)

        # Progress display
        ttk.Separator(main_frame, orient='horizontal').grid(
            row=9, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=10)

        ttk.Label(main_frame, text="Progress:", font=('Helvetica', 10, 'bold')).grid(
            row=10, column=0, sticky=tk.W, pady=(5, 5))

        self.progress_bar = ttk.Progressbar(main_frame, mode='indeterminate')
        self.progress_bar.grid(row=11, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=(0, 5))

        self.progress_label = ttk.Label(main_frame, textvariable=self.progress_text)
        self.progress_label.grid(row=12, column=0, columnspan=3, pady=(0, 10))

        # Action buttons
        button_frame = ttk.Frame(main_frame)
        button_frame.grid(row=13, column=0, columnspan=3, pady=(10, 0))

        self.generate_btn = ttk.Button(button_frame, text="Generate NXS File",
                                       command=self.generate_nxs)
        self.generate_btn.grid(row=0, column=0, padx=(0, 5))

        ttk.Button(button_frame, text="Exit",
                   command=self.root.quit).grid(row=0, column=1)

    def select_file(self):
        """Open dialog for single file selection."""
        filename = filedialog.askopenfilename(
            title="Select Input File",
            filetypes=[
                ("All Supported", ("*.dat", "*.edf", "*.txt", "*.hdf", "*.nxs", "*.xy", "*.zip")),
                ("DAT files", "*.dat"),
                ("EDF files", "*.edf"),
                ("Text files", "*.txt"),
                ("HDF files", "*.hdf"),
                ("NXS files", "*.nxs"),
                ("XY files", "*.xy"),
                ("ZIP files", "*.zip"),
                ("All files", "*.*")
            ]
        )
        if filename:
            self.input_path.set(filename)

            # Auto-generate output path
            base = os.path.splitext(filename)[0]
            self.output_path.set(f"{base}_output.nxs")

    def select_directory(self):
        """Open dialog for directory selection."""
        directory = filedialog.askdirectory(title="Select Input Directory")
        if directory:
            self.input_path.set(directory)

            # Auto-generate output path
            dir_name = os.path.basename(directory)
            parent_dir = os.path.dirname(directory)
            self.output_path.set(os.path.join(parent_dir, f"{dir_name}_output.nxs"))

    def select_output(self):
        """Open dialog for output file selection."""
        filename = filedialog.asksaveasfilename(
            title="Save NXS File As",
            defaultextension=".nxs",
            filetypes=[
                ("NXS files", "*.nxs"),
                ("All files", "*.*")
            ]
        )
        if filename:
            self.output_path.set(filename)

    def update_progress(self, message: str):
        """Update progress display."""
        self.root.after(0, lambda: self.progress_text.set(message))

    def generate_nxs(self):
        """Generate NXS file."""

        # Validate inputs
        if not self.input_path.get():
            messagebox.showerror("Error", "Please select an input file or directory")
            return

        if not self.output_path.get():
            messagebox.showerror("Error", "Please specify an output file")
            return

        # Disable button during processing
        self.generate_btn.config(state='disabled')
        self.progress_bar.start()

        # Run in separate thread
        thread = threading.Thread(target=self._generate_worker)
        thread.start()

    def _generate_worker(self):
        """Worker thread for NXS generation."""
        try:
            # Convert parameters
            source_type = DataSourceType(self.data_source.get())
            time_method = TimeMethod(self.time_method.get())

            # Create generator
            generator = NXSGenerator(source_type)
            generator.writer = NXSWriter()

            # Generate NXS file
            success, messages = generator.generate_nxs(
                input_paths=[self.input_path.get()],
                output_path=self.output_path.get(),
                time_method=time_method,
                progress_callback=self.update_progress
            )

            # Show results
            if success:
                self.root.after(0, lambda: messagebox.showinfo(
                    "Success",
                    f"NXS file generated successfully!\n\nOutput: {self.output_path.get()}\n\n" +
                    "\n".join(messages)
                ))
            else:
                self.root.after(0, lambda: messagebox.showerror(
                    "Error",
                    "Failed to generate NXS file:\n\n" + "\n".join(messages)
                ))

        except Exception as e:
            self.root.after(0, lambda: messagebox.showerror(
                "Error",
                f"An unexpected error occurred:\n\n{str(e)}"
            ))

        finally:
            # Re-enable button and stop progress bar
            self.root.after(0, lambda: self.generate_btn.config(state='normal'))
            self.root.after(0, lambda: self.progress_bar.stop())
            self.root.after(0, lambda: self.progress_text.set("Ready"))


# ============================================================================
# Data Readers
# ============================================================================
class DataReader(ABC):
    """Abstract base class for data readers."""

    @abstractmethod
    def _read_impl(self, path: str) -> np.ndarray:
        """Implementation of file reading."""
        pass

    def read(self, path: str) -> np.ndarray:
        """Read data from file."""
        return self._read_impl(path)


class DATReader(DataReader):
    """Reader for DAT files (XRD and neutron)."""

    def __init__(self, data_type: str = "xrd"):
        super().__init__()
        self.data_type = data_type  # "xrd" or "neutron"

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
                # Log the specific error for debugging
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


# ============================================================================
# File Processing
# ============================================================================
class FileProcessor:
    """File processing for all data types."""

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

    def process_paths(self, selected_paths: List[str]) -> List[FileRecord]:
        """Process selected paths."""
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

        remaining_files = []
        for extracted_path, original_path in all_files:
            if extracted_path not in self.processed_files:
                remaining_files.append((extracted_path, original_path))

        if remaining_files:
            if config.parallel_processing and len(remaining_files) > 20:
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
        chunk_size = max(20, len(files) // config.max_workers)
        chunks = [files[i:i + chunk_size]
                  for i in range(0, len(files), chunk_size)]

        with ThreadPoolExecutor(max_workers=config.max_workers) as executor:
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


class DataReaderFactory:
    """Factory for creating appropriate data readers."""

    READERS = {
        FileType.EDF: EDFReader(),
        FileType.DAT: DATReader("xrd"),
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
    def read_file(cls, file_path: str, is_neutron: bool = False) -> np.ndarray:
        """Read file using appropriate reader."""
        reader = cls.get_reader(file_path, is_neutron)
        return reader.read(file_path)


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
            pass

        return None, None, None


class EDFClassifier(FileClassifierBase):
    """Classifier for EDF files."""

    def classify(self, path: str) -> Tuple[Optional[str], Optional[str], Optional[float]]:
        """Classify EDF file and extract metadata."""
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
            pass

        return None, None, None


class TXTClassifier(FileClassifierBase):
    """Classifier for TXT files (electrochemistry data OR neutron metadata)."""

    ECHEM_KEYWORDS = ["time", "ecell", "voltage", "current", "i/", "ewe", "v/"]

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


class NexusMetadataExtractor:
    """Extracts metadata from NXS files."""

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
        """Decode value from HDF file."""
        if isinstance(value, bytes):
            return value.decode()
        return str(value)

    @staticmethod
    def _parse_nexus_timestamp(timestamp_str: str) -> str:
        """Parse NXS timestamp to standard format."""
        if 'T' in timestamp_str:
            base_time = timestamp_str.split('+')[0].split('Z')[0]
            if '.' in base_time:
                base_time = base_time.split('.')[0]
            return base_time.replace('T', ' ')
        return timestamp_str


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
    """Groups neutron files."""

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
# Scan Builder
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

        for extracted_path, original_path in file_dict.items():
            basename = os.path.basename(extracted_path)
            ext = os.path.splitext(basename)[1].lower()

            if ext == '.nxs':
                scan_id = self._extract_scan_id(basename)
                if scan_id:
                    nxs_to_id[extracted_path] = scan_id

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


class ScanProcessor:
    """Processes and correlates scan data including neutron data."""

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
        xrd_timestamps = []
        for idx, row in df.iterrows():
            if row["timestamp"] and (row["oned"] or row["twod"]):
                xrd_timestamps.append(pd.to_datetime(row["timestamp"]))

        if xrd_timestamps:
            self.xrd_reference_time = min(xrd_timestamps)

        if not echem_df.empty:
            self.echem_reference_time = pd.to_datetime(echem_df["timestamp"]).min()

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

            if min_diff_seconds < config.echem_time_tolerance:
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

            if (scan_time < echem_start - pd.Timedelta(seconds=config.echem_time_tolerance) or
                    scan_time > echem_end + pd.Timedelta(seconds=config.echem_time_tolerance)):
                scan.echem = None
                scan.current = None
                scan.echem_timestamp = None
                continue

            time_diffs = abs(echem_timestamps - scan_time)
            nearest_idx = time_diffs.argmin()
            min_diff = time_diffs.iloc[nearest_idx]

            if min_diff.total_seconds() < config.echem_time_tolerance:
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
# NXS File Generator
# ============================================================================
class NXSGenerator:
    """Main class for NXS file generation."""

    def __init__(self, data_source: DataSourceType = DataSourceType.INHOUSE):
        self.data_source = data_source
        self.validator = DataValidator()
        self.writer = NXSWriter()

    def generate_nxs(self, input_paths: List[str],
                     output_path: str,
                     time_method: TimeMethod = TimeMethod.ABSOLUTE,
                     progress_callback: Optional[Callable] = None) -> Tuple[bool, List[str]]:
        """NXS file generation."""
        try:
            with FileProcessor(progress_callback, self.data_source) as processor:
                records = processor.process_paths(input_paths)

            if not records:
                return False, ["No files found to process"]

            records_df = pd.DataFrame([r.__dict__ for r in records])

            if progress_callback:
                progress_callback("Classifying files...")

            classifier = FileClassificationManager(self.data_source)
            sorted_df = classifier.classify_files(records_df)

            if progress_callback:
                progress_callback("Processing scans and correlating with echem...")

            scan_processor = ScanProcessor(time_method, self.data_source)
            scans, echem_df = scan_processor.process_scans(sorted_df)

            validation_errors = self.validator.validate_for_nxs(scans, echem_df)

            if any("No scan data" in e or "No XRD" in e for e in validation_errors):
                return False, validation_errors

            if progress_callback:
                progress_callback("Writing NXS file...")

            self.writer.write(output_path, scans, echem_df)

            return True, validation_errors if validation_errors else ["NXS file generated successfully"]

        except Exception as e:
            logger.error(f"Error generating NXS file: {e}")
            return False, [f"Error: {str(e)}"]


class DataValidator:
    """Validates data before NXS generation."""

    def validate_for_nxs(self, scans: List[Scan], echem_df: pd.DataFrame) -> List[str]:
        """Returns list of validation errors, empty if valid."""
        errors = []

        if not scans:
            errors.append("No scan data available")

        if echem_df.empty:
            errors.append("Warning: No echem data available")

        has_xrd = any(s.oned or s.twod for s in scans)
        has_neutron = any(s.neutron_files for s in scans)

        if not has_xrd and not has_neutron:
            errors.append("No XRD or neutron data found in scans")

        return errors


class NXSWriter:
    """ Writes NXS files """

    def write(self, output_path: str, scans, echem_df: pd.DataFrame) -> None:
        """Write processed data to NXS file."""

        reader_factory = DataReaderFactory()

        with h5py.File(output_path, 'w') as f:
            # Set root attributes
            f.attrs['NX_class'] = 'NXroot'
            f.attrs['file_name'] = os.path.basename(output_path)
            f.attrs['file_time'] = pd.Timestamp.now().isoformat()

            # Process each scan
            for scan in scans:
                # Create entry for each scan
                scan_entry = f.create_group(f'scan_{scan.scan_num:04d}')
                scan_entry.attrs['NX_class'] = 'NXentry'
                scan_entry.attrs['scan_number'] = scan.scan_num

                # Metadata group
                metadata = scan_entry.create_group('metadata')
                metadata.attrs['NX_class'] = 'NXcollection'

                if scan.echem is not None:
                    metadata.create_dataset('voltage (V)', data=scan.echem)

                if scan.current is not None:
                    metadata.create_dataset('current (mA)', data=scan.current)

                if scan.echem_timestamp:
                    metadata.create_dataset('voltage_timestamp', data=str(scan.echem_timestamp))

                if scan.timestamp:
                    metadata.create_dataset('scan_timestamp', data=str(scan.timestamp))

                if scan.timestamp_for_correlation:
                    metadata.create_dataset('midpoint_adjusted_timestamp',
                                            data=str(scan.timestamp_for_correlation))

                if scan.exposure_time is not None:
                    metadata.create_dataset('exposure_time', data=scan.exposure_time)

                # XRD data group
                if scan.oned or scan.twod:
                    xrd_group = scan_entry.create_group('xrd_data')
                    xrd_group.attrs['NX_class'] = 'NXdata'

                    # 1D data
                    if scan.oned:
                        try:
                            data_1d = reader_factory.read_file(scan.oned)
                            xrd_group.create_dataset('oned_2theta', data=data_1d[:, 0])
                            xrd_group.create_dataset('oned_intensity', data=data_1d[:, 1])
                            xrd_group.attrs['oned_source_file'] = os.path.basename(scan.oned)
                        except Exception as e:
                            logger.error(f"Error reading 1D data for scan {scan.scan_num}: {e}")
                            xrd_group.attrs['oned_source_file'] = os.path.basename(scan.oned)

                    # 2D data
                    if scan.twod:
                        basename = os.path.basename(scan.twod)
                        ext = os.path.splitext(basename)[1].lower()

                        if ext in ['.hdf']:
                            # For HDF files, only store the basename
                            xrd_group.attrs['twod_source_file'] = basename
                            xrd_group.attrs['twod_is_hdf'] = True
                        else:
                            # For other formats, try to read the data
                            try:
                                data_2d = reader_factory.read_file(scan.twod)
                                xrd_group.create_dataset('twod_image', data=data_2d)
                                xrd_group.attrs['twod_source_file'] = basename
                                xrd_group.attrs['twod_is_hdf'] = False
                            except Exception as e:
                                logger.error(f"Error reading 2D data for scan {scan.scan_num}: {e}")
                                xrd_group.attrs['twod_source_file'] = basename

                # Neutron data
                if scan.neutron_files:
                    neutron_group = scan_entry.create_group('neutron_data')
                    neutron_group.attrs['NX_class'] = 'NXdata'

                    if scan.neutron_start:
                        neutron_group.attrs['start_time'] = scan.neutron_start
                    if scan.neutron_end:
                        neutron_group.attrs['end_time'] = scan.neutron_end

                    # Process each measurement
                    for meas_num, meas_files in scan.neutron_files.items():
                        bank_group = neutron_group.create_group(f'bank_{meas_num}')
                        bank_group.attrs['measurement_number'] = meas_num

                        # TOF data
                        if 'tof' in meas_files:
                            try:
                                reader = DATReader("neutron")
                                tof_data = reader.read(meas_files['tof'])
                                bank_group.create_dataset('tof', data=tof_data[:, 0])
                                bank_group.create_dataset('tof_intensity', data=tof_data[:, 1])
                                bank_group.attrs['tof_source_file'] = os.path.basename(meas_files['tof'])
                            except Exception as e:
                                logger.error(f"Error reading TOF data: {e}")
                                bank_group.attrs['tof_source_file'] = os.path.basename(meas_files['tof'])

                        # d-spacing data
                        if 'd' in meas_files:
                            try:
                                reader = DATReader("neutron")
                                d_data = reader.read(meas_files['d'])
                                bank_group.create_dataset('d_spacing', data=d_data[:, 0])
                                bank_group.create_dataset('d_intensity', data=d_data[:, 1])
                                bank_group.attrs['d_source_file'] = os.path.basename(meas_files['d'])
                            except Exception as e:
                                logger.error(f"Error reading d-spacing data: {e}")
                                bank_group.attrs['d_source_file'] = os.path.basename(meas_files['d'])

            # Global metadata
            global_meta = f.create_group('global_metadata')
            global_meta.attrs['NX_class'] = 'NXcollection'
            global_meta.attrs['total_scans'] = len(scans)

            # Store echem data globally
            if not echem_df.empty:
                echem_group = f.create_group('electrochemistry')
                echem_group.attrs['NX_class'] = 'NXdata'

                # Convert timestamps to strings
                timestamps = echem_df['timestamp'].astype(str).values
                echem_group.create_dataset('timestamps', data=timestamps)
                echem_group.create_dataset('voltage (V)', data=echem_df['echem_data'].values)

                if 'current' in echem_df.columns:
                    echem_group.create_dataset('current (mA)', data=echem_df['current'].values)

        logger.info(f"NXS file successfully written to {output_path}")


# ============================================================================
# Main
# ============================================================================
def main():
    """Main entry point."""
    root = tk.Tk()
    app = NXSGeneratorGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
