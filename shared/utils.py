"""
Shared utility functions for crystal-lab projects.
Contains common functions for Google Sheets, BigQuery, and other services.
"""

import gspread
from google.oauth2.service_account import Credentials
from google.cloud import bigquery
from gspread_dataframe import set_with_dataframe
from gspread.exceptions import APIError
import pandas as pd
from .config import (
    GOOGLE_SERVICE_ACCOUNT_FILE,
    BIG_QUERY_SERVICE_ACCOUNT_FILE,
    SCOPES_SHEETS,
    SCOPES_BIGQUERY,
    BQ_PROJECT_ID,
    BQ_LOCATION,
)


# 1.0 Google Sheets Utilities


def get_gspread_client() -> gspread.Client:
    """
    Initialize Google Sheets client using service account credentials.

    Returns:
        gspread.Client: Authorized gspread client

    Raises:
        RuntimeError: If authentication fails or service account file is not found
    """
    try:
        creds = Credentials.from_service_account_file(
            str(GOOGLE_SERVICE_ACCOUNT_FILE), scopes=SCOPES_SHEETS
        )
        gc = gspread.authorize(creds)
        return gc
    except FileNotFoundError:
        raise RuntimeError(f"Service account file not found: {GOOGLE_SERVICE_ACCOUNT_FILE}")
    except Exception as e:
        raise RuntimeError(f"Failed to authorize Google Sheets access: {e}")


def write_to_worksheet(
    gc: gspread.Client,
    spreadsheet_id: str,
    worksheet_name: str,
    df: pd.DataFrame,
    start_row: int = 1,
    start_col: int = 1,
    include_index: bool = False,
    include_header: bool = True,
) -> gspread.Worksheet:
    """
    Write a DataFrame to a Google Sheets worksheet.

    Parameters:
        gc (gspread.Client): Authorized gspread client
        spreadsheet_id (str): ID of the target spreadsheet
        worksheet_name (str): Name of the worksheet to write to
        df (pd.DataFrame): DataFrame to write
        start_row (int): Starting row position (1-indexed)
        start_col (int): Starting column position (1-indexed)
        include_index (bool): Whether to include DataFrame index
        include_header (bool): Whether to include column headers

    Returns:
        gspread.Worksheet: The worksheet that was written to

    Raises:
        RuntimeError: If writing to the sheet fails
    """
    try:
        spreadsheet = gc.open_by_key(spreadsheet_id)

        try:
            worksheet = spreadsheet.worksheet(worksheet_name)
        except gspread.WorksheetNotFound:
            worksheet = spreadsheet.add_worksheet(title=worksheet_name, rows=1000, cols=100)

        # Compute write range and clear only the target area
        n_df_cols = df.shape[1]
        if include_index:
            n_df_cols += 1

        end_col = start_col + n_df_cols - 1
        max_rows = worksheet.row_count

        worksheet.batch_clear(
            [
                f"{gspread.utils.rowcol_to_a1(start_row, start_col)}:"
                f"{gspread.utils.rowcol_to_a1(max_rows, end_col)}"
            ]
        )

        set_with_dataframe(
            worksheet,
            df,
            row=start_row,
            col=start_col,
            include_index=include_index,
            include_column_header=include_header,
        )

        return worksheet

    except APIError as e:
        raise RuntimeError(f"Failed to write to Google Sheet: {e}")
    except Exception as e:
        raise RuntimeError(f"Unexpected error writing to Google Sheets: {e}")


# 2.0 BigQuery Utilities


def get_bigquery_client(use_adc: bool = False) -> bigquery.Client:
    """
    Initialize BigQuery client using service account file or Application Default Credentials.

    Parameters:
        use_adc (bool): If True, use Application Default Credentials (ADC).
                        If False (default), use explicit service account file.

    Returns:
        bigquery.Client: Authorized BigQuery client

    Raises:
        RuntimeError: If authentication fails or service account file is not found
    """
    try:
        if use_adc:
            client = bigquery.Client(project=BQ_PROJECT_ID, location=BQ_LOCATION)
            return client
        else:
            credentials = Credentials.from_service_account_file(
                str(BIG_QUERY_SERVICE_ACCOUNT_FILE), scopes=SCOPES_BIGQUERY
            )
            client = bigquery.Client(
                credentials=credentials, project=BQ_PROJECT_ID, location=BQ_LOCATION
            )
            return client
    except FileNotFoundError:
        raise RuntimeError(f"Service account file not found: {BIG_QUERY_SERVICE_ACCOUNT_FILE}")
    except Exception as e:
        raise RuntimeError(f"Failed to initialize BigQuery client: {e}")


def execute_bigquery_query(query: str) -> pd.DataFrame:
    """
    Execute a BigQuery SQL query and return results as a DataFrame.

    Parameters:
        query (str): SQL query string to execute

    Returns:
        pd.DataFrame: Query results as a pandas DataFrame

    Raises:
        RuntimeError: If query execution fails
    """
    try:
        client = get_bigquery_client()
        bq_query = client.query(query)
        df = bq_query.to_dataframe()
        return df
    except Exception as e:
        raise RuntimeError(f"Failed to execute BigQuery query: {e}")
