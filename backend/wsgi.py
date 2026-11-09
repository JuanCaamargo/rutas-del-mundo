"""Punto de entrada de producción para Render."""
import os

from .app import app, preparar

REQUERIDAS = ("DATABASE_URL", "RDM_SECRET", "RDM_ADMIN_PASSWORD", "RDM_ADVISOR_PASSWORD")
faltantes = [nombre for nombre in REQUERIDAS if not os.environ.get(nombre)]
if faltantes:
    raise RuntimeError("Configura estas variables en Render antes de iniciar: " + ", ".join(faltantes))

preparar()
