"""CDW procurement source: import CDW order/invoice CSV exports.

Unlike the MDM/EDR API sources, CDW data arrives as exported CSV order or
invoice reports, so this is a file-import source: it reads a CSV from disk and
emits one NormalizedDevice per row, carrying purchase metadata (order number,
unit price, order date) in `extra`. No network access is performed.

The CSV column headers vary between exports, so the `columns` config maps
NormalizedDevice fields to CSV headers and ships sensible CDW defaults that
users can override.
"""

from __future__ import annotations

import csv
import logging

from ..models import NormalizedDevice
from .base import DeviceSource, SourceConfigError

logger = logging.getLogger(__name__)

#: Default mapping of NormalizedDevice fields to CDW CSV column headers.
DEFAULT_COLUMNS = {
    "serial": "Serial Number",
    "model": "Product Description",
    "hostname": "Asset Tag",
    "order_number": "Order Number",
    "purchase_cost": "Unit Price",
    "purchase_date": "Order Date",
}


class CdwSource(DeviceSource):
    key = "cdw"
    display_name = "CDW (procurement import)"

    # --- lifecycle hooks -------------------------------------------------
    def validate_config(self) -> None:
        if not self.config.get("csv_file"):
            raise SourceConfigError(
                f"{self.display_name} missing required config: csv_file"
            )

    def setup(self) -> None:
        self.csv_file = self.config.get("csv_file")
        self.delimiter = self.config.get("delimiter", ",")
        self.asset_type = self.config.get("asset_type", "computer")
        # Merge any user-provided column overrides over the defaults.
        self.columns = dict(DEFAULT_COLUMNS)
        self.columns.update(self.config.get("columns") or {})

    # --- data access -----------------------------------------------------
    def fetch_all(self):
        """Read the CDW CSV export and yield one NormalizedDevice per row."""
        try:
            handle = open(
                self.csv_file, encoding="utf-8-sig", newline=""
            )
        except OSError as exc:
            raise SourceConfigError(
                f"{self.display_name} could not open csv_file "
                f"'{self.csv_file}': {exc}"
            ) from exc

        with handle:
            reader = csv.DictReader(handle, delimiter=self.delimiter)
            for row in reader:
                serial = row.get(self.columns["serial"])
                order_number = row.get(self.columns["order_number"])

                # A row with neither a serial nor an order number carries no
                # usable identity; skip it rather than emitting a ghost asset.
                if not serial and not order_number:
                    logger.warning(
                        "Skipping CDW row with no serial and no order number: %r",
                        row,
                    )
                    continue

                # Only include purchase keys whose column is present in the row,
                # so we never fabricate fields a given export doesn't carry.
                extra = {}
                for field_name in ("order_number", "purchase_cost", "purchase_date"):
                    header = self.columns[field_name]
                    if header in row:
                        extra[field_name] = row.get(header)

                yield NormalizedDevice(
                    serial=serial,
                    source="cdw",
                    source_id=order_number,
                    asset_type=self.asset_type,
                    hostname=row.get(self.columns["hostname"]),
                    model=row.get(self.columns["model"]),
                    manufacturer=None,
                    extra=extra,
                    raw=dict(row),
                )
