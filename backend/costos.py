"""Cálculo del costo estimado por persona (HU-11, HU-23).

El costo lo calcula el código, no la IA, para que sea predecible y verificable.
precio por persona = hospedaje + actividades + vuelo (si hay vuelo registrado para el origen).
- Hospedaje: una noche por cada día de viaje menos el último, a la tarifa del alojamiento de la ciudad de ese día
  (por defecto el más económico). Si una ciudad no tiene alojamientos registrados se usa RDM_TARIFA_NOCHE.
- Habitación: la tarifa registrada es por persona en habitación doble; sencilla y triple la ajustan con un factor.
"""
import os

FACTORES_HABITACION = {"sencilla": 1.35, "doble": 1.0, "triple": 0.9}  # supuestos del proyecto


def tarifa_noche():
    try:
        return float(os.environ.get("RDM_TARIFA_NOCHE", "90"))
    except ValueError:
        return 90.0


def hospedaje(noches, dias, tarifas):
    """Suma la tarifa de cada noche según la ciudad del día. tarifas: {ciudad: USD por persona en doble}."""
    base = tarifa_noche()
    return sum(tarifas.get(d["ciudad"], base) for d in dias[:noches])
