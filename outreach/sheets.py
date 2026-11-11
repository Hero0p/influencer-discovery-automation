"""Google Sheets helpers. The sheet is the review screen and the place Zapier watches."""

import gspread


def open_book(settings):
    """Open the spreadsheet named by SHEET_ID using the service-account key file."""
    client = gspread.service_account(filename=str(settings.service_account_file))
    return client.open_by_key(settings.sheet_id)


def get_tab(book, title, headers):
    """Return the tab with this title. It is created with a header row the first time."""
    try:
        return book.worksheet(title)
    except gspread.WorksheetNotFound:
        tab = book.add_worksheet(title=title, rows=200, cols=len(headers))
        tab.update(values=[headers], range_name="A1", value_input_option="RAW")
        return tab


def read_rows(book, title, headers):
    """Every row of a tab as a dictionary keyed by the header row. All values come back as text."""
    return get_tab(book, title, headers).get_all_records(expected_headers=headers, numericise_ignore=["all"])


def append_rows(book, title, headers, rows):
    """Add rows at the bottom. Existing rows are never touched."""
    if rows:
        # RAW stores text exactly as given, so scraped text can never turn into a formula.
        get_tab(book, title, headers).append_rows(rows, value_input_option="RAW", table_range="A1")


def replace_rows(book, title, headers, rows):
    """Rewrite a whole tab (used for the read-only report tabs)."""
    tab = get_tab(book, title, headers)
    tab.clear()
    tab.resize(rows=len(rows) + 10, cols=len(headers))
    tab.update(values=[headers] + rows, range_name="A1", value_input_option="RAW")
