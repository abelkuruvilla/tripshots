"""Entry point of the frozen engine (`tripshots` executable shipped with the desktop app).

The engine archive holds the executable, its libraries and a `bin/` folder with ffmpeg and ffprobe. TripShots calls
`ffmpeg` by name everywhere, so the bundled copies go first on PATH; a system ffmpeg is used when none is bundled.
"""
import multiprocessing
import os
import sys
from pathlib import Path


def _bundled_bin() -> None:
    if not getattr(sys, "frozen", False):
        return
    here = Path(sys.executable).resolve().parent
    for d in (here / "bin", here.parent / "bin"):
        if d.is_dir():
            os.environ["PATH"] = str(d) + os.pathsep + os.environ.get("PATH", "")
            return


if __name__ == "__main__":
    multiprocessing.freeze_support()
    _bundled_bin()
    from tripshots.cli import main
    main()
