# FLowTrack

**FLowTrack** is a desktop app for managing FL Studio project versions, notes, and backups—with optional Google Drive integration for cloud storage.  
Built with Python and CustomTkinter, it provides an easy way to organize, search, and back up your music projects.

---

## Features

- 📁 **Project Versioning:** Create, manage, and search multiple versions of your FL Studio projects.
- 📝 **Notes:** Attach detailed notes to every project version — your ideas, progress, and creative process are always saved and viewable in the GUI.
- 🔍 **Search:** Quickly find projects or versions by name or by the content of its notes. Never lose a beat or spend hours searching through windows explorer again!
- 💾 **Automatic Backups:** Keeps your work safe with easy backup and restore.
- ☁️ **Google Drive Integration:** Upload selected projects to your Google Drive for cloud backup (optional).
- 🎨 **Modern UI:** Clean, dark-themed interface.

---

## Getting Started

### 1. Download

- Download the latest release `.exe` from [Releases](https://github.com/nirvairkataria/FLowTrack/releases)  
  *(or build from source—see below)*

### 2. First Run

- When uploading your first .flp file or creating a new project through the GUI, you’ll be prompted to select your FL Studio executable. 
    - The FL Studio executable is usually called "FL64" and by default is located in C:\Program Files\Image-Line\FL Studio 2024. 
    - This will allow FL Studio to automatically launch when creating new projects or double-clicking on any beat file!
- The app will create a `backups` folder for your projects in the same directory as the application.

### 3. Google Drive Integration (Optional)

To use Google Drive features, the app requires a `client_secrets.json` file:

- **If using the pre-built `.exe`:**  
  Google Drive should work out of the box (if bundled).  
  If not, see below.

- **If building from source:**  
  1. Go to the [Google Cloud Console](https://console.cloud.google.com/).
  2. Create a project, enable the Google Drive API, and download your `client_secrets.json`.
  3. Place it in the same folder as `flowtrack_gui.py`.
  4. (See `client_secrets_TEMPLATE.json` for the required format.)

### Please note
If you are using a version of FL Studio **older than 24.1.1**, you must build the project from source and replace the `empty_template.flp` file with an empty project file created from your own version of FL Studio, in order to be able to create new projects directly from the FLowTrack application. Otherwise, you must manually upload flp files after creating them through FL Studio.

This application only works on Windows and has only been tested on Windows 11 and 10. It may not be compatible with older versions of Windows. 