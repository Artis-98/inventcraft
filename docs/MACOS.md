# InventCraft on macOS (preview)

This is a preview for Apple Silicon Macs (M1 and newer) running macOS 13
or later. It is built and tested automatically on GitHub's Macs, but
nobody at IITEG uses a Mac every day, so please report anything that does
not work at https://github.com/Artis-98/inventcraft/issues.

macOS support was contributed by [@DanWake](https://github.com/DanWake)
and [@calumk](https://github.com/calumk).

## Opening it

Unzip the download and drag `InventCraft.app` into Applications.

The app is not signed with an Apple developer account, so the first time
macOS will refuse to open it ("cannot be opened because Apple cannot check
it"). To allow it once:

1. Try to open InventCraft, and close the warning.
2. Open **System Settings, Privacy & Security**, scroll down, and click
   **Open Anyway** next to InventCraft.

Or, in Terminal:

```bash
xattr -dr com.apple.quarantine /Applications/InventCraft.app
```

## What is different from Windows

* **No automatic updates yet.** Download the new build from the GitHub
  release when one is out and replace the app.
* **Opening a file by double clicking it** in Finder is not wired up yet;
  use File, Open inside InventCraft.
* Documents go in `~/Documents/InventCraft`, and settings stay in your
  home folder.
* Intel Macs are not built yet. InventCraft runs on them from source:
  see [CONTRIBUTING.md](../CONTRIBUTING.md).
