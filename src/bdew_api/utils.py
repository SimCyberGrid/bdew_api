import logging
from datetime import datetime
from typing import Annotated
import re

from pydantic import BeforeValidator

# ============================================================================
# LOGGING SETUP
# ============================================================================


class ColoredFormatter(logging.Formatter):
    """Formatter mit Farben"""
    COLORS = {
        'DEBUG': '\033[36m',     # Cyan
        'INFO': '\033[32m',      # Green
        'WARNING': '\033[33m',   # Yellow
        'ERROR': '\033[31m',     # Red
        'RESET': '\033[0m'
    }

    def format(self, record):
        log_color = self.COLORS.get(record.levelname, self.COLORS['RESET'])
        record.levelname = f"{log_color}{record.levelname}{self.COLORS['RESET']}"
        return super().format(record)


def validate_iso_datetime(value: str | datetime) -> datetime:
    """
    Convert ISO string to datetime; reject non-ISO strings.

    Args:
        value: ISO 8601 formatted string (e.g., '2026-02-02T11:45:00Z' or '2026-02-02T11:45:00+01:00')
               or an already-parsed datetime object.

    Returns:
        Parsed datetime object.

    Raises:
        ValueError: If string is not valid ISO 8601 format.

    Examples:
        >>> validate_iso_datetime('2026-02-02T11:45:00Z')
        datetime.datetime(2026, 2, 2, 11, 45, tzinfo=datetime.timezone.utc)
        >>> validate_iso_datetime('2026-02-02T11:45:00+01:00')
        datetime.datetime(2026, 2, 2, 11, 45, tzinfo=datetime.timezone(datetime.timedelta(seconds=3600)))
    """
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        raise ValueError('Must be ISO string or datetime object')
    try:
        return datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError as e:
        raise ValueError(
            f'Invalid ISO datetime: {value}. Use YYYY-MM-DDTHH:MM:SSZ or YYYY-MM-DDTHH:MM:SS±HH:MM format.'
        ) from e


# Type alias for reusability across models
ISODateTime = Annotated[datetime, BeforeValidator(validate_iso_datetime)]


# ============================================================================
# COMPONENT-ID CLASSIFICATION (BDEW + legacy)
# ============================================================================
# BDEW/RFC-9562 scheme (IDs lowercased): MME = 11-digit MaLo-ID,
# controlbox = 'c' + 10 alphanumeric (SR-ID), GWA/AEMT = 13-digit MP-ID,
# SMGW = UUIDv5.
# Legacy scheme: <3-hex-group><type><8-hex>, e.g. '065mme63be3b18'.

_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


def is_smgw_id(component_id: str) -> bool:
    return "smgw" in component_id or bool(_UUID_RE.match(component_id))


def is_controlbox_id(component_id: str) -> bool:
    return "controlbox" in component_id or bool(re.match(r"^c[0-9a-z]{10}$", component_id))


def is_gwa_id(component_id: str, own_aemt_id: str = "") -> bool:
    """GWA = legacy '…gwa…' id, or a 13-digit MP-ID that is not this AEMT's own."""
    if "gwa" in component_id:
        return True
    return bool(re.match(r"^\d{13}$", component_id)) and component_id != own_aemt_id


def find_group_for_device(groups, device_id: str):
    """Return the routing-table group id containing *device_id*, else None.

    BDEW ids carry no group prefix, so group membership can only be resolved
    by looking the device up in the routing table.
    """
    for group_id, group in groups.items():
        if device_id in group.keys():
            return group_id
    return None
def setup_logger(name: str, id: str, log_level=logging.DEBUG) -> logging.Logger:
    """
    Setup a logger with ColoredFormatter (or standard formatter as fallback).
    
    Args:
        name: Logger name (typically __name__ or specific component name like 'OBIS', 'MeasurementData').
        id: Component ID to include in logger name.
    
    Returns:
        Configured logger instance.
    
    """
    logging.basicConfig(level=log_level)
    
    if id:
        id_split = re.match(r"^(mme|smgw|aemt|gwa|controlbox)([0-9a-f]{8})", id)
        if id_split:
            component = id_split.group(1)
            component_id = id_split.group(2)
            logger_name = f"{component}:{component_id}][{name}" if name != "" else f"{component}:{component_id}"
        else:
            logger_name = f"{id}][{name}" if name != "" else id
    else:
        logger_name = name
    
    logger = logging.getLogger(logger_name)
    logger.handlers.clear()
    logger.propagate = False
    
    handler = logging.StreamHandler()
    # Try to use ColoredFormatter if available
    formatter = ColoredFormatter(
        '[%(levelname)s][%(asctime)s][%(name)s] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    handler.setFormatter(formatter)

    #Make sure both logger and hadnler have the correct logging level
    logger.setLevel(log_level)
    handler.setLevel(log_level)

    # Add handler to logger
    logger.handlers = [handler]
    
    return logger


