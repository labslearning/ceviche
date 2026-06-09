#!/usr/bin/env python
"""Django's command-line utility for administrative tasks."""
import os
import sys
from pathlib import Path

def main():
    """Run administrative tasks."""
    # --- FIX CRÍTICO DE ARQUITECTURA ---
    # Obtenemos la ruta absoluta donde está este archivo (backend/manage.py)
    current_path = Path(__file__).resolve().parent
    # Obtenemos la carpeta padre (ceviche_platform)
    project_root = current_path.parent
    
    # Agregamos la raíz al sys.path. 
    # Esto permite hacer imports como 'from backend.apps import...' sin errores.
    sys.path.append(str(project_root))
    # -----------------------------------

    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.config.settings')
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc
    execute_from_command_line(sys.argv)

if __name__ == '__main__':
    main()
