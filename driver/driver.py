import threading
import epics
import logging
import httpx
from typing import Final, Any
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Type aliases
Database = dict[str, dict[str, Any]]
PVMap = dict[str, 'pvNewVal']

# API configuration
API_BASE_URL: Final[str] = "http://localhost:8000"

# EPICS env vars
P: Final[str] = "EM-AUTOMATION"

class LogPVHandler(logging.Handler):
    def __init__(self, log_pv: epics.PV, error_pv: epics.PV):
        super().__init__()
        self.log_pv = log_pv
        self.error_pv = error_pv
        self.setFormatter(logging.Formatter('DRIVER: %(message)s'))

    def emit(self, record):
        message = self.format(record)
        self.log_pv.put(message)
        if record.levelno >= logging.ERROR:
            self.error_pv.put(1)


@dataclass
class ControlPVs:
    pending: epics.PV
    error: epics.PV
    log: epics.PV

@dataclass
class StatePVs:
    energy_mode: epics.PV
    ts_cw: epics.PV
    cm_cw: epics.PV

def run_job(state: StatePVs) -> bool:
    logger.info("Working...")
    # set up own PVs, read SQL, map state, etc.

    database = read_database()
    pv_map = map_state(state, database)

    status = write_pvs(pv_map)
    if (not status):
        logger.error("Failed to write PVs")
        return False
    
    status = verify_pvs(pv_map)
    if (not status):
        logger.error("Failed to verify PVs")
        return False

    return True

def main():
    lock = threading.Lock()
    control = ControlPVs(
        pending=epics.PV(f'{P}:PENDING'),
        error=epics.PV(f'{P}:ERROR'),
        log=epics.PV(f'{P}:LOG')
    )

    state = StatePVs(
        energy_mode=epics.PV(f'{P}:ENERGY_MODE'),
        ts_cw=epics.PV(f'{P}:TS_CW'),
        cm_cw=epics.PV(f'{P}:CM_CW')
    )

    logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
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
            success = run_job(state)
            if not success:
                control.error.put(1)
        finally:
            lock.release()

    control.pending.add_callback(on_pending)
    input("Press enter to quit\n")

if __name__ == '__main__':
    main()


# -------------------------------------------------------------------------------------------------
# State + configuration mapping logic

@dataclass
pvNewVal:
    new_val: str
    pv: epics.PV

def read_database() -> Database:
    """Fetch rows from the API and return as dict of dicts keyed by PV_NAME.
    
    Returns:
        dict: {PV_NAME: {ID: ..., extra_columns...}, ...}
    """
    response = httpx.get(f"{API_BASE_URL}/rows")
    response.raise_for_status()
    rows = response.json()
    
    database = {}
    for row in rows:
        pv_name = row["PV_NAME"]
        row_data = {k: v for k, v in row.items() if k != "PV_NAME"}
        database[pv_name] = row_data
    
    return database

def map_state(state: StatePVs, database: Database) -> PVMap:
    """Map database rows to PV values based on priority-driven state rules.
    
    For each PV in the database, determines which value to write by checking
    a priority cascade in order: CW_CM > CW_TS > energy_mode (1-4).
    
    The priority check works as follows:
    1. If cw_cm == 1 and the database row has a non-empty "CW_CM" column,
       use that value.
    2. Else if cw_ts == 1 and the database row has a non-empty "CW_TS" column,
       use that value.
    3. Else if energy_mode is 1-4 and the corresponding "EM{mode}" column
       has a non-empty value, use that value.
    4. If no rule matches, log an error and skip this PV.
    
    For each PV that matches a rule, creates an epics.PV object and includes
    it in the returned map.
    
    Args:
        state: Current EPICS state (energy_mode, ts_cw, cm_cw values)
        database: Dict of {PV_NAME: {ID, CW_CM, CW_TS, EM1, EM2, ...}}
    
    Returns:
        Dict mapping PV names to pvNewVal objects with new values and PV references
    """

    energy_mode = state.energy_mode.get()
    cw_ts = state.ts_cw.get()
    cw_cm = state.cm_cw.get()

    pv_map = {}
    
    for pv_name, row in database.items():
        new_val = None
        
        # Priority 1: Check CW_CM
        if cw_cm == 1 and row.get("CW_CM", ""):
            new_val = row["CW_CM"]
        # Priority 2: Check CW_TS
        elif cw_ts == 1 and row.get("CW_TS", ""):
            new_val = row["CW_TS"]
        # Priority 3: Check energy mode (1-4)
        elif energy_mode in [1, 2, 3, 4]:
            col_name = f"EM{energy_mode}"
            if row.get(col_name, ""):
                new_val = row[col_name]
        
        # If a value was found, add to output map
        if new_val is not None:
            pv = epics.PV(pv_name)
            pv_map[pv_name] = pvNewVal(new_val=new_val, pv=pv)
        else:
            logger.error(f"No matching rule for PV '{pv_name}'")
    
    return pv_map

def write_pvs(pv_map: PVMap) -> bool:
    """Write new values to all PVs in the map.
    
    Args:
        pv_map: Dict mapping PV names to pvNewVal objects
    
    Returns:
        True if all writes succeeded, False otherwise
    """
    try:
        for pv_name, pv_val in pv_map.items():
            logger.debug(f"Writing to PV '{pv_name}': {pv_val.new_val}")
            pv_val.pv.put(pv_val.new_val)
        return True
    except Exception as e:
        logger.error(f"Failed to write PVs: {e}")
        return False

def verify_pvs(pv_map: PVMap) -> bool:
    """Verify that PV values match what was written.
    
    Args:
        pv_map: Dict mapping PV names to pvNewVal objects
    
    Returns:
        True if all values match, False otherwise
    """
    all_ok = True
    for pv_name, pv_val in pv_map.items():
        current_val = pv_val.pv.get()
        # Convert to string for comparison since epics.PV.get() may return numeric types
        if str(current_val) == pv_val.new_val:
            logger.debug(f"PV '{pv_name}' verified: {current_val}")
        else:
            logger.error(f"PV '{pv_name}' mismatch: expected {pv_val.new_val}, got {current_val}")
            all_ok = False
    return all_ok