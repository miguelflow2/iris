"""Point d'entrée de l'exécutable PyInstaller."""
import multiprocessing
import sys

from iris.__main__ import main

if __name__ == "__main__":
    multiprocessing.freeze_support()
    sys.exit(main())
