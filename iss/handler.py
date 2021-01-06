import xlwings as xw
import pymsgbox
import json
import os
from os.path import dirname, join

import quickfs_scraping.process
from quickfs_scraping.excel_handler import excel_to_dataframe, check_validity_output_file, excel_sheet_exists


def ask_ticker_to_user():
    # Aak ticker to user
    ticker = pymsgbox.prompt('Please enter a valid ticker: ')
    assert isinstance(ticker, str)

    return ticker.upper()


def get_fs_dir_path():
    # This function gets the directory where the financial statements generated by
    # quickfs_scraping module are
    module_path = dirname(dirname(quickfs_scraping.__file__))

    return join(module_path, 'financial_files', 'excel')


def translate_dict_keys(rule1_dict, sheet_name):
    # Translate dictionary, substituting current keys by table keys
    translation_dict_path = join(dirname(__file__), 'data', 'iss_translation_dict.json')
    with open(translation_dict_path, 'r') as file:
        translation_dict = json.load(file)

    table_header_list = translation_dict[sheet_name]['table_headers']
    rule1_metrics_list = translation_dict[sheet_name]['rule1_metrics']

    result_dict = dict()
    for i, value in enumerate(table_header_list):
        if rule1_metrics_list[i] in rule1_dict:
            result_dict[value] = rule1_dict[rule1_metrics_list[i]]

    return result_dict


def gen_fs_excel_file(ticker):
    quickfs_scraping.process.run(ticker, bool_batch=True)


class FSHandler:
    def __init__(self, sheet_name):
        self.sheet_name = sheet_name.capitalize()
        self.wb = xw.Book.caller()
        self.wb_path = self.wb.fullname
        self.ws = self.wb.sheets[self.sheet_name].api
        self.table = self.ws.ListObjects(self.sheet_name)
        self.fs_dir = get_fs_dir_path()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass

    def table_to_ticker_list(self, only_updated=True):
        ticker_list = list()
        for i in range(1, self.table.ListRows.Count + 1):
            ticker = self.table.ListColumns('Ticker').DataBodyRange(i).Value
            status = self.table.ListColumns('Status').DataBodyRange(i).Value

            if (status != 'Updated' and status != 'Hold') or only_updated is False:
                ticker_list.append(ticker)

        return ticker_list

    def get_fs_excel_path(self, ticker):
        return join(self.fs_dir, ticker.upper() + ".xlsx")

    def open_fs_excel_file(self, ticker):
        excel_file = self.get_fs_excel_path(ticker)

        try:
            os.startfile(excel_file)
        except:
            pymsgbox.alert(f"Excel file for {ticker} doesn't exist or is being used by another process",
                           "Error opening file")
            exit()

    def delete_ticker_from_table(self, ticker):
        # Check first if ticker really is in table
        ticker_list = self.table_to_ticker_list(only_updated=False)
        if ticker not in ticker_list:
            pymsgbox.alert(f"The ticker {ticker} is not present in the {self.sheet_name} table.")
            exit()

        # Remove filter from table if there is
        self.table.ShowAutoFilter = False
        self.table.ShowAutoFilter = True

        # Delete row that has the ticker
        for i in range(1, self.table.ListRows.Count + 1):
            if self.table.ListColumns('Ticker').DataBodyRange(i).Value == ticker:
                self.table.ListRows(i).Delete()

    def add_ticker_to_table(self, ticker, sheet_name):
        # Obtain the correct objects for the specific sheet
        self.ws = self.wb.sheets[sheet_name].api
        self.table = self.ws.ListObjects(sheet_name)

        # Check if ticker already doesn't exists in table
        ticker_list = self.table_to_ticker_list(only_updated=False)
        if ticker in ticker_list:
            pymsgbox.alert(f"The ticker {ticker} is already present in the {self.sheet_name} table.")
            exit()

        # Create new row and add the ticker
        self.table.ListRows.Add(AlwaysInsert=True)
        last_row = self.table.ListRows.Count
        self.table.ListColumns('Ticker').DataBodyRange(last_row).Value = ticker

        # Add suggestions to unfilled qualitative columns
        self.watchlist_status_suggestion(last_row)

        # Change status of ticker in watchlist
        self.table.ListColumns('Status').DataBodyRange(last_row).Value = "New"

    def watchlist_status_suggestion(self, row):
        # Check status suggestion for unfilled cells in user evaluation columns
        columns = ['Personal Approval', 'Meaning Approved', 'Management Approved']
        for header in columns:
            if self.table.ListColumns(header).DataBodyRange(row).Value is None:
                self.table.ListColumns(header).DataBodyRange(row).Value = "CHECK"

    def check_validity_excel_file(self, ticker):
        excel_path = self.get_fs_excel_path(ticker)

        if check_validity_output_file(excel_path):
            if excel_sheet_exists(excel_path, source=self.sheet_name):
                return True
            else:
                return False
        else:
            return False

    def extract_rule1_metrics_data(self, ticker):
        # Check if financial excel file is available and updated.
        # If not, create a new one
        if not self.check_validity_excel_file(ticker):
            gen_fs_excel_file(ticker)

        # Get the data from the fs excel file in a dataframe format
        rule1_df = excel_to_dataframe(self.get_fs_excel_path(ticker), source='rule1_results')

        # Turn first column into index
        rule1_df = rule1_df.set_index('Rule #1 Metric')

        # Transform dataframe into dictionary
        rule1_dict = rule1_df.to_dict()['Value']

        # Translate dictionary, substituting current keys by table keys
        rule1_dict = translate_dict_keys(rule1_dict, self.sheet_name)

        return rule1_dict

    def rule1_data_to_table(self):
        ticker_list = self.table_to_ticker_list()

        if len(ticker_list) == 0:
            pymsgbox.alert("All tickers are already updated. Please change status if you want to update again.",
                           "All tickers already updated")
            exit()

        for i in range(1, self.table.ListRows.Count + 1):
            ticker = self.table.ListColumns('Ticker').DataBodyRange(i).Value

            if ticker in ticker_list:
                rule1_dict = self.extract_rule1_metrics_data(ticker)

                # Put the data in the right location
                for key, value in rule1_dict.items():
                    self.table.ListColumns(key).DataBodyRange(i).Value = value

                # Change status of ticker in table
                self.table.ListColumns('Status').DataBodyRange(i).Value = 'Updated'

                # Add suggestions to unfilled qualitative columns if it is watchlist
                if self.sheet_name == 'Watchlist':
                    self.watchlist_status_suggestion(i)
