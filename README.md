# PrimeHub

PrimeHub is a Windows desktop game hub for installing, updating, and launching the available PC and Android releases.

## Features
- Dark desktop interface with PC and Android catalog tabs.
- Installs SkyRealm and PrimeLauncher for Windows from the official SkyRealm-PC-Launcher release.
- Downloads the PrimeLauncher Mobile APK from its official mobile release.
- Checks installed games for newer versions.
- Keeps installed games under `%LOCALAPPDATA%\PrimeHub\Games`.
- Checks for PrimeHub updates from this repository's own latest GitHub Release. The release must include an asset named `PrimeHub.exe`.
- Open registration and login using the SkyRealm Auth API, with email verification.
- Separate Apocalypse entry card that launches the dedicated SkyRealm Apocalypse mode.

## Build
1. Install Python 3 and PyInstaller: `py -m pip install pyinstaller`.
2. Run `build.bat`.
3. The build creates `PrimeHub.exe` in this directory and copies it to the current user's Desktop.

## Files
- `primehub.py` — application source.
- `build.bat` — Windows build script.
- `PrimeHub.spec` — PyInstaller specification.

## Current limitations
- Android APK download is supported; installing it still requires opening the APK on an Android device.
- A SkyRealm Android APK is not listed until an official release is published.
- The self-updater becomes active after a `PrimeHub.exe` asset is uploaded to a release in this repository.
