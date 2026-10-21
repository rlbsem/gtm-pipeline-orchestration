"""Resolve the installed dependency closure for the explicit roots; no private URLs/config."""
import importlib.metadata as metadata
from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name


def lock():
    pending = [Requirement(x).name for x in Path("requirements.txt").read_text().splitlines() if x.strip()]
    pending += ["setuptools"]
    found = {}
    while pending:
        name = canonicalize_name(pending.pop())
        if name in found:
            continue
        dist = metadata.distribution(name)
        found[name] = dist.version
        for value in dist.requires or []:
            requirement = Requirement(value)
            # Include platform-conditional dependencies for both supported CI systems.
            environments = [{"sys_platform": platform, "platform_system": system, "extra": ""}
                            for platform, system in [("win32", "Windows"), ("linux", "Linux")]]
            if requirement.marker is None or any(requirement.marker.evaluate(env) for env in environments):
                pending.append(requirement.name)
    Path("requirements.lock").write_text("# Exact dependency closure; Python 3.12 / Windows and Linux.\n" +
                                        "\n".join(f"{k}=={v}" for k, v in sorted(found.items())) + "\n")


if __name__ == "__main__":
    lock()
