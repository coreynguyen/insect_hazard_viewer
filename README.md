# Insect Hazard Viewer

![Python](https://img.shields.io/badge/Python-3.8%2B-blue?style=for-the-badge&logo=python&logoColor=white)
![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20Linux-lightgrey?style=for-the-badge)
![License](https://img.shields.io/badge/License-MIT-green?style=for-the-badge)
![Status](https://img.shields.io/badge/Status-Stable-success?style=for-the-badge)

![Tool Preview](preview.jpg)

## 📂 Digital Archeology for Clickteam Executables

**CFAB** is a specialized extraction utility designed to break the seal on compiled **Clickteam Fusion 2.5** executables. It treats the opaque `.exe` container as a file system, locating, decoding, and exporting assets that are locked away in proprietary compression formats.

This tool was developed to handle complex archives, including verified support for **Parasites In the City** and the **H-Edition Patch** (found at `h-game.site`).

---

## ✨ Features

* **🔍 Deep Scan Engine**
    * Heuristic scanning for `zlib` compressed chunks.
    * Validates headers against internal Clickteam image structures.
* **🖼️ Hybrid Asset Viewer**
    * **Stub Archive:** Browses external files (DLLs, music, scripts) embedded in the executable overlay.
    * **Image Bank:** Decodes the proprietary `DAT` memory-mapped image format.
* **👁️ Visual Inspector**
    * Dark-mode GUI optimized for long sessions.
    * High-performance Pan & Zoom (LANCZOS resampling).
    * Transparency checkerboard rendering.
* **💾 Smart Export**
    * **Batch to PNG:** Exports all found sprites with transparency preserved.
    * **Raw DAT:** Dumps raw binary data for further reverse engineering.
    * **Archive Extraction:** Unpacks embedded binary dependencies.

---

## 🛠️ Installation

Ensure you have Python 3.8 or newer installed.

1.  **Clone the repository:**
    ```bash
    git clone [https://github.com/yourusername/cfab.git](https://github.com/yourusername/cfab.git)
    cd cfab
    ```

2.  **Install dependencies:**
    The only non-standard library required is `Pillow` for image processing.
    ```bash
    pip install Pillow
    ```

---

## 🚀 Usage

### GUI Mode
Run the script without arguments to launch the graphical interface:

```bash
python asset_browser.py
