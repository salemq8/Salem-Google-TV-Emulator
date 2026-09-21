# Third-party components

Salem Google TV Emulator v1.0.1 uses Python, PySide6-Essentials/Qt, shiboken6 and packaging. PyInstaller packages the application and has its own bootloader distribution exception. Applicable notices supplied with the pinned distributions are copied into the release's `licenses/` directory; Python's license is included there too.

Qt/PySide shared libraries remain separate files and are not statically linked into Salem. Review the included license texts, distribution obligations and source availability before public redistribution. Upstream component sources are available from https://code.qt.io/ (Qt), https://code.qt.io/pyside/pyside-setup.git (PySide/shiboken), https://github.com/python/cpython (Python), https://github.com/pypa/packaging and https://github.com/pyinstaller/pyinstaller. Matching versions are recorded in `build-manifest.json`.

Microsoft runtime files supplied with the official Python/Qt wheels are included as app-local dependencies. Windows system DLLs are not copied from the developer's Windows installation.

The Windows installer uses NSIS 3.12. Its distribution notices are included as `licenses/NSIS-COPYING.txt`; the NSIS compiler/toolchain itself is not bundled. Upstream source and license information: https://nsis.sourceforge.io/.

The Android Emulator, SDK tools, system images and Microsoft OpenJDK are downloaded separately from their official providers by the existing setup workflow and are not bundled in Salem's Portable/Setup payload. Their license terms apply. SDK license acceptance requires user confirmation.

Salem's custom app icon is independent artwork, not an official Google TV or Google logo. Product ownership and Salem source licensing remain with Salem; this notice does not grant a new license to Salem's own code.
