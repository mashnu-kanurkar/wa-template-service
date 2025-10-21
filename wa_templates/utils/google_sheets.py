import os
import json
import logging
import tempfile
import gspread
from typing import List, Dict, Optional, Any
from google.oauth2.service_account import Credentials

logger = logging.getLogger(__name__)

# Logging configuration (optional; remove if already configured elsewhere)
if not logger.handlers:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

REQUIRED_FIELDS = [
    "id", "title", "description", "availability", "condition",
    "price", "link", "image_link", "brand"
]

OPTIONAL_FIELDS = [
    "quantity_to_sell_on_facebook", "size", "sale_price", "sale_price_effective_date",
    "item_group_id", "status", "color", "gender", "age_group", "material",
    "pattern", "rich_text_description", "shipping", "shipping_weight",
    "internal_label", "custom_label_0", "custom_label_1", "custom_label_2",
    "custom_label_3", "custom_label_4"
]


class GoogleSheetCatalog:
    SCOPES = ['https://www.googleapis.com/auth/spreadsheets']

    def __init__(self, sheet_url: str, service_file_content: str):
        self.sheet_url = sheet_url
        self.service_file_content = service_file_content
        self.client = self._get_client_from_content()
        self.sheet = self._open_sheet()
        logger.info(f"Initialized GoogleSheetCatalog for {self.sheet_url}")

    # -----------------------------
    # Internal Helpers
    # -----------------------------

    def _get_client_from_content(self):
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".json") as tmp_file:
                tmp_file.write(self.service_file_content.encode())
                tmp_path = tmp_file.name

            client = gspread.authorize(Credentials.from_service_account_file(tmp_path, scopes=self.SCOPES))
            logger.debug("GSpread client authorized successfully.")
            return client
        except Exception as e:
            logger.exception("Failed to create gspread client: %s", e)
            raise
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    def _open_sheet(self):
        try:
            sheet = self.client.open_by_url(self.sheet_url).sheet1
            logger.info(f"Opened Google Sheet: {sheet.title}")
            return sheet
        except Exception as e:
            logger.exception(f"Error opening sheet at {self.sheet_url}: {e}")
            raise

    def _ensure_grid_capacity(self, required_rows: int, required_cols: int):
        """Expands grid automatically if needed."""
        try:
            sheet_props = self.sheet.spreadsheet.fetch_sheet_metadata()
            sheet_info = next(s for s in sheet_props["sheets"] if s["properties"]["sheetId"] == self.sheet.id)
            grid = sheet_info["properties"]["gridProperties"]

            current_rows = grid.get("rowCount", 1000)
            current_cols = grid.get("columnCount", 26)

            if required_rows > current_rows:
                self.sheet.add_rows(required_rows - current_rows)
                logger.info(f"Expanded sheet rows from {current_rows} → {required_rows}")

            if required_cols > current_cols:
                self.sheet.add_cols(required_cols - current_cols)
                logger.info(f"Expanded sheet columns from {current_cols} → {required_cols}")
        except Exception as e:
            logger.exception("Error ensuring grid capacity: %s", e)

    def _ensure_headers(self, new_fields: Optional[List[str]] = None):
        """Ensures required, optional, and dynamic headers exist."""
        headers = self.sheet.row_values(1)
        new_fields = new_fields or []
        all_fields = REQUIRED_FIELDS + OPTIONAL_FIELDS + [
            f for f in new_fields if f not in REQUIRED_FIELDS + OPTIONAL_FIELDS
        ]
        self._ensure_grid_capacity(required_rows=1, required_cols=len(all_fields))

        updated = False
        for field in all_fields:
            if field not in headers:
                self.sheet.update_cell(1, len(headers) + 1, field)
                headers.append(field)
                updated = True
                logger.info(f"Added new header: {field}")

        if updated:
            logger.info("Headers updated successfully.")
        else:
            logger.debug("Sheet headers already up-to-date.")
        return headers

    # -----------------------------
    # Core Operations
    # -----------------------------

    def read_all(self) -> List[Dict[str, Any]]:
        data = self.sheet.get_all_records()
        logger.info(f"Retrieved {len(data)} records from catalog.")
        return data

    def batch_write(
        self,
        add_list: Optional[List[Dict]] = None,
        update_list: Optional[List[Dict]] = None,
        delete_list: Optional[List[Any]] = None,
        partial: bool = True
    ) -> Dict[str, int]:
        """Unified add/update/delete operation."""
        add_list = add_list or []
        update_list = update_list or []
        delete_list = delete_list or []
        logger.info("Starting batch write operation...")
        logger.debug(f"Add list: {len(add_list)}, Update list: {len(update_list)}, Delete list: {len(delete_list)}")

        all_fields = set()
        for p in add_list + update_list:
            all_fields.update(p.keys())
        headers = self._ensure_headers(all_fields)

        rows = self.sheet.get_all_records()
        id_to_row_idx = {str(r["id"]): i + 2 for i, r in enumerate(rows)}  # Sheet row numbers

        # DELETE
        deleted_count = 0
        for pid in delete_list:
            row_idx = id_to_row_idx.get(str(pid))
            if row_idx:
                self.sheet.delete_rows(row_idx)
                deleted_count += 1
                logger.info(f"Deleted product ID {pid}")
                for key, idx in id_to_row_idx.items():
                    if idx > row_idx:
                        id_to_row_idx[key] -= 1

        # UPDATE
        updated_count = 0
        for product in update_list:
            pid = str(product.get("id"))
            if not pid:
                logger.warning(f"Skipping update, missing ID: {product}")
                continue
            row_idx = id_to_row_idx.get(pid)
            if not row_idx:
                logger.warning(f"Product {pid} not found for update.")
                continue
            row_updates = {}
            for field, value in product.items():
                if field in headers:
                    col_idx = headers.index(field) + 1
                    row_updates[col_idx] = value
            if row_updates:
                cell_list = self.sheet.range(row_idx, 1, row_idx, len(headers))
                for col_idx, value in row_updates.items():
                    cell_list[col_idx - 1].value = value
                self.sheet.update_cells(cell_list)
                updated_count += 1
                logger.info(f"Updated product {pid}")

        # ADD
        added_count = 0
        if add_list:
            new_rows = [[p.get(h, "") for h in headers] for p in add_list]
            self.sheet.append_rows(new_rows)
            added_count = len(add_list)
            logger.info(f"Added {added_count} new product(s).")

        logger.info(f"Batch operation complete. Added={added_count}, Updated={updated_count}, Deleted={deleted_count}")
        return {"added": added_count, "updated": updated_count, "deleted": deleted_count}

    def add_row(self, new_data: Dict[str, Any]):
        headers = self._ensure_headers(new_data.keys())
        row = [new_data.get(h, "") for h in headers]
        self.sheet.append_row(row)
        logger.info(f"Added new product with ID {new_data.get('id')}")

    def update_row(self, product_id: Any, updated_data: Dict[str, Any]) -> bool:
        headers = self._ensure_headers(updated_data.keys())
        rows = self.sheet.get_all_records()
        for idx, row in enumerate(rows, start=2):
            if str(row.get("id")) == str(product_id):
                for field, value in updated_data.items():
                    if field in headers:
                        col_index = headers.index(field) + 1
                        self.sheet.update_cell(idx, col_index, value)
                        logger.debug(f"Updated field '{field}' for product {product_id}")
                logger.info(f"Updated row for product {product_id}")
                return True
        logger.warning(f"Product {product_id} not found for update.")
        return False

    def delete_row(self, product_id: Any) -> bool:
        rows = self.sheet.get_all_records()
        for idx, row in enumerate(rows, start=2):
            if str(row.get("id")) == str(product_id):
                self.sheet.delete_rows(idx)
                logger.info(f"Deleted product ID {product_id}")
                return True
        logger.warning(f"Product {product_id} not found for deletion.")
        return False

    def bulk_write(self, product_list: List[Dict[str, Any]]):
        """Handles both add and update by ID."""
        all_fields = {k for p in product_list for k in p.keys()}
        headers = self._ensure_headers(all_fields)
        rows = self.sheet.get_all_records()
        id_to_row_idx = {str(r["id"]): i + 2 for i, r in enumerate(rows)}

        for product in product_list:
            pid = str(product.get("id"))
            if pid in id_to_row_idx:
                row_idx = id_to_row_idx[pid]
                for field, value in product.items():
                    if field in headers:
                        col_idx = headers.index(field) + 1
                        self.sheet.update_cell(row_idx, col_idx, value)
                logger.info(f"Updated product {pid}")
            else:
                row = [product.get(h, "") for h in headers]
                self.sheet.append_row(row)
                logger.info(f"Added new product {pid}")

        logger.info(f"Bulk write complete. Processed {len(product_list)} products.")

    def bulk_delete(self, product_ids: List[Any]) -> int:
        rows = self.sheet.get_all_records()
        id_to_row_idx = {str(r["id"]): i + 2 for i, r in enumerate(rows)}
        deleted_count = 0
        for pid in product_ids:
            row_idx = id_to_row_idx.get(str(pid))
            if row_idx:
                self.sheet.delete_rows(row_idx)
                deleted_count += 1
                for key, idx in id_to_row_idx.items():
                    if idx > row_idx:
                        id_to_row_idx[key] -= 1
                logger.info(f"Deleted product ID {pid}")
        logger.info(f"Bulk delete complete. Deleted {deleted_count} rows.")
        return deleted_count
