"""Atlas Research: evidence-driven investment research on Hindsight."""

from importlib.metadata import version

# The installed distribution's version, so pyproject.toml is the only place it is written.
# A released image reports its tag instead (Settings.version, from ATLAS_VERSION).
__version__ = version("atlas-research")
