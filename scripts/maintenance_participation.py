"""Join the existing maintenance barrier for an explicit operator command.

This is opt-in and does not protect nonparticipating processes or prove that
the configured directory is shared with the application.
"""
import os
import sys

from app.maintenance_barrier import MaintenanceActive, MaintenanceBarrier


def run_guarded(command, *args):
    directory = os.environ.get('GSUB_MAINTENANCE_ROOT')
    if not directory:
        return command(*args)
    try:
        operation = MaintenanceBarrier(directory).operation()
        operation.__enter__()
    except (MaintenanceActive, OSError, ValueError, RuntimeError):
        print('Operation unavailable: maintenance active or coordination unavailable.', file=sys.stderr)
        return 1
    try:
        return command(*args)
    finally:
        operation.__exit__(None, None, None)
