# A program used to analyze data prior to distribution.
# sammatime, 2026
import google.generativeai as genai
import logging
import openpyxl
import traceback

# Config keys
EMAIL_CONFIG = "email_config"
ATTACHMENT = "attachment"

# SQL queries
SELECT_STOCK_NAME_AND_ACRONYM = "SELECT stock_name, acronym FROM STOCK WHERE stock_id={};"

# AI settings
GEMINI_MODEL = "gemini-2.0-flash"
AI_ERROR_ANSWER = "An error occurred in querying the AI agent."
TOP_COUNT = 3

# xlsx layout
DATA_SHEET_TITLE = "Stock Data"
INSIGHT_SHEET_TITLE = "Insight"
XLSX_HEADER = ["Stock Name", "Stock Acronym", "Yesterday's Price", "Today's Price", "Total Difference", "Percent Difference"]

logger = logging.getLogger()


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
        (None if the data could not be analyzed, so the distributor sends an apology instead)

    Creates:
    -----------
      - a file at the location of email_config -> attachment
    '''
    try:
        # call format_findings
        formatted_data = format_findings(mariadb_data)
        if not formatted_data:
            logger.info("No stock had both a previous and a current price, so there is nothing to analyze")
            return None

        # add each stock's name and acronym from mariadb
        for finding in formatted_data:
            mariadb_cursor.execute(SELECT_STOCK_NAME_AND_ACRONYM.format(finding["stock_id"]))
            rows = mariadb_cursor.fetchall()
            if rows:
                finding["stock_name"], finding["acronym"] = rows[0]

        # use sort_findings
        sorted_data = sort_findings(formatted_data)

        # use get_insight
        blurb = get_insight(sorted_data)

        # develop_xlsx
        develop_xlsx(sorted_data, blurb, config[EMAIL_CONFIG][ATTACHMENT])
        return blurb
    except Exception as e:
        logger.error("Analysis failed: {}".format(e))
        traceback.print_exc()
        return None


def format_findings(mariadb_data):
    '''
    Takes in the data from mariadb, and formats it for use within the analyzer functions.

    Parameters:
    -----------
      mariadb_data: the stock data provided from the distributor
        (rows of (stock_id, price), newest pull first)

    Returns:
    -----------
      - a formatted set of findings: a list of dicts, one per stock, with stock_id, stock_name, acronym,
        yesterday_price, today_price, difference and rate_of_change. Stocks without two prices
        (or with a previous price of 0) are left out, since no rate of change can be worked out.
    '''
    prices_by_stock = {}
    for (stock_id, price) in mariadb_data:
        prices_by_stock.setdefault(stock_id, []).append(price)

    findings = []
    for stock_id, prices in prices_by_stock.items():
        if len(prices) < 2 or prices[1] == 0:
            continue
        today_price, yesterday_price = prices[0], prices[1]
        difference = today_price - yesterday_price
        findings.append({
            "stock_id": stock_id,
            "stock_name": None,
            "acronym": None,
            "yesterday_price": yesterday_price,
            "today_price": today_price,
            "difference": difference,
            "rate_of_change": difference / yesterday_price,
        })
    return findings


def sort_findings(formatted_mariadb_data):
    '''
    Sorts the findings following getting them into a usable format.

    Parameters:
    -----------
      formatted_mariadb_data: the stock data provided from the distributor, formatted

    Returns:
    -----------
      - a formatted set of findings sorted by rate of change (biggest gainer first, biggest loser last)
    '''
    return sorted(formatted_mariadb_data, key=lambda finding: finding["rate_of_change"], reverse=True)


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
    gainers = [finding for finding in sorted_data if finding["rate_of_change"] > 0][:TOP_COUNT]
    losers = [finding for finding in reversed(sorted_data) if finding["rate_of_change"] < 0][:TOP_COUNT]

    def describe(findings):
        return "\n".join("{} ({}): {} -> {} ({:+.2%})".format(finding["stock_name"], finding["acronym"],
            finding["yesterday_price"], finding["today_price"], finding["rate_of_change"])
            for finding in findings) or "None today"

    query = ("Here are today's top three gainers and top three losers among the stocks we track.\n"
        "For each stock, please find a recent news article about it and write a short blurb on why it may have moved, "
        "naming the article you used. Keep the whole answer short enough for an email.\n\n"
        "Top gainers:\n{}\n\nTop losers:\n{}\n").format(describe(gainers), describe(losers))

    try:
        model = genai.GenerativeModel(GEMINI_MODEL)
        return model.generate_content(query).text
    except Exception as e:
        logger.error("AI query failed: {}".format(e))
        traceback.print_exc()
        return AI_ERROR_ANSWER


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
        (a "Stock Data" sheet with one row per stock, and an "Insight" sheet with the blurb)
    '''
    workbook = openpyxl.Workbook()

    data_sheet = workbook.active
    data_sheet.title = DATA_SHEET_TITLE
    data_sheet.append(XLSX_HEADER)
    for finding in sorted_data:
        data_sheet.append([finding["stock_name"], finding["acronym"], finding["yesterday_price"],
            finding["today_price"], finding["difference"], finding["rate_of_change"]])
        data_sheet.cell(row=data_sheet.max_row, column=len(XLSX_HEADER)).number_format = "0.00%"

    insight_sheet = workbook.create_sheet(INSIGHT_SHEET_TITLE)
    for line in blurb.splitlines():
        insight_sheet.append([line])

    workbook.save(xlsx_location)
