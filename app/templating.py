"""Gemeinsame Jinja2Templates-Instanz für main.py und admin.py.

Eigenes Modul statt Import aus main.py, damit admin.py main.py nicht
importieren muss (main.py bindet admin.py als Router ein - ein Import in
die andere Richtung wäre ein Zirkelimport).
"""
import pathlib

from fastapi.templating import Jinja2Templates

TEMPLATES_DIR = pathlib.Path(__file__).resolve().parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
