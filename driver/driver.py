import threading
import logging
import httpx
from typing import Final
from dataclasses import dataclass

import epics
from state_mapper import StatePVs, run_mapper

logger = logging.getLogger(__name__)

# EPICS env vars
P: Final[str] = "EM-AUTOMATION"

# Logging configuration
LOG_LEVEL: Final[int] = logging.DEBUG

class LogPVHandler(logging.Handler):
    def __init__(self, log_pv: epics.PV, error_pv: epics.PV):
        super().__init__()
        self.log_pv = log_pv
        self.error_pv = error_pv
        self.setFormatter(logging.Formatter('DRIVER: %(message)s'))

    def emit(self, record):
        message = self.format(record)
        # TODO: Write to log PV when we determine the correct string length limit
        # For now, just log to stdout
        # self.log_pv.put(message)
        if record.levelno >= logging.ERROR:
            try:
                self.error_pv.put(1)
            except Exception:
                pass

@dataclass
class ControlPVs:
    pending: epics.PV
    error: epics.PV
    log: epics.PV

def main():
    lock = threading.Lock()
    control = ControlPVs(
        pending=epics.PV(f'{P}:PENDING'),
        error=epics.PV(f'{P}:ERROR'),
        log=epics.PV(f'{P}:Automation_Logs')
    )

    state = StatePVs(
        energy_mode=epics.PV(f'{P}:ENERGY_MODE'),
        ts_cw=epics.PV(f'{P}:TS_CW'),
        cm_cw=epics.PV(f'{P}:CM_CW')
    )

    logging.basicConfig(level=LOG_LEVEL, format='%(levelname)s: %(message)s')
    logger.addHandler(LogPVHandler(control.log, control.error))

    def on_pending(value=None, **kw):
        if value != 1:
            return
        threading.Thread(target=dispatch, daemon=True).start()

    def dispatch():
        if not lock.acquire(blocking=True):
            return
        try:
            control.pending.put(0)
            success = run_mapper(state)
            if not success:
                control.error.put(1)
        finally:
            lock.release()

    control.pending.add_callback(on_pending)
    input("Press enter to quit\n")


if __name__ == '__main__':
    main()