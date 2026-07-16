"""PyInstaller entry point — a real script (not the console_scripts shim)
so the frozen binary has a clean import graph."""

from poseidon.cli import main

if __name__ == "__main__":
    main()
