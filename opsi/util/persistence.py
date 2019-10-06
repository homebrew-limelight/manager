import logging
from json import JSONDecodeError
from pathlib import PosixPath

from pydantic import ValidationError

from ..webserver.schema import NodeTreeN, Preferences

LOGGER = logging.getLogger(__name__)


class Persistence:
    PATHS = ("/var/lib/opensight", "~/.local/share/opensight")
    NODETREE_DIR = "nodetrees"

    def __init__(self, path=None):
        self._nodetree = None

        self._prefs = None
        self._profile = None

        self.paths = self.PATHS
        if path:
            self.paths = (path,) + self.paths

        self.base_path = self._get_path()

        # handle all preferences here
        self._profile = self.prefs.profile
        self.nodetree_path = self._get_nt_path()

    def _get_nt_path(self):
        return (
            self.base_path / self.NODETREE_DIR / f"nodetree_{self.profile}.json"
            if self.enabled
            else None
        )

    def _get_path(self):
        for path in self.paths:
            path = PosixPath(path).expanduser().resolve()  # get absolute canonical path

            try:
                LOGGER.debug("Trying path: %s", path)

                # mkdir -p and then ensure file created + write perms
                (path / self.NODETREE_DIR).mkdir(parents=True, exist_ok=True)
                for i in range(0, 10):
                    (path / self.NODETREE_DIR / f"nodetree_{i}.json").touch()
                (path / "preferences.json").touch()

            except OSError:
                LOGGER.debug("Skipping path", exc_info=True)
                continue

            else:
                LOGGER.info("Decided upon path: %s", path)

                return path

        LOGGER.error("Failed to setup persistence")
        return None

    @property
    def nodetree(self) -> NodeTreeN:
        if self._nodetree:
            return self._nodetree
        try:
            self._nodetree = NodeTreeN.parse_file(self.nodetree_path)
            return self._nodetree
        except (ValidationError, JSONDecodeError, ValueError) as e:
            LOGGER.warning("Nodetree persistence invalid, creating new NodeTree")
            LOGGER.debug(e, exc_info=True)
            return NodeTreeN()
        except OSError:
            LOGGER.exception("Failed to read from nodetree persistence")
        return None

    @nodetree.setter
    def nodetree(self, nodetree: NodeTreeN):
        if self.base_path is None:
            return
        self._nodetree = nodetree
        try:
            self.nodetree_path.write_text(nodetree.json())
        except OSError:
            LOGGER.exception("Failed to write to nodetree persistence")

    @property
    def prefs(self) -> Preferences:
        if self._prefs:
            return self._prefs
        try:
            self._prefs = Preferences.parse_file(self.base_path / "preferences.json")
            return self.prefs
        except (ValidationError, JSONDecodeError, ValueError) as e:
            LOGGER.warning(
                "Preferences persistence invalid. Creating new preferences file."
            )
            LOGGER.debug(e, exc_info=True)
            # set default preferences here
            self._prefs = Preferences(profile=0)
            return Preferences(profile=0)
        except OSError:
            LOGGER.exception("Failed to read from preferences persistence")
        return None

    @prefs.setter
    def prefs(self, prefs: Preferences):
        if self.base_path is None:
            return
        self._prefs = prefs
        try:
            (self.base_path / "preferences.json").write_text(prefs.json())
        except OSError:
            LOGGER.exception("Failed to write to preferences persistence")

    def update_nodetree(self):
        self._nodetree = None
        self.nodetree_path = self._get_nt_path()
        self.nodetree = self.nodetree  # ensure blank nodetree if not exist

    @property
    def enabled(self):
        return bool(self.base_path)

    @property
    def profile(self):
        return int(self._profile)

    @profile.setter
    def profile(self, value):
        self._profile = value
        self.nodetree_path = self._get_nt_path()
        self.prefs.profile = value
        self.prefs = self.prefs  # write to file
        LOGGER.info(f"Switching to profile {value}")