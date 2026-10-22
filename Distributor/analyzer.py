# A program used to analyze data prior to distribution.
# sammatime, 2026

def run_analyze(mariadb_data, mariadb_cursor, config):
    '''
    helps to facilitate the running of the analyze functions.

    Parameters:
    -----------
      mariadb_data: the stock data provided from the distributor
      mariadb_cursor: a cursor to mariadb, so the analyzer functions can also use the mariadb reference
      config: the distributor config in use 

    Returns:
    -----------
      - email contents that could be returned to the recipient describing the .xlsx file

    Creates:
    -----------
      - a file at the location of email_config -> attachment
    '''
    # call format_findings
    # use sort_findings
    # use get_insight
    # develop_xlsx


def format_findings(mariadb_data):
    '''
    Takes in the data from mariadb, and formats it for use within the analyzer functions.

    Parameters:
    -----------
      mariadb_data: the stock data provided from the distributor

    Returns:
    -----------
      - a formatted set of findings
    '''



def sort_findings(formatted_mariadb_data):
    '''
    Sorts the findings following getting them into a usable format.

    Parameters:
    -----------
      formatted_mariadb_data: the stock data provided from the distributor, formatted

    Returns:
    -----------
      - a formatted set of findings sorted by rate of change
    '''



def get_insight(sorted_data):
    '''
    Talks to an AI model about the current sorted data, specifically asking for insight on the top three gainers
    and losers, finding a recent article on each of the gainers and losers and providing a blurb on them.

    Parameters:
    -----------
      sorted_data: a sorted set of stock data

    Returns:
    -----------
      - a blurb for both the email and the xlsx file
    '''



def develop_xlsx(sorted_data, blurb, xlsx_location):
    '''
    Uses information gathered earlier in the function calls and develops an xlsx from it.

    Parameters:
    -----------
      sorted_data: a sorted set of stock data
      blurb: a blurb to be included in the xlsx
      xlsx_location: the location of the xlsx file

    Creates:
    -----------
      - a file at the location of email_config -> attachment
    '''
