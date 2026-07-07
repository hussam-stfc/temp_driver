import logging
import httpx
from typing import Final, Any
from enum import Enum
from dataclasses import dataclass
from time import sleep

import epics

from mapper_interface import StateMapper, StatePVs as BaseStatePVs

logger = logging.getLogger(__name__)

# Env vars
API_BASE_URL: Final[str] = "http://localhost:8000"
PLC_204_PREFIX: Final[str] = "FE-204-PLC"

# Helper type aliases
Database = dict[str, dict[str, Any]]
PVMap = dict[str, 'pvWithVal']

@dataclass
class EnergyModeStatePVs(BaseStatePVs):
    energy_mode: epics.PV
    ts_cw: epics.PV
    cm_cw: epics.PV

@dataclass
class pvWithVal:
    val: str
    pv: epics.PV

# Custom Global state
class shutterState(Enum):
    NONE = 0
    SINGLESHOT = 1
    ONEHZ = 2
    TENHZ = 3


class EnergyModeMapper(StateMapper):
    """State mapper implementation based on energy mode priority."""

    def __init__(self, prefix: str):
        self.init(prefix)

    def init(self, prefix: str):
        self.state = EnergyModeStatePVs(
            energy_mode=epics.PV(f'{prefix}:ENERGY_MODE'),
            ts_cw=epics.PV(f'{prefix}:TS_CW'),
            cm_cw=epics.PV(f'{prefix}:CM_CW')
        )

        self.fastShutterLastState: shutterState = shutterState.NONE

    def run(self) -> bool:
        logger.info("Working...")

        database = self.read_config()
        pv_map = self.map_state(database)

        self.pre_write()

        status = self.write_pvs(pv_map)
        if not status:
            logger.error("Failed to write PVs")
            return False

        self.post_write()

        return True

    def read_config(self) -> Database:
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

    def map_state(self, database: Database) -> PVMap:
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
            Dict mapping PV names to pvWithVal objects with new values and PV references
        """

        energy_mode = self.state.energy_mode.get()
        cw_ts = self.state.ts_cw.get()
        cw_cm = self.state.cm_cw.get()
        
        logger.debug(f"State: energy_mode={energy_mode}, cw_ts={cw_ts}, cw_cm={cw_cm}")

        pv_map = {}
        
        for pv_name, row in database.items():
            val = None
            state_name = None
            
            # Priority 1: Check CW_CM
            if cw_cm == 1 and row.get("CM_CW_IN", ""):
                val = row["CM_CW_IN"]
                state_name = "CM_CW_IN"
            # Priority 2: Check CW_TS
            elif cw_ts == 1 and row.get("TS_CW_IN", ""):
                val = row["TS_CW_IN"]
                state_name = "TS_CW_IN"
            # Priority 3: Check energy mode (1-4)
            elif energy_mode in [1, 2, 3, 4]:
                col_name = f"EM{energy_mode}"
                if row.get(col_name, ""):
                    val = row[col_name]
                    state_name = col_name
            
            # If a value was found, add to output map
            if val is not None:
                pv = epics.PV(pv_name)
                pv_map[pv_name] = pvWithVal(val=val, pv=pv)
                logger.info(f"PV {pv_name} set to {val} for {state_name}")
            else:
                logger.error(f"No matching rule for PV '{pv_name}'")
        
        return pv_map

    def pre_write(self):
        """Perform any necessary actions before writing PVs."""

        logger.info("Pre-write: store fast shutter state and close fast shutter")

        try:
            fastShutterIsSingleShot = epics.PV(f'{PLC_204_PREFIX}:OP_Fast_Shutter_Single_Shot_MODE').get() == 1
            if fastShutterIsSingleShot:
                logger.info("Fast shutter is in single shot mode")
                self.fastShutterLastState = shutterState.SINGLESHOT

            fastShutterIsOneHz = epics.PV(f'{PLC_204_PREFIX}:OP_Fast_Shutter_1Hz_MODE').get() == 1
            if fastShutterIsOneHz:
                logger.info("Fast shutter is in 1Hz mode")
                self.fastShutterLastState = shutterState.ONEHZ

            fastShutterIsTenHz = epics.PV(f'{PLC_204_PREFIX}:OP_Fast_Shutter_10Hz_MODE').get() == 1
            if fastShutterIsTenHz:
                logger.info("Fast shutter is in 10Hz mode")
                self.fastShutterLastState = shutterState.TENHZ

            epics.PV(f'{PLC_204_PREFIX}:IP_Fast_Shutter_Do_PULSE').put(0) # TODO: Is it 0 or 1?
            logger.info("Fast shutter closed")

        except Exception as e:
            logger.error(f"Failed to store fast shutter state or close shutter: {e}")
        

    def write_pvs(self, pv_map: PVMap) -> bool:
        """Write new values to all PVs in the map.
        
        Args:
            pv_map: Dict mapping PV names to pvWithVal objects
        
        Returns:
            True if all writes succeeded, False otherwise
        """
        try:
            for pv_name, pv_val in pv_map.items():
                logger.debug(f"Writing to PV '{pv_name}': {pv_val.val}")
                pv_val.pv.put(pv_val.val)
                sleep(0.1)  # Debug delay
            return True
        except Exception as e:
            logger.error(f"Failed to write PVs: {e}")
            return False


    def verify_pvs(self, pv_map: PVMap) -> bool:
        """Verify that PV values match what was written.
        
        Args:
            pv_map: Dict mapping PV names to pvWithVal objects
        
        Returns:
            True if all values match, False otherwise
        """
        all_ok = True
        for pv_name, pv_val in pv_map.items():
            current_val = pv_val.pv.get()
            # Convert to string for comparison since epics.PV.get() may return numeric types
            if str(current_val) == pv_val.val:
                logger.debug(f"PV '{pv_name}' verified: {current_val}")
            else:
                logger.error(f"PV '{pv_name}' mismatch: expected {pv_val.val}, got {current_val}")
                all_ok = False
        return all_ok

    def post_write(self):
        """Perform any necessary actions after writing PVs."""

        logging.info("Post-write: restore fast shutter state")

        # Restore the fast shutter to the state before the write operation

        try:
            if self.fastShutterLastState == shutterState.SINGLESHOT:
                logger.info("Restoring fast shutter to single shot mode")
                epics.PV(f'{PLC_204_PREFIX}:IP_Fast_Shutter_Single_Shot_Do_PULSE.PROC').put(1)

            if self.fastShutterLastState == shutterState.ONEHZ:
                logger.info("Restoring fast shutter to 1Hz mode")
                epics.PV(f'{PLC_204_PREFIX}:IP_Fast_Shutter_1Hz_Do_PULSE.PROC').put(1)

            if self.fastShutterLastState == shutterState.TENHZ:
                logger.info("Restoring fast shutter to 10Hz mode")
                epics.PV(f'{PLC_204_PREFIX}:IP_Fast_Shutter_10Hz_Do_PULSE.PROC').put(1)

        except Exception as e:
            logger.error(f"Failed to restore fast shutter state: {e}")