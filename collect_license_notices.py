"""Copy project, Python and installed-distribution notices for a release build.

Run in the clean build environment. This preserves available notices; it is not
a legal compatibility check or a guarantee that vendored components are covered.
"""
from importlib import metadata
from pathlib import Path
import argparse
import re
import shutil
import sys


def collect(destination):
    root = Path(__file__).resolve().parent
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(root / "LICENSE", destination / "LICENSE")
    notices = destination / "THIRD_PARTY_NOTICES"
    notices.mkdir(parents=True, exist_ok=True)
    python_license = Path(sys.base_prefix) / "LICENSE.txt"
    if not python_license.is_file():
        raise SystemExit("Python LICENSE.txt is missing; supply the matching runtime notice before packaging.")
    python_target = notices / "Python" / "LICENSE.txt"
    python_target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(python_license, python_target)
    lines = ["# Build-environment license notices", "",
             "Python " + sys.version.split()[0], "",
             "This directory conservatively includes notices from all installed build-environment",
             "distributions, including tools that may not be redistributed. It does not relicense",
             "any component. Preserve notices already embedded in the packaged runtime too.", "",
             "Review missing notices and vendored/native components before publishing.", ""]
    for distribution in sorted(metadata.distributions(), key=lambda d: d.metadata.get("Name", "").lower()):
        name = distribution.metadata.get("Name", "unknown")
        version = distribution.version
        folder = re.sub(r"[^A-Za-z0-9_.-]", "_", name + "-" + version)
        count = 0
        for entry in distribution.files or ():
            relative = Path(str(entry))
            if relative.is_absolute() or ".." in relative.parts:
                continue
            if not any(part.lower().startswith(("license", "licence", "copying", "copyright", "notice", "third_party", "third-party")) for part in relative.parts):
                continue
            source = Path(distribution.locate_file(entry))
            if source.is_file():
                target = notices / folder / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
                count += 1
        lines.append(f"- {name} {version}: {count} notice files" + ("; REVIEW REQUIRED (none found)" if not count else ""))
    (notices / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("Collected project, Python and distribution notices for packaging.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", help="Fresh staging directory or application bundle")
    collect(parser.parse_args().destination)
