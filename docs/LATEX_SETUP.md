# LaTeX Setup

GETKAN-CV compiles resumes with `xelatex`. The custom document class
[getkan-cv.cls](../getkan-cv.cls) uses `fontspec` and `unicode-math`, so
`pdflatex` will not work. This document lists the required dependencies and the
install steps for Linux, macOS, and Windows.

## Required dependencies

### Commands

| Command | Purpose | Required |
| --- | --- | --- |
| `xelatex` | PDF compilation engine used by the CLI | Yes |
| `latexmk` | Multi-pass builds from the terminal and VS Code | Yes |
| `kpsewhich` | Resolves LaTeX package paths (used for verification) | Yes |
| `pdfinfo` | Page count metadata for one-page layout profiles | Optional |
| `fc-cache` | Font cache refresh for the bundled TTF fonts | Optional |

### LaTeX packages

Required by `getkan-cv.cls`:

`array`, `enumitem`, `ragged2e`, `geometry`, `fancyhdr`, `xcolor`, `iftex`
(`ifxetex`), `xifthen`, `etoolbox`, `setspace`, `fontspec`, `unicode-math`,
`fontawesome5`, `sourcesanspro`, `tcolorbox`, `parskip`, `hyperref`.

Fonts under [resume/fonts](../resume/fonts) (Roboto, FontAwesome) ship with the
repository and are loaded by path, so no system font install is needed.

## Automated install

### Linux and macOS

```bash
chmod +x scripts/install-latex.sh
./scripts/install-latex.sh
```

Options:

- `--verify-only` — check the toolchain without installing anything.
- `--dry-run` — print the commands that would run.

Supported platforms: Debian/Ubuntu (`apt-get`), Fedora/RHEL (`dnf`), Arch
(`pacman`), openSUSE (`zypper`), macOS (Homebrew + `tlmgr`).

### Windows

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install-latex.ps1
```

Options:

- `-Distribution TeXLive` — install TeX Live instead of the default MiKTeX.
- `-VerifyOnly` — check the toolchain without installing anything.
- `-DryRun` — print the commands that would run.

Run the script from an elevated (Administrator) PowerShell prompt. After the TeX
distribution is installed, open a new terminal so `PATH` updates take effect,
then re-run the script to install the LaTeX packages.

## Manual install

### Debian / Ubuntu

```bash
sudo apt-get update
sudo apt-get install -y \
    texlive-xetex \
    texlive-latex-recommended \
    texlive-latex-extra \
    texlive-fonts-recommended \
    texlive-fonts-extra \
    latexmk \
    poppler-utils \
    fontconfig
```

### Fedora / RHEL

```bash
sudo dnf install -y \
    texlive-xetex \
    texlive-collection-latexrecommended \
    texlive-collection-latexextra \
    texlive-collection-fontsrecommended \
    texlive-collection-fontsextra \
    texlive-latexmk \
    poppler-utils \
    fontconfig
```

### Arch Linux

```bash
sudo pacman -S --needed \
    texlive-xetex \
    texlive-latexrecommended \
    texlive-latexextra \
    texlive-fontsrecommended \
    texlive-fontsextra \
    texlive-binextra \
    poppler \
    fontconfig
```

`texlive-binextra` provides `latexmk`.

### openSUSE

```bash
sudo zypper install -y \
    texlive-xetex \
    texlive-collection-latexrecommended \
    texlive-collection-latexextra \
    texlive-collection-fontsrecommended \
    texlive-collection-fontsextra \
    texlive-latexmk \
    poppler-tools \
    fontconfig
```

### macOS

Full distribution (about 5 GB, includes everything):

```bash
brew install --cask mactex-no-gui
brew install poppler
```

Minimal distribution (about 100 MB, packages installed on demand):

```bash
brew install --cask basictex
brew install poppler
export PATH="/Library/TeX/texbin:$PATH"
sudo tlmgr update --self
sudo tlmgr install \
    latexmk collection-xetex collection-fontsrecommended \
    fontspec unicode-math fontawesome5 sourcesanspro tcolorbox \
    enumitem ragged2e geometry fancyhdr xcolor xifthen etoolbox \
    setspace parskip hyperref iftex
```

Add `/Library/TeX/texbin` to `PATH` permanently in `~/.zshrc`:

```bash
echo 'export PATH="/Library/TeX/texbin:$PATH"' >> ~/.zshrc
```

### Windows

MiKTeX (recommended, installs missing packages on demand):

```powershell
winget install --id MiKTeX.MiKTeX -e
```

TeX Live:

```powershell
winget install --id TeXLive.TeXLive -e
```

With Chocolatey:

```powershell
choco install miktex -y
```

Install the LaTeX packages explicitly with MiKTeX's package manager:

```powershell
mpm --admin --update-db
mpm --admin --install fontspec unicode-math fontawesome5 sourcesanspro tcolorbox
```

`pdfinfo` on Windows comes from the Poppler utilities:

```powershell
winget install --id oschwartz10612.Poppler -e
```

It is optional; the CLI skips page count metadata when it is absent.

## Verify the installation

Run the platform script in verify mode:

```bash
./scripts/install-latex.sh --verify-only
```

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install-latex.ps1 -VerifyOnly
```

Or check manually:

```bash
xelatex --version
latexmk --version
kpsewhich fontspec.sty unicode-math.sty fontawesome5.sty sourcesanspro.sty tcolorbox.sty
```

Then compile the base resume:

```bash
cd resume
latexmk -xelatex -interaction=nonstopmode -file-line-error resume.tex
```

A successful run produces `resume/resume.pdf`.

## Troubleshooting

**`xelatex not available on PATH`**
The CLI reports this when the engine is missing. Confirm with
`command -v xelatex` (Linux/macOS) or `Get-Command xelatex` (Windows). On macOS
add `/Library/TeX/texbin` to `PATH`. On Windows open a new terminal after
installing.

**`LaTeX Error: File 'fontawesome5.sty' not found`**
The extra font collection is missing. Install `texlive-fonts-extra`
(Debian/Ubuntu), `texlive-collection-fontsextra` (Fedora/openSUSE),
`texlive-fontsextra` (Arch), or run `sudo tlmgr install fontawesome5`.

**`Package fontspec Error: The font ... cannot be found`**
Run `fc-cache -fv` and confirm the TTF files exist under
[resume/fonts](../resume/fonts).

**VS Code builds with `pdflatex` instead of `xelatex`**
LaTeX Workshop defaults to `pdflatex`. The workspace settings in
[GETKAN-CV.code-workspace](../GETKAN-CV.code-workspace) and
`resume/.latexmkrc` force the `xelatex` recipe. Reload the window after
changing them.

**Stale build artifacts cause confusing errors**
Delete `resume/resume.aux`, `resume/resume.fdb_latexmk`, `resume/resume.fls`,
and `resume/resume.xdv`, then rebuild.
