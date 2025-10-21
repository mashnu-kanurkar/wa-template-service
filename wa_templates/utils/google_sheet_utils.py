# import gspread
# from google.oauth2.service_account import Credentials
# import logging
# import os

# logger = logging.getLogger(__name__)

# SCOPES = ['https://www.googleapis.com/auth/spreadsheets']

# def get_sheet_client(service_file_path: str):
#     try:
#         if not os.path.exists(service_file_path):
#             raise FileNotFoundError(f"Service credentials not found: {service_file_path}")
#         creds = Credentials.from_service_account_file(service_file_path, scopes=SCOPES)
#         client = gspread.authorize(creds)
#         return client
#     except Exception as e:
#         logger.exception("Failed to authorize Google Sheets client: %s", e)
#         raise

# # def read_catalog_data(sheet_url: str, service_file_path: str):
# #     try:
# #         client = get_sheet_client(service_file_path)
# #         sheet = client.open_by_url(sheet_url).sheet1
# #         data = sheet.get_all_records()
# #         logger.info("Fetched %d rows from catalog sheet", len(data))
# #         return data
# #     except Exception as e:
# #         logger.exception("Error reading Google Sheet: %s", e)
# #         raise

# # def update_catalog_data(sheet_url: str, service_file_path: str, rows: list):
# #     try:
# #         client = get_sheet_client(service_file_path)
# #         sheet = client.open_by_url(sheet_url).sheet1
# #         sheet.clear()
# #         sheet.update('A1', rows)
# #         logger.info("Updated catalog sheet with %d rows", len(rows))
# #         return True
# #     except Exception as e:
# #         logger.exception("Error updating Google Sheet: %s", e)
# #         raise

# def update_row(sheet_url, service_file, product_id, updated_data):
#     client = get_sheet_client(service_file)
#     sheet = client.open_by_url(sheet_url).sheet1
#     rows = sheet.get_all_records()
#     headers = sheet.row_values(1)

#     for idx, row in enumerate(rows, start=2):
#         if str(row.get("id")) == str(product_id):
#             for field, value in updated_data.items():
#                 if field in headers:
#                     col_index = headers.index(field) + 1
#                     sheet.update_cell(idx, col_index, value)
#             logger.info("Updated catalog sheet with row id %d", product_id)
#             return True
#     logger.warning("Row with id %d not found for update", product_id)   
#     return False

# def add_row(sheet_url, service_file, new_data):
#     client = get_sheet_client(service_file)
#     sheet = client.open_by_url(sheet_url).sheet1
#     sheet.append_row([new_data.get(h, "") for h in sheet.row_values(1)])
#     logger.info("Added new row to catalog sheet with id %s", new_data.get("id"))

# def delete_row(sheet_url, service_file, product_id):
#     client = get_sheet_client(service_file)
#     sheet = client.open_by_url(sheet_url).sheet1
#     rows = sheet.get_all_records()
#     for idx, row in enumerate(rows, start=2):
#         if str(row.get("id")) == str(product_id):
#             sheet.delete_rows(idx)
#             logger.info("Deleted row from catalog sheet with id %d", product_id)
#             return True
#     logger.warning("Row with id %d not found for deletion", product_id)
#     return False


