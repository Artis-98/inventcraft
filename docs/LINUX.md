# InventCraft on Linux

InventCraft is built and tested automatically on Ubuntu 22.04, and its 3D
view is checked on a current Arch Linux as well, on every release. Please
report anything that does not work at
https://github.com/Artis-98/inventcraft/issues.

## Installing

Unpack the archive and run the install script inside it:

```bash
tar -xzf InventCraft-*-linux-x86_64.tar.gz
./InventCraft/install.sh
```

That copies InventCraft to `~/.local/share/InventCraft`, puts it on your
applications menu with its icon, makes it the program that opens
`.icpart`, `.icasm`, `.icdraw` and `.iccam` files (and DATUM's `.pdat`,
`.adat`, `.ddat` and `.cdat`), and adds an `inventcraft` command to
`~/.local/bin`. Nothing needs root, and nothing outside your home folder
is touched.

To run it from where you unpacked it instead, use
`./InventCraft/install.sh --here`, or skip the script and start
`./InventCraft/InventCraft` directly.

To remove it, run `~/.local/share/InventCraft/install.sh --remove`. Your
documents and settings are kept.

It needs glibc 2.31 or newer (Ubuntu 20.04, Debian 11, Fedora 32 and
anything later) and an X11 or XWayland desktop with OpenGL. On a minimal
system Qt may ask for a few libraries; on Ubuntu and Debian these cover it:

```bash
sudo apt install libxcb-cursor0 libxkbcommon-x11-0 libxcb-icccm4 \
  libxcb-image0 libxcb-keysyms1 libxcb-render-util0 libgl1 libegl1
```

## Updates

From 0.3.0 the Linux build updates itself, as the Windows one does. It
checks for a new version on start and every six hours, or at once from
File, Check for Updates. A new version is downloaded as one archive, its
hash is checked against the signed update feed, and it is put in place
when InventCraft restarts.

It can only update a folder your account can write to, which the install
script's copy always is. A copy unpacked somewhere owned by root has to be
replaced by hand.

Builds older than 0.3.0 do not update themselves: download this one and
run its install script.

## Other differences from Windows

* **SpaceMouse** support needs read access to the device. 3Dconnexion's
  own udev rule, or one granting your user the hidraw device, does that.
* Documents go in `~/Documents/InventCraft` (or `~/Documents/DATUM`, if
  you already have that folder) and settings under `~/.config`.

## If the 3D view will not start

InventCraft always runs through X11, XWayland on a Wayland desktop,
because the OpenCASCADE viewer draws into an X11 window. If it reports
that it could not get an OpenGL window, check that XWayland has working
OpenGL:

```bash
glxinfo -B
```

It should name your graphics card. Please open an issue with what it
prints, your graphics card and driver, and the output of
`echo $XDG_SESSION_TYPE $QT_QPA_PLATFORM`. To try another Qt platform
anyway, set `DATUM_QT_PLATFORM` before starting it.
