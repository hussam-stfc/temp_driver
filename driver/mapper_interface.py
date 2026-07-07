from abc import ABC, abstractmethod
from typing import Any
from dataclasses import dataclass


@dataclass
class StatePVs:
    """Base state structure. Implementations may extend this."""
    pass


class StateMapper(ABC):
    """Abstract interface for state mapper implementations.
    
    All mapper implementations should:
    1. Initialize state via init_state()
    2. Execute mapping logic via run()
    3. Implement required helper methods
    """

    @abstractmethod
    def init(self, prefix: str):
        pass

    @abstractmethod
    def run(self) -> bool:
        """Execute the state mapping workflow.
        
        This is the main entry point. Implementations should:
        1. Read from data source (DB, API, etc.)
        2. Map state to output values
        3. Perform pre-write actions
        4. Write PVs
        5. Perform post-write actions
        6. Return success/failure status
        
        Returns:
            True if successful, False otherwise
        """
        pass

    @abstractmethod
    def read_config(self) -> Any:
        """Read data from source (database, API, file, etc.).
        
        Returns:
            Data in whatever format the implementation needs
        """
        pass

    @abstractmethod
    def map_state(self, data: Any) -> Any:
        """Map input data to output values based on current state.
        
        Args:
            data: Input data from read_data()
            
        Returns:
            Mapped output (typically dict or list of PV values)
        """
        pass

    @abstractmethod
    def pre_write(self) -> None:
        """Perform actions before writing PVs (e.g., save state, close shutters)."""
        pass

    @abstractmethod
    def write_pvs(self, mapped_data: Any) -> bool:
        """Write values to EPICS PVs.
        
        Args:
            mapped_data: Output from map_state()
            
        Returns:
            True if all writes succeeded, False otherwise
        """
        pass

    @abstractmethod
    def post_write(self) -> None:
        """Perform actions after writing PVs (e.g., restore state)."""
        pass
