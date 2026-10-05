# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""Locating and unpacking the build outputs the three deployment modes need.

The suite runs against the artifacts the release actually ships, not against the Gradle class
directories, because the packaging is part of what is under test - a merged fat jar and a per-module
tarball load components through genuinely different code paths (see ``modes.py``).

Everything here is read-only with respect to ``build/``: tarballs are unpacked into a scratch
directory so a test run can never disturb ``build/distribution``, whose exact contents the release
workflow depends on.
"""

from __future__ import annotations

import glob
import os
import shutil
import tarfile
from dataclasses import dataclass, field
from pathlib import Path


class ArtifactError(RuntimeError):
    """Raised when a required build artifact is missing or malformed."""


def repo_root() -> Path:
    """The repository root, derived from this file's location.

    Deliberately not derived from git: the suite must work inside a source archive that carries no
    .git directory at all, which is how an uncommitted working tree is shipped to CodeBuild.
    """
    return Path(__file__).resolve().parents[3]


def distribution_dir(root: Path | None = None) -> Path:
    return (root or repo_root()) / "build" / "distribution"


@dataclass
class Artifacts:
    """Resolved, unpacked build artifacts, shared by every case in a run.

    Unpacking happens once per run rather than once per case: the uberjar tarball alone is ~228 MB and
    the full set is ~3.6 GB, so per-case extraction would dominate the suite's runtime.
    """

    root: Path
    workdir: Path
    #: Absolute path of the fat jar, e.g. <workdir>/sfc-uberjar/lib/sfc-uberjar-1.11.0.jar
    uberjar: Path
    #: Module name -> unpacked module directory containing bin/ and lib/
    modules: dict[str, Path] = field(default_factory=dict)
    #: The e2e-support jar carrying E2eMetricsWriter, or None when it has not been built.
    support_jar: Path | None = None

    def module_dir(self, module: str) -> Path:
        try:
            return self.modules[module]
        except KeyError:
            raise ArtifactError(
                f"module {module!r} was not unpacked for this run; "
                f"available: {sorted(self.modules)}"
            ) from None

    def module_lib_glob(self, module: str) -> str:
        """A ``JarFiles`` entry for in-process mode.

        SFC expands a directory or a wildcard itself (InstanceFactory.expandedJarList), so pointing at
        the module's lib directory is enough and avoids naming ~460 jars explicitly.
        """
        return str(self.module_dir(module) / "lib")

    def module_launcher(self, module: str) -> Path:
        """The generated start script for a module, used to run it as an IPC service."""
        launcher = self.module_dir(module) / "bin" / module
        if not launcher.is_file():
            raise ArtifactError(f"no launcher at {launcher}")
        return launcher


def _extract(tarball: Path, into: Path) -> Path:
    """Extract ``tarball`` into ``into`` and return the single top-level directory it contained."""
    if not tarball.is_file():
        raise ArtifactError(f"missing artifact {tarball}")

    with tarfile.open(tarball) as tf:
        # Reject absolute paths and traversal before writing anything. These tarballs are produced by
        # our own build, so this is belt-and-braces rather than a real threat model, but a malformed
        # archive writing outside the scratch directory would be very confusing to debug.
        members = tf.getmembers()
        for m in members:
            target = (into / m.name).resolve()
            if not str(target).startswith(str(into.resolve()) + os.sep):
                raise ArtifactError(f"{tarball.name} contains an out-of-tree path: {m.name}")
        # filter="data" is the safe extraction mode; it exists from Python 3.12 and becomes the
        # default later, so it is requested explicitly and tolerated when absent.
        try:
            tf.extractall(into, filter="data")  # type: ignore[call-arg]
        except TypeError:
            tf.extractall(into)

    tops = {Path(m.name).parts[0] for m in members if m.name not in (".", "./")}
    if len(tops) != 1:
        raise ArtifactError(f"expected exactly one top-level directory in {tarball.name}, got {sorted(tops)}")
    return into / tops.pop()


def prepare(
    modules: list[str],
    workdir: Path,
    root: Path | None = None,
    clean: bool = True,
) -> Artifacts:
    """Unpack the uberjar plus the named per-module tarballs into ``workdir``.

    ``modules`` must include every component a case names: ``sfc-main`` for in-process and IPC mode,
    the adapter (``simulator``), and each target under test. Unpacking only what is needed keeps a
    core-tier run well under a gigabyte instead of the full 3.6 GB.
    """
    root = root or repo_root()
    dist = distribution_dir(root)
    if not dist.is_dir():
        raise ArtifactError(
            f"{dist} does not exist - run ./gradlew build first.\n"
            "  The suite runs against the released tarballs, not the Gradle class directories."
        )

    if clean and workdir.exists():
        shutil.rmtree(workdir)
    workdir.mkdir(parents=True, exist_ok=True)

    uberjar_dir = _extract(dist / "sfc-uberjar.tar.gz", workdir)
    # The jar name carries the version, which comes from settings.gradle.kts and is therefore not
    # knowable here - resolve it rather than assume it.
    jars = sorted(glob.glob(str(uberjar_dir / "lib" / "sfc-uberjar-*.jar")))
    if not jars:
        raise ArtifactError(f"no sfc-uberjar-<version>.jar under {uberjar_dir / 'lib'}")
    if len(jars) > 1:
        raise ArtifactError(f"several uberjars under {uberjar_dir / 'lib'}: {jars}")

    artifacts = Artifacts(root=root, workdir=workdir, uberjar=Path(jars[0]))

    for module in modules:
        artifacts.modules[module] = _extract(dist / f"{module}.tar.gz", workdir)

    # Optional: only in-process and IPC mode need it as a JarFiles entry. In uberjar mode it goes on
    # the classpath instead. Its absence is not fatal here so that a case which asserts no metrics
    # still runs; runner.py refuses metrics assertions when it is missing.
    support = sorted(glob.glob(str(root / "ci" / "e2e-support" / "build" / "libs" / "e2e-support-*.jar")))
    if support:
        artifacts.support_jar = Path(support[0])

    return artifacts
