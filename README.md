# SceneDiet 🚀
*A lightweight, powerful Blender add-on designed to audit, manage, and clean up performance bottlenecks and file bloat in complex 3D scenes.*

![Blender Version](https://img.shields.io/badge/Blender-4.0%2B-orange?style=flat-square&logo=blender)
![License](https://img.shields.io/badge/License-MIT-blue.svg?style=flat-square)

---

## 🌟 Overview
**SceneDiet** acts as a health inspector for your Blender projects. Whether you're working on massive architectural visualizations (ArchViz) or real-time game assets, SceneDiet helps you identify, track, and purge wasted data to boost viewport performance and reduce file size.

## ✨ Key Features
* 🔍 **Smart Inspection & Bloat Detection:** Scans for orphan data (unused materials, textures, node groups), duplicate data-blocks, zero-poly meshes, and extreme polygon counts.
* 📏 **Memory Estimation:** Automatically calculates approximate VRAM/RAM footprints for textures in megabytes (MB).
* 🎯 **Interactive Viewport Highlighting:** Instantly select and pinpoint heavy meshes, suffixes, or orphaned assets directly from the sidebar panel.
* 🛡️ **Safety Rails:** Built-in name prefix protection (e.g., `DOT`) to prevent accidental bulk-deletions of critical assets, plus pre-purge safety backup integration.
* ⚙️ **Optimization Presets:** Tailor limits instantly with built-in profiles for **ArchViz** (500k poly limit) and **Game Dev** (20k poly limit).
* 📊 **Pipeline Reporting:** Export comprehensive scene health logs into structured `.json` audit reports.

---

## 📦 Installation
You can install **SceneDiet** using any of the following methods:

### Method A: Install via ZIP (Recommended for Users)
1. Download the repository source code as a `.zip` file from the main GitHub page.
2. Open Blender (v4.0 or higher).
3. Go to **Edit > Preferences > Add-ons > Install...**
4. Select the downloaded `.zip` file and click **Install Add-on**.
5. Enable **Scene: SceneDiet** in the add-on list.

### Method B: Extract & Drop / Manual Installation (For Developers)
1. Download or clone the repository and extract the files.
2. Locate your Blender add-ons directory:
   * **Windows:** `%APPDATA%\Blender Foundation\Blender\<version>\scripts\addons\`
   * **macOS:** `~/Library/Application Support/Blender/<version>/scripts/addons/`
   * **Linux:** `~/.config/blender/<version>/scripts/addons/`
3. Place `scene_diet_addon.py` directly inside that folder.
4. Open Blender, go to **Edit > Preferences > Add-ons**, and enable **Scene: SceneDiet**.

---

## 👨‍💻 Author
**Muhammad Danish Bin Idris**  
*Student & Developer*
