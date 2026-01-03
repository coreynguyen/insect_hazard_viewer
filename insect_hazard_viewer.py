#!/usr/bin/env python3
"""
Clickteam Fusion EXE Asset Browser
Complete tool for extracting and viewing all assets from Clickteam games

Features:
- Full file system view (stub archive + embedded files)
- DAT image viewer with pan/zoom
- Raw file export for debugging
- PNG export with format options
- Batch export capabilities

Controls:
- Mouse wheel: Zoom in/out
- Left click drag: Pan image
- Double click: Fit to window
- +/= : Zoom in
- - : Zoom out
- 0 : Reset view
- F : Fit to window

Author: Created for game asset extraction
Version: 2.0
"""

import struct
import sys
import zlib
import mmap
import os
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from pathlib import Path
from PIL import Image, ImageTk
import threading
import pickle
import time
import io

VERSION = "2.0"

class DATImage:
    """Parser for custom DAT image format with full header analysis"""
    HEADER_SIZE = 32
    
    def __init__(self, data):
        self.data = data
        self.raw_header = data[:self.HEADER_SIZE] if len(data) >= self.HEADER_SIZE else b''
        
        # Header fields
        self.type_id = 0
        self.flags = 0
        self.unknown_02 = 0
        self.unknown_04 = 0
        self.data_size = 0
        self.width = 0
        self.height = 0
        self.format_flag = 0
        self.unknown_14 = 0
        self.unknown_18 = 0
        self.chroma_flag = 0
        self.unknown_1E = 0
        
        # Calculated values
        self.actual_width = 0
        self.has_planar_alpha = False
        self.alpha_stride = 0
        self.needs_flip = False
        self.chroma_key = None
        self.is_ck_fl = False
        
        self.parse()
    
    def parse(self):
        if len(self.data) < self.HEADER_SIZE:
            raise ValueError("Data too small for DAT header")
        
        header = self.raw_header
        
        # Parse all header fields
        self.type_id = header[0]
        self.flags = header[1]
        self.unknown_02 = struct.unpack('<H', header[0x02:0x04])[0]
        self.unknown_04 = struct.unpack('<I', header[0x04:0x08])[0]
        self.data_size = struct.unpack('<I', header[0x08:0x0C])[0]
        self.width = struct.unpack('<H', header[0x0C:0x0E])[0]
        self.height = struct.unpack('<H', header[0x0E:0x10])[0]
        self.format_flag = struct.unpack('<I', header[0x10:0x14])[0]
        self.unknown_14 = struct.unpack('<I', header[0x14:0x18])[0]
        self.unknown_18 = struct.unpack('<I', header[0x18:0x1C])[0]
        self.chroma_flag = struct.unpack('<H', header[0x1C:0x1E])[0]
        self.unknown_1E = struct.unpack('<H', header[0x1E:0x20])[0]
        
        if self.width == 0 or self.height == 0:
            raise ValueError(f"Invalid dimensions: {self.width}x{self.height}")
        
        # Check for CK+FL combination (format_flag 0x1004 = has separate alpha plane)
        self.is_ck_fl = (self.format_flag == 0x1004 and self.chroma_flag == 0x8000)
        
        # Determine actual width (handle 2-byte row alignment for BGR data)
        aligned_width = self.width + (self.width % 2)
        bgr_exact = self.width * self.height * 3
        bgr_aligned = aligned_width * self.height * 3
        
        if self.data_size == bgr_exact or (self.data_size > bgr_exact and self.data_size < bgr_aligned):
            self.actual_width = self.width
        else:
            self.actual_width = aligned_width
        
        # BGR row stride (2-byte aligned width * 3 bytes per pixel)
        self.bgr_stride = self.actual_width * 3
        
        # Alpha row stride (4-byte aligned width)
        self.alpha_stride = ((self.width + 3) // 4) * 4
        
        # Calculate expected sizes
        bgr_needed = self.bgr_stride * self.height
        alpha_needed = self.alpha_stride * self.height
        
        # Check for planar alpha:
        # - CK+FL format (0x1004) always has separate BGR + Alpha planes
        # - Standard format with extra data also has planar alpha
        if self.is_ck_fl:
            # CK+FL format: BGR plane (2-byte row aligned) + Alpha plane (4-byte row aligned)
            self.has_planar_alpha = True
            self.chroma_key = None  # Use actual alpha values, not chroma key
        elif self.chroma_flag == 0x0000 and self.data_size > bgr_needed:
            # Standard format with alpha plane
            self.has_planar_alpha = True
            self.chroma_key = None
        else:
            self.has_planar_alpha = False
            # Determine chroma key color for transparency
            if self.chroma_flag == 0x8000:
                self.chroma_key = (0, 128, 0)  # Green
            else:
                self.chroma_key = (0, 0, 0)  # Black
        
        # Flip disabled by default - user can toggle
        self.needs_flip = False
        
        self.pixel_data = self.data[self.HEADER_SIZE:]
    
    def get_header_info(self):
        """Return formatted header information"""
        info = []
        info.append(f"Header Bytes:")
        # Split header into 2 rows for readability
        info.append(f"  {self.raw_header[:16].hex().upper()}")
        info.append(f"  {self.raw_header[16:].hex().upper()}")
        info.append(f"")
        info.append(f"Type ID:      0x{self.type_id:02X} ({self.type_id})")
        info.append(f"Flags:        0x{self.flags:02X} ({self.flags})")
        info.append(f"Unknown 02:   0x{self.unknown_02:04X}")
        info.append(f"Unknown 04:   0x{self.unknown_04:08X}")
        info.append(f"Data Size:    0x{self.data_size:08X} ({self.data_size:,})")
        info.append(f"Width:        {self.width}")
        info.append(f"Height:       {self.height}")
        info.append(f"Format Flag:  0x{self.format_flag:08X}")
        info.append(f"Unknown 14:   0x{self.unknown_14:08X}")
        info.append(f"Unknown 18:   0x{self.unknown_18:08X}")
        info.append(f"Chroma Flag:  0x{self.chroma_flag:04X}")
        info.append(f"Unknown 1E:   0x{self.unknown_1E:04X}")
        info.append(f"")
        info.append(f"--- Calculated ---")
        info.append(f"Actual Width: {self.actual_width}")
        info.append(f"Planar Alpha: {self.has_planar_alpha}")
        if self.has_planar_alpha:
            info.append(f"Alpha Stride: {self.alpha_stride}")
        if self.chroma_key:
            info.append(f"Chroma Key:   RGB{self.chroma_key}")
        info.append(f"CK+FL Flags:  {self.is_ck_fl}")
        info.append(f"Apply Flip:   {self.needs_flip}")
        
        return "\n".join(info)
    
    def to_pil_image(self, force_flip=None):
        """Convert to PIL Image with optional flip override"""
        img = Image.new('RGBA', (self.width, self.height))
        pixels = img.load()
        data = self.pixel_data
        
        # Calculate BGR data size using stride (for row-aligned formats)
        bgr_stride = getattr(self, 'bgr_stride', self.actual_width * 3)
        bgr_size = bgr_stride * self.height
        
        if self.has_planar_alpha and len(data) > bgr_size:
            # Planar format: BGR data (row-aligned) followed by Alpha plane (row-aligned)
            bgr_data = data[:bgr_size]
            alpha_data = data[bgr_size:]
            alpha_stride = self.alpha_stride if self.alpha_stride > 0 else self.width
            
            for y in range(self.height):
                bgr_row_start = y * bgr_stride
                alpha_row_start = y * alpha_stride
                for x in range(self.width):
                    bgr_idx = bgr_row_start + x * 3
                    if bgr_idx + 3 <= len(bgr_data):
                        b, g, r = bgr_data[bgr_idx], bgr_data[bgr_idx+1], bgr_data[bgr_idx+2]
                    else:
                        r, g, b = 0, 0, 0
                    
                    alpha_idx = alpha_row_start + x
                    a = alpha_data[alpha_idx] if alpha_idx < len(alpha_data) else 255
                    pixels[x, y] = (r, g, b, a)
        else:
            # Chroma key format (no separate alpha)
            chroma_key = self.chroma_key or (0, 0, 0)
            
            for y in range(self.height):
                row_start = y * bgr_stride
                for x in range(self.width):
                    idx = row_start + x * 3
                    if idx + 3 <= len(data):
                        b, g, r = data[idx], data[idx+1], data[idx+2]
                        if (r, g, b) == chroma_key:
                            pixels[x, y] = (0, 0, 0, 0)
                        else:
                            pixels[x, y] = (r, g, b, 255)
                    else:
                        pixels[x, y] = (0, 0, 0, 0)
        
        # Apply flip
        do_flip = force_flip if force_flip is not None else self.needs_flip
        if do_flip:
            img = img.transpose(Image.FLIP_TOP_BOTTOM)
        
        return img


class StubArchive:
    """Parser for the stub archive (77 77 77 77 signature)"""
    
    def __init__(self, filepath):
        self.filepath = filepath
        self.files = []
        self.archive_offset = 0
    
    def scan(self):
        """Scan for and parse the stub archive"""
        with open(self.filepath, 'rb') as f:
            data = f.read()
        
        # Find PE overlay
        pe_offset = struct.unpack('<I', data[0x3C:0x40])[0]
        num_sections = struct.unpack('<H', data[pe_offset+6:pe_offset+8])[0]
        opt_header_size = struct.unpack('<H', data[pe_offset+20:pe_offset+22])[0]
        
        section_table = pe_offset + 24 + opt_header_size
        max_end = 0
        
        for i in range(num_sections):
            raw_size = struct.unpack('<I', data[section_table + i*40 + 16:section_table + i*40 + 20])[0]
            raw_ptr = struct.unpack('<I', data[section_table + i*40 + 20:section_table + i*40 + 24])[0]
            max_end = max(max_end, raw_ptr + raw_size)
        
        overlay_start = max_end
        
        # Find 77 77 77 77 signature
        sig = bytes([0x77, 0x77, 0x77, 0x77])
        sig_pos = data.find(sig, overlay_start)
        
        if sig_pos == -1:
            return []
        
        self.archive_offset = sig_pos
        
        # Parse header
        header_size = struct.unpack('<I', data[sig_pos + 8:sig_pos + 12])[0]
        file_count = struct.unpack('<I', data[sig_pos + 0x1C:sig_pos + 0x20])[0]
        
        # Parse file entries
        pos = sig_pos + header_size
        self.files = []
        
        for i in range(file_count):
            if pos + 2 > len(data):
                break
            
            name_len = struct.unpack('<H', data[pos:pos+2])[0]
            pos += 2
            
            if pos + name_len * 2 > len(data):
                break
            
            name_bytes = data[pos:pos + name_len * 2]
            try:
                filename = name_bytes.decode('utf-16le').rstrip('\x00')
            except:
                filename = f"file_{i}"
            pos += name_len * 2
            
            if pos + 8 > len(data):
                break
            
            crc = struct.unpack('<I', data[pos:pos+4])[0]
            compressed_size = struct.unpack('<I', data[pos+4:pos+8])[0]
            pos += 8
            
            data_offset = pos
            pos += compressed_size
            
            self.files.append({
                'index': i,
                'filename': filename,
                'crc': crc,
                'compressed_size': compressed_size,
                'data_offset': data_offset,
                'type': 'archive'
            })
        
        return self.files
    
    def extract_file(self, index):
        """Extract and decompress a file by index"""
        if index >= len(self.files):
            return None
        
        file_info = self.files[index]
        
        with open(self.filepath, 'rb') as f:
            f.seek(file_info['data_offset'])
            compressed = f.read(file_info['compressed_size'])
        
        try:
            return zlib.decompress(compressed)
        except:
            return compressed  # Return raw if decompression fails


class ImageScanner:
    """Fast scanner for DAT images in Clickteam EXE files"""
    
    def __init__(self, filepath):
        self.filepath = filepath
        self.images = []
        self.progress = 0
        self.status = ""
        self.complete = False
        self.cancelled = False
    
    def scan(self, progress_callback=None):
        """Scan the EXE for all DAT images"""
        start_time = time.time()
        
        file_size = os.path.getsize(self.filepath)
        
        with open(self.filepath, 'rb') as f:
            mm = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
            
            # Find PAMU header
            pamu_pos = mm.find(b'PAMU')
            start_offset = pamu_pos if pamu_pos != -1 else 0
            
            self.images = []
            
            # Phase 1: Find all zlib headers
            if progress_callback:
                progress_callback(0, "Finding compressed data blocks...")
            
            zlib_headers = []
            pos = start_offset
            
            while not self.cancelled:
                pos = mm.find(b'\x78', pos)
                if pos == -1 or pos >= file_size - 10:
                    break
                
                next_byte = mm[pos + 1]
                if next_byte in [0x01, 0x5E, 0x9C, 0xDA]:
                    if (0x78 * 256 + next_byte) % 31 == 0:
                        zlib_headers.append(pos)
                
                pos += 1
                
                if len(zlib_headers) % 5000 == 0 and progress_callback:
                    pct = min(25, int((pos - start_offset) * 25 / (file_size - start_offset)))
                    progress_callback(pct, f"Finding blocks... {len(zlib_headers):,} found")
            
            if self.cancelled:
                mm.close()
                return []
            
            # Phase 2: Test each zlib block for DAT image
            total_headers = len(zlib_headers)
            
            for i, zpos in enumerate(zlib_headers):
                if self.cancelled:
                    break
                
                if progress_callback and i % 500 == 0:
                    pct = 25 + int(i * 75 / total_headers)
                    progress_callback(pct, f"Analyzing {i:,}/{total_headers:,} blocks... {len(self.images)} images found")
                
                try:
                    chunk_end = min(zpos + 5000000, file_size)
                    chunk = mm[zpos:chunk_end]
                    
                    decompressor = zlib.decompressobj()
                    decompressed = decompressor.decompress(chunk, 20000000)
                    
                    if len(decompressed) >= 32:
                        w = struct.unpack('<H', decompressed[0x0C:0x0E])[0]
                        h = struct.unpack('<H', decompressed[0x0E:0x10])[0]
                        ds = struct.unpack('<I', decompressed[0x08:0x0C])[0]
                        format_flag = struct.unpack('<I', decompressed[0x10:0x14])[0]
                        chroma_flag = struct.unpack('<H', decompressed[0x1C:0x1E])[0]
                        
                        if 2 <= w <= 8192 and 2 <= h <= 8192:
                            expected_bgr = w * h * 3
                            expected_bgra = w * h * 4
                            actual_data = len(decompressed) - 32
                            
                            if (abs(ds - expected_bgr) <= expected_bgr * 0.3 or
                                abs(ds - expected_bgra) <= expected_bgra * 0.3 or
                                abs(actual_data - expected_bgr) <= expected_bgr * 0.3 or
                                abs(actual_data - expected_bgra) <= expected_bgra * 0.3):
                                
                                compressed_size = len(chunk) - len(decompressor.unused_data)
                                
                                self.images.append({
                                    'offset': zpos,
                                    'compressed_size': compressed_size,
                                    'decompressed_size': len(decompressed),
                                    'width': w,
                                    'height': h,
                                    'data_size': ds,
                                    'format_flag': format_flag,
                                    'chroma_flag': chroma_flag,
                                    'type': 'image'
                                })
                
                except (zlib.error, struct.error):
                    pass
                except Exception:
                    pass
            
            mm.close()
        
        self.complete = True
        elapsed = time.time() - start_time
        
        if progress_callback:
            progress_callback(100, f"Complete! Found {len(self.images)} images in {elapsed:.1f}s")
        
        return self.images
    
    def get_raw_data(self, index):
        """Get raw decompressed data for an image"""
        if index >= len(self.images):
            return None
        
        img_info = self.images[index]
        
        with open(self.filepath, 'rb') as f:
            f.seek(img_info['offset'])
            compressed = f.read(img_info['compressed_size'] + 1000)
        
        try:
            return zlib.decompress(compressed)
        except:
            return None
    
    def get_image(self, index, force_flip=None):
        """Extract and decode a single image"""
        data = self.get_raw_data(index)
        if data is None:
            return None, None
        
        try:
            dat = DATImage(data)
            return dat.to_pil_image(force_flip=force_flip), dat
        except Exception as e:
            print(f"Error decoding image {index}: {e}")
            return None, None
    
    def save_cache(self, cache_path):
        """Save image index to cache"""
        with open(cache_path, 'wb') as f:
            pickle.dump(self.images, f)
    
    def load_cache(self, cache_path):
        """Load image index from cache"""
        if os.path.exists(cache_path):
            try:
                with open(cache_path, 'rb') as f:
                    self.images = pickle.load(f)
                    self.complete = True
                    return True
            except:
                pass
        return False


class AssetBrowserApp:
    """GUI Application for browsing and exporting EXE assets"""
    
    def __init__(self, root):
        self.root = root
        self.root.title(f"Clickteam EXE Asset Browser v{VERSION}")
        self.root.geometry("1500x950")
        
        self.image_scanner = None
        self.stub_archive = None
        self.current_image = None
        self.current_dat = None
        self.current_raw_data = None
        self.photo_image = None
        self.scan_thread = None
        self.filepath = None
        
        # Zoom and pan state
        self.zoom_level = 1.0
        self.pan_x = 0
        self.pan_y = 0
        self.drag_start_x = 0
        self.drag_start_y = 0
        self.is_dragging = False
        
        self.setup_style()
        self.setup_ui()
    
    def setup_style(self):
        """Setup dark theme"""
        style = ttk.Style()
        self.root.configure(bg='#2b2b2b')
        
        style.theme_use('clam')
        style.configure('.', background='#2b2b2b', foreground='#ffffff', fieldbackground='#3c3c3c')
        style.configure('Treeview', background='#3c3c3c', foreground='#ffffff', 
                       fieldbackground='#3c3c3c', rowheight=22)
        style.configure('Treeview.Heading', background='#4a4a4a', foreground='#ffffff')
        style.map('Treeview', background=[('selected', '#0078d4')], foreground=[('selected', '#ffffff')])
        style.configure('TProgressbar', background='#0078d4', troughcolor='#3c3c3c', thickness=20)
        style.configure('TLabelframe', background='#2b2b2b', foreground='#ffffff')
        style.configure('TLabelframe.Label', background='#2b2b2b', foreground='#ffffff')
        style.configure('TNotebook', background='#2b2b2b')
        style.configure('TNotebook.Tab', background='#3c3c3c', foreground='#ffffff', padding=[10, 5])
        style.map('TNotebook.Tab', background=[('selected', '#4a4a4a')])
    
    def setup_ui(self):
        """Setup the user interface"""
        # Menu bar
        menubar = tk.Menu(self.root)
        self.root.config(menu=menubar)
        
        file_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="File", menu=file_menu)
        file_menu.add_command(label="Open EXE...", command=self.open_exe)
        file_menu.add_command(label="Clear Cache & Rescan", command=self.clear_cache_and_rescan)
        file_menu.add_separator()
        file_menu.add_command(label="Export Selected as PNG...", command=self.export_selected_png)
        file_menu.add_command(label="Export Selected as Raw DAT...", command=self.export_selected_raw)
        file_menu.add_separator()
        file_menu.add_command(label="Export All Images as PNG...", command=self.export_all_png)
        file_menu.add_command(label="Export All Images as Raw DAT...", command=self.export_all_raw)
        file_menu.add_command(label="Export All Archive Files...", command=self.export_all_archive)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.root.quit)
        
        # View menu
        view_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="View", menu=view_menu)
        view_menu.add_command(label="Zoom In (+)", command=self.zoom_in)
        view_menu.add_command(label="Zoom Out (-)", command=self.zoom_out)
        view_menu.add_command(label="Reset View (0)", command=self.reset_view)
        view_menu.add_command(label="Fit to Window (F)", command=self.fit_to_window)
        
        # Main paned window
        self.paned = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        self.paned.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # Left panel with notebook for tabs
        left_frame = ttk.Frame(self.paned)
        self.paned.add(left_frame, weight=1)
        
        # Notebook for different views
        self.notebook = ttk.Notebook(left_frame)
        self.notebook.pack(fill=tk.BOTH, expand=True)
        
        # === Images Tab ===
        images_frame = ttk.Frame(self.notebook)
        self.notebook.add(images_frame, text="Images")
        
        # Progress frame (shown during scan)
        self.progress_frame = ttk.LabelFrame(images_frame, text="Scanning")
        self.progress_var = tk.DoubleVar(value=0)
        self.progress_bar = ttk.Progressbar(self.progress_frame, variable=self.progress_var, 
                                            maximum=100, mode='determinate')
        self.progress_bar.pack(fill=tk.X, padx=10, pady=(10, 5))
        self.progress_label = ttk.Label(self.progress_frame, text="Initializing...")
        self.progress_label.pack(pady=(0, 10))
        
        # Filter controls
        filter_frame = ttk.LabelFrame(images_frame, text="Filters")
        filter_frame.pack(fill=tk.X, pady=(0, 5))
        
        filter_inner = ttk.Frame(filter_frame)
        filter_inner.pack(fill=tk.X, padx=5, pady=5)
        
        ttk.Label(filter_inner, text="Min W:").grid(row=0, column=0, sticky='e')
        self.min_width_var = tk.StringVar(value="0")
        ttk.Entry(filter_inner, textvariable=self.min_width_var, width=6).grid(row=0, column=1, padx=2)
        
        ttk.Label(filter_inner, text="Min H:").grid(row=0, column=2, sticky='e', padx=(10, 0))
        self.min_height_var = tk.StringVar(value="0")
        ttk.Entry(filter_inner, textvariable=self.min_height_var, width=6).grid(row=0, column=3, padx=2)
        
        ttk.Label(filter_inner, text="Min Size:").grid(row=0, column=4, sticky='e', padx=(10, 0))
        self.min_size_var = tk.StringVar(value="0")
        ttk.Entry(filter_inner, textvariable=self.min_size_var, width=8).grid(row=0, column=5, padx=2)
        
        ttk.Button(filter_inner, text="Apply", command=self.apply_filter).grid(row=0, column=6, padx=(10, 0))
        
        # Image count label
        self.image_count_label = ttk.Label(images_frame, text="No images loaded")
        self.image_count_label.pack(anchor='w', pady=(0, 5))
        
        # Image list
        img_tree_frame = ttk.Frame(images_frame)
        img_tree_frame.pack(fill=tk.BOTH, expand=True)
        
        columns = ('index', 'dims', 'size', 'format', 'offset')
        self.image_tree = ttk.Treeview(img_tree_frame, columns=columns, show='headings')
        
        self.image_tree.heading('index', text='#')
        self.image_tree.heading('dims', text='Dimensions')
        self.image_tree.heading('size', text='Size')
        self.image_tree.heading('format', text='Format')
        self.image_tree.heading('offset', text='Offset')
        
        self.image_tree.column('index', width=50, anchor='e')
        self.image_tree.column('dims', width=90, anchor='c')
        self.image_tree.column('size', width=80, anchor='e')
        self.image_tree.column('format', width=70, anchor='c')
        self.image_tree.column('offset', width=90, anchor='e')
        
        img_scrollbar = ttk.Scrollbar(img_tree_frame, orient=tk.VERTICAL, command=self.image_tree.yview)
        self.image_tree.configure(yscrollcommand=img_scrollbar.set)
        
        self.image_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        img_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.image_tree.bind('<<TreeviewSelect>>', self.on_image_select)
        
        # === Archive Files Tab ===
        archive_frame = ttk.Frame(self.notebook)
        self.notebook.add(archive_frame, text="Archive Files")
        
        # Archive count label
        self.archive_count_label = ttk.Label(archive_frame, text="No files loaded")
        self.archive_count_label.pack(anchor='w', pady=5)
        
        # Archive file tree
        arch_tree_frame = ttk.Frame(archive_frame)
        arch_tree_frame.pack(fill=tk.BOTH, expand=True)
        
        arch_columns = ('filename', 'size', 'compressed', 'offset')
        self.archive_tree = ttk.Treeview(arch_tree_frame, columns=arch_columns, show='tree headings')
        
        self.archive_tree.heading('#0', text='Name')
        self.archive_tree.heading('filename', text='Filename')
        self.archive_tree.heading('size', text='Size')
        self.archive_tree.heading('compressed', text='Compressed')
        self.archive_tree.heading('offset', text='Offset')
        
        self.archive_tree.column('#0', width=200)
        self.archive_tree.column('filename', width=150)
        self.archive_tree.column('size', width=80, anchor='e')
        self.archive_tree.column('compressed', width=80, anchor='e')
        self.archive_tree.column('offset', width=90, anchor='e')
        
        arch_scrollbar = ttk.Scrollbar(arch_tree_frame, orient=tk.VERTICAL, command=self.archive_tree.yview)
        self.archive_tree.configure(yscrollcommand=arch_scrollbar.set)
        
        self.archive_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        arch_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.archive_tree.bind('<<TreeviewSelect>>', self.on_archive_select)
        
        # Right panel
        right_frame = ttk.Frame(self.paned)
        self.paned.add(right_frame, weight=2)
        
        # Info panel with header details
        info_frame = ttk.LabelFrame(right_frame, text="File Info")
        info_frame.pack(fill=tk.X, pady=(0, 5))
        
        self.info_text = tk.Text(info_frame, height=14, bg='#3c3c3c', fg='#00ff00',
                                 font=('Consolas', 9), wrap=tk.NONE)
        info_scroll_y = ttk.Scrollbar(info_frame, orient=tk.VERTICAL, command=self.info_text.yview)
        info_scroll_x = ttk.Scrollbar(info_frame, orient=tk.HORIZONTAL, command=self.info_text.xview)
        self.info_text.configure(yscrollcommand=info_scroll_y.set, xscrollcommand=info_scroll_x.set)
        
        self.info_text.grid(row=0, column=0, sticky='nsew', padx=5, pady=5)
        info_scroll_y.grid(row=0, column=1, sticky='ns', pady=5)
        info_scroll_x.grid(row=1, column=0, sticky='ew', padx=5)
        info_frame.grid_columnconfigure(0, weight=1)
        info_frame.grid_rowconfigure(0, weight=1)
        
        # Flip control
        flip_frame = ttk.Frame(right_frame)
        flip_frame.pack(fill=tk.X, pady=(0, 5))
        
        ttk.Label(flip_frame, text="Vertical Flip:").pack(side=tk.LEFT)
        self.flip_var = tk.StringVar(value="off")
        ttk.Radiobutton(flip_frame, text="Off", variable=self.flip_var, 
                       value="off", command=self.refresh_preview).pack(side=tk.LEFT, padx=5)
        ttk.Radiobutton(flip_frame, text="On", variable=self.flip_var,
                       value="on", command=self.refresh_preview).pack(side=tk.LEFT, padx=5)
        ttk.Radiobutton(flip_frame, text="Auto (header)", variable=self.flip_var,
                       value="auto", command=self.refresh_preview).pack(side=tk.LEFT, padx=5)
        
        # Preview canvas with zoom controls
        preview_frame = ttk.LabelFrame(right_frame, text="Preview")
        preview_frame.pack(fill=tk.BOTH, expand=True)
        
        # Zoom control bar
        zoom_bar = ttk.Frame(preview_frame)
        zoom_bar.pack(fill=tk.X, padx=5, pady=2)
        
        ttk.Button(zoom_bar, text="-", width=3, command=self.zoom_out).pack(side=tk.LEFT)
        self.zoom_label = ttk.Label(zoom_bar, text="100%", width=8)
        self.zoom_label.pack(side=tk.LEFT, padx=5)
        ttk.Button(zoom_bar, text="+", width=3, command=self.zoom_in).pack(side=tk.LEFT)
        ttk.Button(zoom_bar, text="Fit", width=5, command=self.fit_to_window).pack(side=tk.LEFT, padx=5)
        ttk.Button(zoom_bar, text="1:1", width=5, command=self.actual_size).pack(side=tk.LEFT)
        ttk.Button(zoom_bar, text="Reset", width=6, command=self.reset_view).pack(side=tk.LEFT, padx=5)
        
        ttk.Label(zoom_bar, text="  Mouse: Wheel=Zoom, Drag=Pan").pack(side=tk.RIGHT)
        
        self.canvas = tk.Canvas(preview_frame, bg='#1e1e1e', highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True)
        
        # Bind mouse events for pan and zoom
        self.canvas.bind('<MouseWheel>', self.on_mousewheel)
        self.canvas.bind('<Button-4>', self.on_mousewheel)
        self.canvas.bind('<Button-5>', self.on_mousewheel)
        self.canvas.bind('<ButtonPress-1>', self.on_pan_start)
        self.canvas.bind('<B1-Motion>', self.on_pan_move)
        self.canvas.bind('<ButtonRelease-1>', self.on_pan_end)
        self.canvas.bind('<Double-Button-1>', self.fit_to_window)
        
        # Keyboard shortcuts
        self.root.bind('<plus>', lambda e: self.zoom_in())
        self.root.bind('<equal>', lambda e: self.zoom_in())
        self.root.bind('<minus>', lambda e: self.zoom_out())
        self.root.bind('<0>', lambda e: self.reset_view())
        self.root.bind('<f>', lambda e: self.fit_to_window())
        self.root.bind('<F>', lambda e: self.fit_to_window())
        
        # Status bar
        self.status_var = tk.StringVar(value="Ready - Open an EXE file to scan for assets")
        status_bar = ttk.Label(self.root, textvariable=self.status_var, relief=tk.SUNKEN)
        status_bar.pack(fill=tk.X, side=tk.BOTTOM)
    
    def open_exe(self, filepath=None):
        """Open an EXE file and scan for assets"""
        if filepath is None:
            filepath = filedialog.askopenfilename(
                title="Open Clickteam Fusion EXE",
                filetypes=[("Executable files", "*.exe"), ("All files", "*.*")]
            )
        
        if not filepath:
            return
        
        self.filepath = filepath
        self.image_scanner = ImageScanner(filepath)
        self.stub_archive = StubArchive(filepath)
        
        # Scan stub archive first (fast)
        self.status_var.set("Scanning stub archive...")
        self.root.update()
        self.stub_archive.scan()
        self.populate_archive_tree()
        
        # Check for cached image index
        cache_path = filepath + ".imgcache"
        if self.image_scanner.load_cache(cache_path):
            self.status_var.set(f"Loaded {len(self.image_scanner.images):,} images from cache")
            self.populate_image_list()
            self.root.title(f"Clickteam EXE Asset Browser - {Path(filepath).name}")
            return
        
        # Start image scanning with progress
        self.start_scan(cache_path)
        self.root.title(f"Clickteam EXE Asset Browser - {Path(filepath).name}")
    
    def populate_archive_tree(self):
        """Populate the archive file tree with folder structure"""
        self.archive_tree.delete(*self.archive_tree.get_children())
        
        if not self.stub_archive or not self.stub_archive.files:
            self.archive_count_label.configure(text="No archive files found")
            return
        
        # Build folder structure
        folders = {}
        
        for file_info in self.stub_archive.files:
            filename = file_info['filename']
            parts = filename.replace('\\', '/').split('/')
            
            if len(parts) == 1:
                # Root level file
                folder_key = ''
            else:
                folder_key = '/'.join(parts[:-1])
            
            if folder_key not in folders:
                folders[folder_key] = []
            folders[folder_key].append(file_info)
        
        # Create folder nodes
        folder_nodes = {'': ''}
        
        for folder_path in sorted(folders.keys()):
            if folder_path == '':
                continue
            
            parts = folder_path.split('/')
            current_path = ''
            parent = ''
            
            for part in parts:
                current_path = f"{current_path}/{part}" if current_path else part
                
                if current_path not in folder_nodes:
                    folder_nodes[current_path] = self.archive_tree.insert(
                        folder_nodes[parent], 'end', text=f"📁 {part}",
                        values=('', '', '', ''), open=True
                    )
                parent = current_path
        
        # Add files to folders
        for folder_path, files in folders.items():
            parent_node = folder_nodes.get(folder_path, '')
            
            for file_info in files:
                filename = file_info['filename'].split('/')[-1].split('\\')[-1]
                
                # Get extension for icon
                ext = Path(filename).suffix.lower()
                if ext in ['.dll', '.exe']:
                    icon = "⚙️"
                elif ext in ['.ift', '.mfx']:
                    icon = "🔌"
                elif ext in ['.mvx', '.ccn']:
                    icon = "🎮"
                else:
                    icon = "📄"
                
                self.archive_tree.insert(
                    parent_node, 'end', 
                    iid=f"arch_{file_info['index']}",
                    text=f"{icon} {filename}",
                    values=(
                        filename,
                        f"{file_info['compressed_size']:,}",
                        f"{file_info['compressed_size']:,}",
                        f"0x{file_info['data_offset']:X}"
                    )
                )
        
        self.archive_count_label.configure(text=f"{len(self.stub_archive.files)} archive files")
    
    def on_archive_select(self, event):
        """Handle archive file selection"""
        selection = self.archive_tree.selection()
        if not selection:
            return
        
        item_id = selection[0]
        if not item_id.startswith('arch_'):
            return  # Folder selected
        
        index = int(item_id.replace('arch_', ''))
        self.preview_archive_file(index)
    
    def preview_archive_file(self, index):
        """Preview an archive file"""
        if not self.stub_archive:
            return
        
        file_info = self.stub_archive.files[index]
        data = self.stub_archive.extract_file(index)
        
        self.current_raw_data = data
        self.current_dat = None
        self.current_image = None
        
        # Update info panel
        self.info_text.delete(1.0, tk.END)
        info = []
        info.append(f"Filename:         {file_info['filename']}")
        info.append(f"Compressed Size:  {file_info['compressed_size']:,} bytes")
        info.append(f"Decompressed:     {len(data):,} bytes")
        info.append(f"CRC32:            0x{file_info['crc']:08X}")
        info.append(f"Data Offset:      0x{file_info['data_offset']:X}")
        info.append(f"")
        info.append(f"First 64 bytes (hex):")
        
        for i in range(0, min(64, len(data)), 16):
            hex_str = ' '.join(f'{data[j]:02X}' for j in range(i, min(i+16, len(data))))
            ascii_str = ''.join(chr(data[j]) if 32 <= data[j] < 127 else '.' for j in range(i, min(i+16, len(data))))
            info.append(f"  {i:04X}: {hex_str:<48} {ascii_str}")
        
        self.info_text.insert(tk.END, '\n'.join(info))
        
        # Clear preview
        self.canvas.delete("all")
        self.status_var.set(f"Archive file: {file_info['filename']}")
    
    def clear_cache_and_rescan(self):
        """Clear cache and rescan current file"""
        if not self.image_scanner:
            messagebox.showinfo("Info", "No file loaded")
            return
        
        cache_path = self.filepath + ".imgcache"
        if os.path.exists(cache_path):
            os.remove(cache_path)
        
        self.image_scanner.images = []
        self.image_scanner.complete = False
        self.image_tree.delete(*self.image_tree.get_children())
        
        self.start_scan(cache_path)
    
    def start_scan(self, cache_path):
        """Start background scan with progress updates"""
        self.progress_frame.pack(fill=tk.X, pady=5, before=self.image_count_label)
        self.progress_var.set(0)
        self.progress_label.configure(text="Initializing scan...")
        
        self.scan_thread = threading.Thread(target=self.run_scan, args=(cache_path,), daemon=True)
        self.scan_thread.start()
        
        self.check_scan_progress()
    
    def run_scan(self, cache_path):
        """Run scan in background thread"""
        def progress_callback(percent, status):
            self.progress_var.set(percent)
            self.root.after(0, lambda: self.progress_label.configure(text=status))
        
        self.image_scanner.scan(progress_callback)
        
        if self.image_scanner.complete and self.image_scanner.images:
            self.image_scanner.save_cache(cache_path)
    
    def check_scan_progress(self):
        """Check scan progress and update UI"""
        if self.image_scanner and self.image_scanner.complete:
            self.progress_frame.pack_forget()
            self.populate_image_list()
            self.status_var.set(f"Found {len(self.image_scanner.images):,} images")
        elif self.image_scanner and self.image_scanner.cancelled:
            self.progress_frame.pack_forget()
            self.status_var.set("Scan cancelled")
        else:
            self.root.after(100, self.check_scan_progress)
    
    def populate_image_list(self):
        """Populate the image list with filtering"""
        self.image_tree.delete(*self.image_tree.get_children())
        
        if not self.image_scanner:
            return
        
        try:
            min_width = int(self.min_width_var.get())
        except:
            min_width = 0
        
        try:
            min_height = int(self.min_height_var.get())
        except:
            min_height = 0
        
        try:
            min_size = int(self.min_size_var.get())
        except:
            min_size = 0
        
        displayed = 0
        for i, img in enumerate(self.image_scanner.images):
            if img['width'] < min_width or img['height'] < min_height:
                continue
            if img['decompressed_size'] < min_size:
                continue
            
            dims = f"{img['width']}x{img['height']}"
            size = f"{img['decompressed_size']:,}"
            
            # Format indicator
            fmt_parts = []
            if img.get('chroma_flag') == 0x8000:
                fmt_parts.append("CK")
            if img.get('format_flag') == 0x1004:
                fmt_parts.append("FL")
            fmt = "+".join(fmt_parts) if fmt_parts else "STD"
            
            offset = f"0x{img['offset']:X}"
            
            self.image_tree.insert('', 'end', iid=str(i), values=(i, dims, size, fmt, offset))
            displayed += 1
        
        self.image_count_label.configure(text=f"Showing {displayed:,} of {len(self.image_scanner.images):,} images")
    
    def apply_filter(self):
        """Apply filter and refresh list"""
        self.populate_image_list()
    
    def on_image_select(self, event):
        """Handle image selection"""
        selection = self.image_tree.selection()
        if not selection:
            return
        
        index = int(selection[0])
        self.preview_image(index)
    
    def get_flip_setting(self):
        """Get current flip setting"""
        flip = self.flip_var.get()
        if flip == "off":
            return False
        elif flip == "on":
            return True
        else:
            return None
    
    def preview_image(self, index):
        """Preview an image"""
        if not self.image_scanner:
            return
        
        self.status_var.set(f"Loading image {index}...")
        self.root.update()
        
        # Get raw data for potential export
        self.current_raw_data = self.image_scanner.get_raw_data(index)
        
        result = self.image_scanner.get_image(index, force_flip=self.get_flip_setting())
        
        if result[0] is None:
            self.info_text.delete(1.0, tk.END)
            self.info_text.insert(tk.END, "Failed to decode image")
            self.canvas.delete("all")
            self.status_var.set("Decode error")
            return
        
        image, dat = result
        self.current_image = image
        self.current_dat = dat
        self.current_index = index
        
        # Reset zoom and pan for new image
        self.zoom_level = 1.0
        self.pan_x = 0
        self.pan_y = 0
        self.zoom_label.configure(text="100%")
        
        # Auto-fit if image is larger than canvas
        canvas_width = self.canvas.winfo_width()
        canvas_height = self.canvas.winfo_height()
        if canvas_width > 10 and canvas_height > 10:
            if image.size[0] > canvas_width or image.size[1] > canvas_height:
                self.fit_to_window()
        
        # Update info panel with full header details
        self.info_text.delete(1.0, tk.END)
        self.info_text.insert(tk.END, dat.get_header_info())
        
        # Display image
        self.display_image(image)
        
        img_info = self.image_scanner.images[index]
        self.status_var.set(f"Image {index}: {img_info['width']}x{img_info['height']}")
    
    def refresh_preview(self):
        """Refresh preview with current flip setting"""
        if hasattr(self, 'current_index') and self.image_scanner:
            self.preview_image(self.current_index)
    
    def display_image(self, image):
        """Display an image on the canvas with zoom and pan"""
        if image.mode != 'RGBA':
            image = image.convert('RGBA')
        
        canvas_width = self.canvas.winfo_width()
        canvas_height = self.canvas.winfo_height()
        
        if canvas_width < 10:
            canvas_width = 800
        if canvas_height < 10:
            canvas_height = 600
        
        # Apply zoom
        img_width, img_height = image.size
        new_width = max(1, int(img_width * self.zoom_level))
        new_height = max(1, int(img_height * self.zoom_level))
        
        if new_width != img_width or new_height != img_height:
            resample = Image.Resampling.NEAREST if self.zoom_level > 1 else Image.Resampling.LANCZOS
            display_image = image.resize((new_width, new_height), resample)
        else:
            display_image = image
        
        # Checkerboard background for transparency
        bg = self.create_checkerboard(display_image.size)
        composite = Image.alpha_composite(bg, display_image)
        
        self.photo_image = ImageTk.PhotoImage(composite)
        
        self.canvas.delete("all")
        
        x = canvas_width // 2 + self.pan_x
        y = canvas_height // 2 + self.pan_y
        
        self.canvas.create_image(x, y, image=self.photo_image, anchor=tk.CENTER)
    
    def create_checkerboard(self, size, block_size=8):
        """Create checkerboard background for transparency display"""
        w, h = size
        img = Image.new('RGBA', (w, h))
        pixels = img.load()
        
        c1 = (100, 100, 100, 255)
        c2 = (150, 150, 150, 255)
        
        for y in range(h):
            for x in range(w):
                if ((x // block_size) + (y // block_size)) % 2 == 0:
                    pixels[x, y] = c1
                else:
                    pixels[x, y] = c2
        
        return img
    
    # Zoom and Pan Methods
    def zoom_in(self):
        self.zoom_level = min(10.0, self.zoom_level * 1.25)
        self.update_zoom_display()
    
    def zoom_out(self):
        self.zoom_level = max(0.1, self.zoom_level / 1.25)
        self.update_zoom_display()
    
    def actual_size(self):
        self.zoom_level = 1.0
        self.pan_x = 0
        self.pan_y = 0
        self.update_zoom_display()
    
    def reset_view(self):
        self.zoom_level = 1.0
        self.pan_x = 0
        self.pan_y = 0
        self.update_zoom_display()
    
    def fit_to_window(self, event=None):
        if not self.current_image:
            return
        
        canvas_width = self.canvas.winfo_width()
        canvas_height = self.canvas.winfo_height()
        
        if canvas_width < 10 or canvas_height < 10:
            return
        
        img_width, img_height = self.current_image.size
        
        scale_x = canvas_width / img_width
        scale_y = canvas_height / img_height
        self.zoom_level = min(scale_x, scale_y) * 0.95
        
        self.pan_x = 0
        self.pan_y = 0
        self.update_zoom_display()
    
    def update_zoom_display(self):
        self.zoom_label.configure(text=f"{int(self.zoom_level * 100)}%")
        if self.current_image:
            self.display_image(self.current_image)
    
    def on_mousewheel(self, event):
        if event.num == 4 or event.delta > 0:
            self.zoom_level = min(10.0, self.zoom_level * 1.1)
        elif event.num == 5 or event.delta < 0:
            self.zoom_level = max(0.1, self.zoom_level / 1.1)
        self.update_zoom_display()
    
    def on_pan_start(self, event):
        self.is_dragging = True
        self.drag_start_x = event.x - self.pan_x
        self.drag_start_y = event.y - self.pan_y
        self.canvas.configure(cursor='fleur')
    
    def on_pan_move(self, event):
        if self.is_dragging:
            self.pan_x = event.x - self.drag_start_x
            self.pan_y = event.y - self.drag_start_y
            if self.current_image:
                self.display_image(self.current_image)
    
    def on_pan_end(self, event):
        self.is_dragging = False
        self.canvas.configure(cursor='')
    
    # Export Methods
    def export_selected_png(self):
        """Export selected image as PNG"""
        if not self.current_image:
            messagebox.showinfo("Info", "No image selected")
            return
        
        if hasattr(self, 'current_index'):
            img_info = self.image_scanner.images[self.current_index]
            default_name = f"image_{self.current_index:04d}_{img_info['width']}x{img_info['height']}.png"
        else:
            default_name = "image.png"
        
        output_path = filedialog.asksaveasfilename(
            title="Export Image as PNG",
            initialfile=default_name,
            defaultextension=".png",
            filetypes=[("PNG files", "*.png"), ("All files", "*.*")]
        )
        
        if not output_path:
            return
        
        self.current_image.save(output_path, "PNG")
        self.status_var.set(f"Exported: {output_path}")
    
    def export_selected_raw(self):
        """Export selected image as raw DAT data"""
        if not self.current_raw_data:
            messagebox.showinfo("Info", "No data selected")
            return
        
        if hasattr(self, 'current_index'):
            img_info = self.image_scanner.images[self.current_index]
            default_name = f"image_{self.current_index:04d}_{img_info['width']}x{img_info['height']}.dat"
        else:
            default_name = "image.dat"
        
        output_path = filedialog.asksaveasfilename(
            title="Export Raw DAT Data",
            initialfile=default_name,
            defaultextension=".dat",
            filetypes=[("DAT files", "*.dat"), ("Binary files", "*.bin"), ("All files", "*.*")]
        )
        
        if not output_path:
            return
        
        with open(output_path, 'wb') as f:
            f.write(self.current_raw_data)
        
        self.status_var.set(f"Exported raw: {output_path}")
    
    def export_all_png(self):
        """Export all images as PNG"""
        if not self.image_scanner or not self.image_scanner.images:
            messagebox.showinfo("Info", "No images loaded")
            return
        
        output_dir = filedialog.askdirectory(title="Select Export Directory for PNG")
        if not output_dir:
            return
        
        self._batch_export(output_dir, export_png=True, export_raw=False)
    
    def export_all_raw(self):
        """Export all images as raw DAT"""
        if not self.image_scanner or not self.image_scanner.images:
            messagebox.showinfo("Info", "No images loaded")
            return
        
        output_dir = filedialog.askdirectory(title="Select Export Directory for Raw DAT")
        if not output_dir:
            return
        
        self._batch_export(output_dir, export_png=False, export_raw=True)
    
    def _batch_export(self, output_dir, export_png=True, export_raw=False):
        """Batch export with progress dialog"""
        progress_win = tk.Toplevel(self.root)
        progress_win.title("Exporting")
        progress_win.geometry("400x120")
        progress_win.transient(self.root)
        progress_win.grab_set()
        
        ttk.Label(progress_win, text="Exporting images...").pack(pady=10)
        export_progress = ttk.Progressbar(progress_win, maximum=len(self.image_scanner.images))
        export_progress.pack(fill=tk.X, padx=20, pady=5)
        export_label = ttk.Label(progress_win, text="Starting...")
        export_label.pack()
        
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        
        exported = 0
        errors = 0
        flip_setting = self.get_flip_setting()
        
        for i, img_info in enumerate(self.image_scanner.images):
            export_progress['value'] = i + 1
            export_label.configure(text=f"Exporting {i+1}/{len(self.image_scanner.images)}...")
            progress_win.update()
            
            base_name = f"image_{i:04d}_{img_info['width']}x{img_info['height']}"
            
            if export_raw:
                raw_data = self.image_scanner.get_raw_data(i)
                if raw_data:
                    with open(Path(output_dir) / f"{base_name}.dat", 'wb') as f:
                        f.write(raw_data)
                    exported += 1
                else:
                    errors += 1
            
            if export_png:
                result = self.image_scanner.get_image(i, force_flip=flip_setting)
                if result[0]:
                    result[0].save(Path(output_dir) / f"{base_name}.png", "PNG")
                    if not export_raw:
                        exported += 1
                else:
                    if not export_raw:
                        errors += 1
        
        progress_win.destroy()
        
        fmt = "PNG" if export_png else "RAW DAT"
        self.status_var.set(f"Export complete: {exported} {fmt} files, {errors} errors")
        messagebox.showinfo("Export Complete", 
                          f"Exported {exported} {fmt} files\nErrors: {errors}\n\nLocation: {output_dir}")
    
    def export_all_archive(self):
        """Export all archive files with folder structure"""
        if not self.stub_archive or not self.stub_archive.files:
            messagebox.showinfo("Info", "No archive files loaded")
            return
        
        output_dir = filedialog.askdirectory(title="Select Export Directory for Archive Files")
        if not output_dir:
            return
        
        progress_win = tk.Toplevel(self.root)
        progress_win.title("Exporting Archive")
        progress_win.geometry("400x120")
        progress_win.transient(self.root)
        progress_win.grab_set()
        
        ttk.Label(progress_win, text="Exporting archive files...").pack(pady=10)
        export_progress = ttk.Progressbar(progress_win, maximum=len(self.stub_archive.files))
        export_progress.pack(fill=tk.X, padx=20, pady=5)
        export_label = ttk.Label(progress_win, text="Starting...")
        export_label.pack()
        
        exported = 0
        errors = 0
        
        for i, file_info in enumerate(self.stub_archive.files):
            export_progress['value'] = i + 1
            export_label.configure(text=f"Exporting {i+1}/{len(self.stub_archive.files)}...")
            progress_win.update()
            
            filename = file_info['filename'].replace('\\', '/')
            output_path = Path(output_dir) / filename
            
            output_path.parent.mkdir(parents=True, exist_ok=True)
            
            data = self.stub_archive.extract_file(i)
            if data:
                with open(output_path, 'wb') as f:
                    f.write(data)
                exported += 1
            else:
                errors += 1
        
        progress_win.destroy()
        
        self.status_var.set(f"Archive export complete: {exported} files, {errors} errors")
        messagebox.showinfo("Export Complete", 
                          f"Exported {exported} archive files\nErrors: {errors}\n\nLocation: {output_dir}")


def main():
    root = tk.Tk()
    app = AssetBrowserApp(root)
    
    if len(sys.argv) > 1:
        filepath = sys.argv[1]
        if Path(filepath).exists():
            root.after(100, lambda: app.open_exe(filepath))
    
    root.mainloop()


if __name__ == '__main__':
    main()