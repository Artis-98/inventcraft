"""Each kind of InventCraft file its own icon in Windows Explorer.

The installer registers them, but a copy that has only ever updated
itself never ran that, so the program registers them itself at start.
Tested against a throwaway key, never the real file associations: it
writes the same ProgIDs, icons and open command as the installer, a
second run writes nothing, and an extension another program owns is left
alone.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import harness  # noqa: E402,F401

from datum.ui import winassoc  # noqa: E402

FAILS = []


def check(name, cond, extra=""):
    print(("  PASS  " if cond else "  FAIL  ") + name
          + ("  " + str(extra) if extra and not cond else ""))
    if not cond:
        FAILS.append(name)


folder = winassoc.icon_folder()
check("the four file icons ship with the program",
      all(os.path.exists(os.path.join(folder, ico))
          for _t, ico in winassoc.PROGIDS.values()))
planned = dict(winassoc.plan(r"C:\Apps\InventCraft.exe", folder))
check("a part is IITEG.DATUM.Part, the installer's ProgID",
      planned[".icpart"] == "IITEG.DATUM.Part"
      and planned[".pdat"] == "IITEG.DATUM.Part")
check("with the part icon",
      planned["IITEG.DATUM.Part\\DefaultIcon"].endswith('part.ico"'))
check("and opens in InventCraft",
      planned["IITEG.DATUM.Assembly\\shell\\open\\command"]
      == '"C:\\Apps\\InventCraft.exe" "%1"')
check("running from source registers nothing",
      winassoc.register_if_installed() == 0)

if sys.platform == "win32":
    import winreg
    base = r"Software\IITEG-tests\Classes"

    def wipe(key):
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key, 0,
                                winreg.KEY_ALL_ACCESS) as k:
                while True:
                    try:
                        sub = winreg.EnumKey(k, 0)
                    except OSError:
                        break
                    wipe(key + "\\" + sub)
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, key)
        except OSError:
            pass

    wipe(r"Software\IITEG-tests")
    try:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER,
                              base + r"\.iccam") as k:
            winreg.SetValueEx(k, "", 0, winreg.REG_SZ, "SomeoneElse.Cam")
        n = winassoc.register(r"C:\Apps\InventCraft.exe", folder, base)
        check("the first run writes the file types", n > 10, n)
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            base + r"\IITEG.DATUM.Drawing\DefaultIcon") as k:
            icon = winreg.QueryValueEx(k, "")[0]
        check("a drawing gets the drawing icon", icon.endswith('drawing.ico"'),
              icon)
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, base + r"\.iccam") as k:
            owner = winreg.QueryValueEx(k, "")[0]
        check("an extension another program has is left alone",
              owner == "SomeoneElse.Cam", owner)
        check("a second run writes nothing",
              winassoc.register(r"C:\Apps\InventCraft.exe", folder, base) == 0)
    finally:
        wipe(r"Software\IITEG-tests")

print()
if FAILS:
    print("%d FAILURES: %s" % (len(FAILS), ", ".join(FAILS)))
    sys.exit(1)
print("all passed")
