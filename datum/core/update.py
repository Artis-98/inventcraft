"""Finding, fetching and staging a new version of InventCraft.

The shape of the problem decides the shape of the solution.  InventCraft itself
is about four megabytes of Python; the Qt and OpenCASCADE runtime under it
is closer to seven hundred.  So an update that ships the whole application
again would be a seven hundred megabyte download to fix a typo, and nobody
would ever take one.  Instead every release publishes a manifest listing
each file with its hash, and an update downloads only the files whose
hashes changed.  A Python-only release is a few megabytes; Qt and
OpenCASCADE move only when the dependency itself is bumped.

Nothing here touches the running installation.  Downloads go into a
staging folder and are checked, all of them, before anything is applied,
because a half-applied update is a broken application with no way back.
The swap happens after InventCraft has exited, driven by :mod:`datum.core.swap`.

None of this runs from a source checkout.  There is nothing sensible for
an updater to do to a git working tree, so it turns itself off.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import ssl
import sys
import tarfile
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from .. import __version__

# Where releases are published.  Overridable so a release can be tried
# against a staging feed before it goes to everybody.
DEFAULT_FEED = "https://api.iiteg.com/datum/"
# Since 0.3.3 the signed feed is also on the GitHub release, where the
# downloads already are; this address always leads to the newest one.
# Asked first, with the server as the fallback, which also serves copies
# older than 0.3.3, which only know the server.
GITHUB_FEED = ("https://github.com/Artis-98/inventcraft/releases/latest/"
               "download/")
FEEDS = (GITHUB_FEED, DEFAULT_FEED)
FEED_FILE = "latest.json"

# The public half of the release signing key.  Its private half never
# leaves the machine that cuts releases and is never in this repository.
#
# This is what makes the update channel safe rather than merely encrypted.
# HTTPS proves you are talking to api.iiteg.com; it does not prove that
# what api.iiteg.com is serving came from IITEG.  An update installs code
# that then runs as the user, so the difference matters: if the host were
# ever compromised, a signature check is the thing standing between that
# and every DATUM install executing somebody else's code.
PUBLIC_KEY_HEX = \
    "fef85a4d8378f0242f337153806c79f734ce1f97894b70dcd6707ce72ce11b91"

STAGING = ".staging"
# Where a Linux archive is unpacked before what changed in it is staged.
# Inside the installation, so the files can be renamed into place rather
# than copied across filesystems.
UNPACK = ".unpack"

# Files that live in the installation but are not part of a build, so a
# release that does not mention them is not asking for them to go.
#
# The uninstaller is the one that matters.  Inno Setup writes unins000.exe
# and unins000.dat into the install folder after the build is made, so
# they are in no manifest, and treating "not in the manifest" as "delete"
# would quietly destroy the uninstaller on the very first update and leave
# DATUM permanently listed in Add or Remove Programs with nothing behind
# it.
KEEP_ALWAYS = ("unins", "datum-update-")
PLAN_FILE = "update-plan.json"
TIMEOUT = 30.0
CHUNK = 256 * 1024


class UpdateError(Exception):
    """Something went wrong that the person should be told about."""


# ------------------------------------------------------------------ versions


def parse_version(text: str) -> Tuple[int, ...]:
    """A version as numbers, so 0.2.10 sorts above 0.2.9.

    Anything that is not a plain number stops the parse rather than
    guessing: 0.3.0-beta1 compares as 0.3.0, which is near enough for
    deciding whether a release is newer and much better than throwing.
    """
    parts: List[int] = []
    for piece in str(text or "0").split("."):
        digits = ""
        for char in piece:
            if not char.isdigit():
                break
            digits += char
        if not digits:
            break
        parts.append(int(digits))
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts)


def is_newer(candidate: str, current: str = __version__) -> bool:
    return parse_version(candidate) > parse_version(current)


# ------------------------------------------------------------- where we live


def frozen() -> bool:
    """Whether this is an installed build rather than a source checkout."""
    return bool(getattr(sys, "frozen", False))


def install_dir() -> str:
    """The folder the application was installed into."""
    if frozen():
        return os.path.dirname(os.path.abspath(sys.executable))
    # a source checkout: the repository root, two levels up from here
    return os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))))


def can_update() -> Tuple[bool, str]:
    """Whether updating makes sense here, and why not when it does not."""
    if not frozen():
        return (False, "InventCraft is running from source; use git instead")
    if sys.platform != "win32" and not sys.platform.startswith("linux"):
        return (False, "there is no update feed for this system; download "
                       "the new build from datum.iiteg.com")
    target = install_dir()
    if not os.access(target, os.W_OK):
        return (False, "%s is not writable by this account" % target)
    return (True, "")


# -------------------------------------------------------------------- hashing


def file_hash(path: str) -> str:
    """The SHA256 of a file, or "" when it is not there."""
    digest = hashlib.sha256()
    try:
        with open(path, "rb") as handle:
            for block in iter(lambda: handle.read(CHUNK), b""):
                digest.update(block)
    except OSError:
        return ""
    return digest.hexdigest()


def hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def manifest_of(folder: str, skip: Sequence[str] = (STAGING,)) -> Dict:
    """Every file under a folder, with its size and hash.

    Paths are stored relative and with forward slashes, so a manifest
    written on one machine means the same thing on another.
    """
    files: Dict[str, Dict] = {}
    root = os.path.abspath(folder)
    for base, dirs, names in os.walk(root):
        dirs[:] = [d for d in dirs if d not in skip]
        for name in names:
            full = os.path.join(base, name)
            relative = os.path.relpath(full, root).replace(os.sep, "/")
            files[relative] = {"size": os.path.getsize(full),
                               "sha256": file_hash(full)}
    return {"files": files}


# ------------------------------------------------------------------- signing


def verify(data: bytes, signature_hex: str,
           public_key_hex: str = "") -> bool:
    """Whether a signature really is this key's signature over these bytes.

    An unset public key means the build was made before signing was set up.
    That is allowed, so the machinery can be put in place and turned on
    afterwards, but it is reported by :func:`signing_enabled` rather than
    passing quietly as though it had been checked.
    """
    key_hex = public_key_hex or PUBLIC_KEY_HEX
    if not key_hex:
        return True
    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric.ed25519 import (
            Ed25519PublicKey)
    except ImportError:
        # Refusing is the only safe answer.  A build that was told to check
        # signatures and cannot must not fall back to trusting the server.
        return False
    try:
        key = Ed25519PublicKey.from_public_bytes(bytes.fromhex(key_hex))
        key.verify(bytes.fromhex(signature_hex), data)
        return True
    except (InvalidSignature, ValueError, TypeError):
        return False


def signing_enabled() -> bool:
    return bool(PUBLIC_KEY_HEX)


# ------------------------------------------------------------------ fetching


# Where Linux distributions keep their trusted certificates.  The Linux
# build is made on Ubuntu and its OpenSSL looks where Ubuntu keeps them,
# so on Fedora and others it trusted nothing and every update check
# failed with CERTIFICATE_VERIFY_FAILED (GitHub #7).
CA_FILES = (
    "/etc/ssl/certs/ca-certificates.crt",                  # Debian, Arch
    "/etc/pki/tls/certs/ca-bundle.crt",                    # Fedora, RHEL
    "/etc/pki/ca-trust/extracted/pem/tls-ca-bundle.pem",   # Fedora, RHEL
    "/etc/ssl/ca-bundle.pem",                              # openSUSE
    "/etc/ssl/cert.pem",                                   # Alpine, Void
)


def _context() -> ssl.SSLContext:
    context = ssl.create_default_context()
    if sys.platform == "win32":
        return context      # the Windows certificate store, always there
    candidates = []
    try:
        import certifi      # shipped with the Linux build
        candidates.append(certifi.where())
    except ImportError:
        pass
    candidates.extend(CA_FILES)
    for path in candidates:
        if path and os.path.isfile(path):
            try:
                context.load_verify_locations(cafile=path)
                break
            except (OSError, ssl.SSLError):
                continue
    return context


def _opener():
    return urllib.request.build_opener(
        urllib.request.HTTPSHandler(context=_context()))


def fetch(url: str, timeout: float = TIMEOUT) -> bytes:
    """Get a URL, insisting on HTTPS."""
    if not url.lower().startswith("https://"):
        raise UpdateError("refusing to fetch an update over %s"
                          % (url.split(":", 1)[0] or "an unknown scheme"))
    request = urllib.request.Request(
        url, headers={"User-Agent": "InventCraft/%s" % __version__})
    try:
        with _opener().open(request, timeout=timeout) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        raise UpdateError("%s said %s" % (url, exc.code)) from exc
    except (urllib.error.URLError, OSError, ssl.SSLError) as exc:
        raise UpdateError("cannot reach %s: %s" % (url, exc)) from exc


def fetch_signed(base: str, name: str, timeout: float = TIMEOUT) -> bytes:
    """A published file, with its signature checked before it is believed."""
    data = fetch(urllib.parse.urljoin(base, name), timeout)
    if not signing_enabled():
        return data
    signature = fetch(urllib.parse.urljoin(base, name + ".sig"),
                      timeout).decode("ascii", "replace").strip()
    if not verify(data, signature):
        raise UpdateError(
            "%s is not signed by IITEG's release key, so it has not been "
            "trusted.  Nothing has been changed." % name)
    return data


# ------------------------------------------------------------------- the feed


@dataclass
class Release:
    """What the feed says the newest version is."""

    version: str = ""
    released: str = ""
    notes: str = ""
    manifest: str = ""          # relative to the feed
    installer: str = ""         # a full reinstall, for big jumps
    minimum: str = "0.0.0"      # older than this cannot be patched forward
    base: str = ""
    # A build that comes as one archive off the GitHub release rather
    # than file by file off the server: Linux always, Windows from 0.3.1.
    # Its hash is in the signed feed, so the archive is as trusted as
    # everything else wherever it is hosted.
    package: str = ""
    package_sha256: str = ""
    package_size: int = 0

    @property
    def newer(self) -> bool:
        return is_newer(self.version)

    @property
    def needs_reinstall(self) -> bool:
        """Whether the jump is too far to patch and wants the installer."""
        return parse_version(__version__) < parse_version(self.minimum)

    @classmethod
    def from_dict(cls, data: Dict, base: str,
                  platform: str = "") -> "Release":
        """What the feed offers this system.

        Linux takes the feed's ``linux`` entry, which is added once the
        archive has been built, so until then a Linux copy is simply not
        offered anything.  Windows takes the ``windows`` entry when there
        is one, the whole build as one archive on the GitHub release, and
        otherwise the release the feed is about, file by file off the
        server, which is all a copy older than 0.3.1 knows how to read;
        ``platform`` "files" reads it that way on purpose.
        """
        system = platform or sys.platform
        entry = None
        if system.startswith("linux"):
            entry = data.get("linux")
            entry = entry if isinstance(entry, dict) else {}
        elif system != "files" and isinstance(data.get("windows"), dict) \
                and data["windows"].get("url"):
            entry = data["windows"]
        if entry is not None:
            try:
                size = int(entry.get("size", 0) or 0)
            except (TypeError, ValueError):
                size = 0
            return cls(version=str(entry.get("version", "")),
                       released=str(entry.get("released",
                                              data.get("released", ""))),
                       notes=str(entry.get("notes", data.get("notes", ""))),
                       minimum=str(entry.get("minimum", "0.0.0")),
                       base=base,
                       package=str(entry.get("url", "")),
                       package_sha256=str(entry.get("sha256", "")),
                       package_size=size)
        return cls(version=str(data.get("version", "")),
                   released=str(data.get("released", "")),
                   notes=str(data.get("notes", "")),
                   manifest=str(data.get("manifest", "")),
                   installer=str(data.get("installer", "")),
                   minimum=str(data.get("minimum", "0.0.0")),
                   base=base)


def check(feed: str = DEFAULT_FEED,
          fetcher: Optional[Callable[[str, str], bytes]] = None,
          platform: str = "") -> Release:
    """Ask the feed what the newest release is.

    The usual feed is asked on GitHub first and on the server when GitHub
    cannot be reached or has no feed; any other feed, a test one, is asked
    alone.  Either way the feed is signed, so where it came from does not
    decide whether it is believed.

    ``fetcher`` exists so this can be tested without a network: it is
    handed the base and the file name and gives back the bytes.
    """
    if not feed or feed == DEFAULT_FEED:
        failures = []
        for candidate in FEEDS:
            try:
                return _check_one(candidate, fetcher, platform)
            except UpdateError as exc:
                failures.append(exc)
        raise failures[-1] if len(failures) == 1 else UpdateError(
            "; ".join(str(f) for f in failures))
    return _check_one(feed, fetcher, platform)


def _check_one(feed: str,
               fetcher: Optional[Callable[[str, str], bytes]],
               platform: str) -> Release:
    base = feed if feed.endswith("/") else feed + "/"
    get = fetcher or (lambda b, n: fetch_signed(b, n))
    try:
        data = json.loads(get(base, FEED_FILE).decode("utf-8"))
    except UpdateError:
        raise
    except (ValueError, UnicodeDecodeError) as exc:
        raise UpdateError("the update feed is not readable: %s" % exc)
    if not isinstance(data, dict) or not data.get("version"):
        raise UpdateError("the update feed named no version")
    return Release.from_dict(data, base, platform)


# --------------------------------------------------------------- the diffing


@dataclass
class Plan:
    """What an update would actually do, worked out before it does it."""

    version: str = ""
    target: str = ""
    download: List[str] = field(default_factory=list)   # relative paths
    delete: List[str] = field(default_factory=list)
    unchanged: int = 0
    bytes_needed: int = 0
    files: Dict[str, Dict] = field(default_factory=dict)

    @property
    def empty(self) -> bool:
        return not self.download and not self.delete

    def summary(self) -> str:
        if self.empty:
            return "everything is already up to date"
        parts = []
        if self.download:
            parts.append("%d file(s), %s" % (len(self.download),
                                             human(self.bytes_needed)))
        if self.delete:
            parts.append("%d removed" % len(self.delete))
        return " and ".join(parts)


def human(count: float) -> str:
    for unit in ("B", "kB", "MB", "GB"):
        if count < 1024 or unit == "GB":
            return "%.0f %s" % (count, unit) if unit == "B" \
                else "%.1f %s" % (count, unit)
        count /= 1024.0
    return "%.1f GB" % count


def plan_for(manifest: Dict, target: str, version: str = "",
             keep: Sequence[str] = (STAGING,)) -> Plan:
    """Which files this installation would have to fetch, and which to drop.

    Compared by hash rather than by timestamp, because a timestamp says
    when a file was written and this needs to know whether its contents are
    the ones the release is made of.
    """
    wanted = manifest.get("files") or {}
    if not isinstance(wanted, dict) or not wanted:
        raise UpdateError("the release manifest lists no files")

    plan = Plan(version=version or str(manifest.get("version", "")),
                target=os.path.abspath(target), files=wanted)
    for relative, entry in sorted(wanted.items()):
        if not _safe_relative(relative):
            raise UpdateError("the manifest names a path outside the "
                              "installation: %s" % relative)
        local = os.path.join(plan.target, relative.replace("/", os.sep))
        if file_hash(local) == str(entry.get("sha256", "")):
            plan.unchanged += 1
            continue
        plan.download.append(relative)
        plan.bytes_needed += int(entry.get("size", 0) or 0)

    here = manifest_of(plan.target, skip=keep)["files"]
    for relative in sorted(here):
        if relative in wanted or _keep(relative):
            continue
        plan.delete.append(relative)
    return plan


def _keep(relative: str) -> bool:
    """Whether a file that is not in the manifest should be left alone."""
    name = relative.rsplit("/", 1)[-1].lower()
    return any(name.startswith(prefix) for prefix in KEEP_ALWAYS)


def _safe_relative(relative: str) -> bool:
    """Whether a manifest path stays inside the folder it belongs to.

    A release is signed, so a hostile path should never arrive.  It is
    checked anyway: this code deletes and overwrites files, and "the
    signature would have caught it" is not a reason to hand a path
    straight to the filesystem.
    """
    if not relative or relative.startswith(("/", "\\")):
        return False
    if ":" in relative:
        return False
    parts = relative.replace("\\", "/").split("/")
    return ".." not in parts and "" not in parts


# ------------------------------------------------------------- the downloading


def staging_dir(target: str) -> str:
    return os.path.join(os.path.abspath(target), STAGING)


def download(plan: Plan, release: Release,
             progress: Optional[Callable[[int, int], bool]] = None,
             fetcher: Optional[Callable[[str], bytes]] = None) -> str:
    """Fetch everything the plan needs into staging, and check all of it.

    Returns the staging folder.  Raises rather than returning half a
    release: a file whose hash does not match is not written anywhere the
    swap could later find it.

    ``progress`` is called with (done, total) and may return False to
    cancel, which cleans up and raises.
    """
    staging = staging_dir(plan.target)
    clear_staging(plan.target)
    os.makedirs(staging, exist_ok=True)

    version_base = urllib.parse.urljoin(release.base,
                                        posix_dir(release.manifest))
    get = fetcher or fetch
    total = len(plan.download)
    for index, relative in enumerate(plan.download):
        entry = plan.files.get(relative) or {}
        url = urllib.parse.urljoin(version_base, urllib.parse.quote(relative))
        try:
            data = get(url)
        except UpdateError:
            clear_staging(plan.target)
            raise
        wanted = str(entry.get("sha256", ""))
        if wanted and hash_bytes(data) != wanted:
            clear_staging(plan.target)
            raise UpdateError(
                "%s did not arrive intact, so the update has been "
                "abandoned and nothing was changed." % relative)
        destination = os.path.join(staging, relative.replace("/", os.sep))
        os.makedirs(os.path.dirname(destination), exist_ok=True)
        with open(destination, "wb") as handle:
            handle.write(data)
        if progress is not None and not progress(index + 1, total):
            clear_staging(plan.target)
            raise UpdateError("the update was cancelled")

    write_plan(plan)
    return staging


def fetch_to(url: str, path: str,
             progress: Optional[Callable[[int, int], bool]] = None,
             total: int = 0, timeout: float = TIMEOUT) -> str:
    """Download a URL into a file, a piece at a time, and return its hash.

    For the Linux archive, which is a few hundred megabytes and so is not
    held in memory the way the small files of a Windows update are.
    ``progress`` gets (kilobytes done, kilobytes in all) and may return
    False to cancel.
    """
    if not url.lower().startswith("https://"):
        raise UpdateError("refusing to fetch an update over %s"
                          % (url.split(":", 1)[0] or "an unknown scheme"))
    request = urllib.request.Request(
        url, headers={"User-Agent": "InventCraft/%s" % __version__})
    digest = hashlib.sha256()
    done = 0
    try:
        with _opener().open(request, timeout=timeout) as response, \
                open(path, "wb") as out:
            length = int(response.headers.get("Content-Length") or 0)
            total = length or total
            for block in iter(lambda: response.read(CHUNK), b""):
                out.write(block)
                digest.update(block)
                done += len(block)
                if progress is not None and not progress(
                        done // 1024, max(1, total // 1024)):
                    raise UpdateError("the update was cancelled")
    except urllib.error.HTTPError as exc:
        raise UpdateError("%s said %s" % (url, exc.code)) from exc
    except (urllib.error.URLError, OSError, ssl.SSLError) as exc:
        raise UpdateError("cannot reach %s: %s" % (url, exc)) from exc
    return digest.hexdigest()


def download_package(release: Release, target: str,
                     progress: Optional[Callable[[int, int], bool]] = None,
                     fetcher: Optional[Callable[..., str]] = None) -> Plan:
    """Fetch the build's archive, check it, and stage what changed in it.

    What it leaves behind is exactly what a Windows download leaves: the
    changed files under the staging folder and the plan beside them, so
    the swap and everything after it are the same on both.
    """
    if not release.package or not release.package_sha256:
        raise UpdateError("the update feed has no build for this system")
    target = os.path.abspath(target)
    clear_staging(target)
    unpack = os.path.join(target, UNPACK)
    shutil.rmtree(unpack, ignore_errors=True)
    os.makedirs(unpack)
    archive = os.path.join(unpack, "package.tar.gz")
    try:
        got = (fetcher or fetch_to)(release.package, archive, progress,
                                    release.package_size)
        if got != release.package_sha256:
            raise UpdateError(
                "the downloaded build is not the one the signed feed "
                "describes, so it has not been trusted.  Nothing has been "
                "changed.")
        root = _unpack(archive, unpack)
        manifest = manifest_of(root)
        plan = plan_for(manifest, target, release.version,
                        keep=(STAGING, UNPACK))
        staging = staging_dir(target)
        for relative in plan.download:
            source = os.path.join(root, relative.replace("/", os.sep))
            destination = os.path.join(staging, relative.replace("/", os.sep))
            os.makedirs(os.path.dirname(destination), exist_ok=True)
            os.replace(source, destination)
        write_plan(plan)
        return plan
    except (OSError, tarfile.TarError) as exc:
        clear_staging(target)
        raise UpdateError("the new build could not be unpacked: %s"
                          % exc) from exc
    except UpdateError:
        clear_staging(target)
        raise
    finally:
        shutil.rmtree(unpack, ignore_errors=True)


def _unpack(archive: str, into: str) -> str:
    """Unpack the archive and return the application folder inside it.

    Through tarfile's "data" filter, which refuses links and paths that
    lead outside the folder and strips set-user-id bits.  The archive is
    signed for, so none of that should ever be in it; this code still
    writes files, and "the hash would have caught it" is not a reason to
    let an archive put one anywhere it likes.
    """
    # gzip for Linux, xz for Windows: whichever the archive is
    with tarfile.open(archive, "r:*") as tar:
        tar.extractall(into, filter="data")
    os.remove(archive)
    tops = [name for name in os.listdir(into)
            if os.path.isdir(os.path.join(into, name))]
    if len(tops) != 1:
        raise UpdateError("the new build is not laid out as expected")
    return os.path.join(into, tops[0])


def posix_dir(path: str) -> str:
    """The folder part of a published path, with its trailing slash."""
    head = path.replace("\\", "/").rsplit("/", 1)[0]
    return (head + "/") if head and head != path else ""


def write_plan(plan: Plan) -> str:
    """Record what the swap should do, so it does not have to work it out."""
    staging = staging_dir(plan.target)
    os.makedirs(staging, exist_ok=True)
    path = os.path.join(staging, PLAN_FILE)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump({"version": plan.version,
                   "download": plan.download,
                   "delete": plan.delete}, handle, indent=1)
    return path


def read_plan(target: str) -> Optional[Dict]:
    path = os.path.join(staging_dir(target), PLAN_FILE)
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return None


def clear_staging(target: str) -> None:
    import shutil
    shutil.rmtree(staging_dir(target), ignore_errors=True)


def pending(target: Optional[str] = None) -> Optional[str]:
    """The version waiting to be applied on restart, if there is one."""
    plan = read_plan(target or install_dir())
    return str(plan.get("version")) if plan else None
