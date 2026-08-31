# Third-party notices

Structura is free software under the **GNU General Public License, version 3 or
later**. The full text is in [`LICENSE`](LICENSE).

This program comes with ABSOLUTELY NO WARRANTY.

Everything below ships inside a built application. Nothing here is optional
reading for anyone redistributing a build: the licences require that these
notices travel with the binary.

`structura licenses` prints this same information from the running
installation, with the versions it actually has.

---

## Qt for Python (PySide6) and Qt

Used for the window.

Offered by the Qt Company under **LGPL-3.0-only OR GPL-2.0-only OR
GPL-3.0-only** (or a commercial licence). **Structura uses it under
LGPL-3.0-only.**

That is a deliberate choice rather than the path of least resistance. GPL-3.0
would also be compatible with Structura's own licence and would carry fewer
obligations, because a GPL work has to publish its complete source anyway. The
LGPL is taken instead because it is the option that obliges us to keep Qt
*replaceable* — and being obliged to keep that property is worth more than the
paperwork it costs.

- Source for the exact version: <https://download.qt.io/official_releases/QtForPython/>
- Qt sources: <https://download.qt.io/official_releases/qt/>
- LGPLv3 text: [`LICENSES/LGPL-3.0.txt`](LICENSES/LGPL-3.0.txt)
- LGPLv3 is a set of permissions on top of GPLv3, whose text is in
  [`LICENSE`](LICENSE)

You may modify Qt and reverse-engineer Structura as far as is needed to debug
those modifications.

Only the **Essentials** modules are shipped, and Structura imports three of
them — `QtCore`, `QtGui` and `QtWidgets`. The Qt *Addons* are not bundled;
several of them (Qt Charts, Qt Data Visualization, Qt 3D) are offered under GPL
or a commercial licence rather than the LGPL, so adding one would change this
document rather than the dependency list.

### Replacing Qt

Builds are distributed as a directory or a native installer — **never as a
single fused executable** — so that replacing Qt needs no rebuild:

1. Find the Qt shared libraries in the installed application directory
   (`PySide6/` on Windows and Linux, `Contents/Resources/` inside the `.app` on
   macOS).
2. Replace them with your own binary-compatible build.
3. Run the application.

**On macOS**, an application that has been signed and notarised refuses to start
once a bundled library is replaced, because the signature no longer matches.
That is a property of the platform, not of the licence. Re-sign the bundle
locally to run it:

```sh
codesign --force --deep --sign - /Applications/Structura.app
```

Failing that, rebuild: Structura's source and its complete build configuration
are public, so substituting a different PySide6 in the build environment and
running the build produces a working application.

## Shiboken

The binding layer PySide6 is built on. Same terms, same source, same
obligations as above.

## PyYAML

Used for frontmatter parsing. **MIT.**
<https://github.com/yaml/pyyaml>

## watchdog

Used for the filesystem watcher. **Apache-2.0.**
<https://github.com/gorakhargosh/watchdog>

---

## For anyone redistributing a build

- Ship this file and [`LICENSE`](LICENSE) with the application.
- Ship the application as a directory or a native installer, not as a one-file
  freeze. A fused executable makes the LGPL's relinking right impractical, and
  "the user could rebuild it from source" is a weaker answer than "the user can
  swap the file".
- Point at the source for the *exact* Qt version bundled, not at "the latest".
- If you modify Structura, say so, and pass on the same freedoms: that is what
  the GPL is for.
