# A program used to analyze data prior to distribution.
# sammatime, 2026
import google.generativeai as genai
import logging
import openpyxl
from openpyxl.styles import Font, PatternFill
import traceback

# Config keys
EMAIL_CONFIG = "email_config"
ATTACHMENT = "attachment"

# SQL queries
SELECT_STOCK_NAME_AND_ACRONYM = "SELECT stock_name, acronym FROM STOCK WHERE stock_id={};"

# A price of -1 means the price is missing (-1 == -1.0, so both forms match)
MISSING_PRICE = -1

# AI settings
GEMINI_MODEL = "gemini-2.0-flash"
AI_ERROR_ANSWER = "An error occurred in querying the AI agent."
TOP_COUNT = 3

# xlsx layout
DATA_SHEET_TITLE = "Stock Data"
INSIGHT_SHEET_TITLE = "Insight"
XLSX_HEADER = ["Stock Name", "Ticker", "Market", "Yesterday's Price", "Today's Price", "Total Difference", "Percent Difference"]
DATA_COLUMN_WIDTHS = [38, 10, 10, 18, 16, 18, 20]
INSIGHT_COLUMN_WIDTH = 120

# Percent difference shading: a move near 0 gets the light color, the biggest move of the day gets the dark one
GAIN_LIGHT, GAIN_DARK = (0xE6, 0xF4, 0xEA), (0x1E, 0x7B, 0x34)
LOSS_LIGHT, LOSS_DARK = (0xFC, 0xE8, 0xE6), (0xB3, 0x26, 0x1E)
BLACK, WHITE = "000000", "FFFFFF"

# Insight headlines: the AI is asked to head its sections with these, and the xlsx shows them bold with an emoji
# (there is no bull face emoji, so the gainers get a cow face)
GAINERS_HEADLINE = "Top gainers"
LOSERS_HEADLINE = "Top losers"
HEADLINE_EMOJIS = {GAINERS_HEADLINE: "\U0001F42E", LOSERS_HEADLINE: "\U0001F43B"}  # cow face, bear face

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
        yesterday_price, today_price, difference and rate_of_change. Stocks without two prices,
        with a previous price of 0, or with either price of -1 (a missing price) are left out,
        so they appear in neither the xlsx nor the blurb.
    '''
    prices_by_stock = {}
    for (stock_id, price) in mariadb_data:
        prices_by_stock.setdefault(stock_id, []).append(price)

    findings = []
    for stock_id, prices in prices_by_stock.items():
        if len(prices) < 2:
            continue
        today_price, yesterday_price = prices[0], prices[1]
        if MISSING_PRICE in (today_price, yesterday_price) or yesterday_price == 0:
            continue
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
        "naming the article you used. Keep the whole answer short enough for an email.\n"
        "Start the gainers section with a line saying only \"{}\" and the losers section with a line saying only \"{}\".\n\n"
        "Top gainers:\n{}\n\nTop losers:\n{}\n").format(GAINERS_HEADLINE, LOSERS_HEADLINE, describe(gainers), describe(losers))

    try:
        model = genai.GenerativeModel(GEMINI_MODEL)
        return model.generate_content(query).text
    except Exception as e:
        logger.error("AI query failed: {}".format(e))
        traceback.print_exc()
        return AI_ERROR_ANSWER


def shade_for_rate(rate_of_change, max_abs_rate):
    '''
    Works out the shading for a percent difference cell.

    Parameters:
    -----------
      rate_of_change: the stock's rate of change
      max_abs_rate: the biggest rate of change (up or down) among all the stocks, which gets the darkest shade

    Returns:
    -----------
      - (fill color, font color) as hex strings: green for a gain and red for a loss, lighter the closer
        the rate is to 0 (with white text on the darker shades), or None for no change
    '''
    if rate_of_change == 0 or max_abs_rate == 0:
        return None
    light, dark = (GAIN_LIGHT, GAIN_DARK) if rate_of_change > 0 else (LOSS_LIGHT, LOSS_DARK)
    strength = min(abs(rate_of_change) / max_abs_rate, 1.0)
    fill = "".join("{:02X}".format(round(l + (d - l) * strength)) for l, d in zip(light, dark))
    return fill, WHITE if strength > 0.5 else BLACK


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
        (a "Stock Data" sheet with one row per stock in alphabetical order by market then name, its acronym
        split into ticker and market, and its percent difference shaded green or red; and an "Insight" sheet
        with the blurb, its "Top gainers"/"Top losers" headlines in bold with a cow face/bear face emoji)
    '''
    workbook = openpyxl.Workbook()

    data_sheet = workbook.active
    data_sheet.title = DATA_SHEET_TITLE
    data_sheet.append(XLSX_HEADER)
    for cell in data_sheet[1]:
        cell.font = Font(bold=True)
    for column, width in zip("ABCDEFG", DATA_COLUMN_WIDTHS):
        data_sheet.column_dimensions[column].width = width

    rows = []
    for finding in sorted_data:
        # "GOOGL:NASDAQ" -> ticker "GOOGL", market "NASDAQ"
        ticker, _, market = (finding["acronym"] or "").partition(":")
        rows.append((finding["stock_name"] or "", ticker, market, finding))
    rows.sort(key=lambda row: (row[2].casefold(), row[0].casefold()))

    max_abs_rate = max((abs(finding["rate_of_change"]) for finding in sorted_data), default=0)
    for (stock_name, ticker, market, finding) in rows:
        data_sheet.append([stock_name, ticker, market, finding["yesterday_price"],
            finding["today_price"], finding["difference"], finding["rate_of_change"]])
        percent_cell = data_sheet.cell(row=data_sheet.max_row, column=len(XLSX_HEADER))
        shade = shade_for_rate(finding["rate_of_change"], max_abs_rate)
        if shade is None:
            # no change: just a black 0
            percent_cell.number_format = "0"
            percent_cell.font = Font(color=BLACK)
        else:
            fill, font = shade
            percent_cell.number_format = "0.00%"
            percent_cell.fill = PatternFill(fill_type="solid", start_color=fill, end_color=fill)
            percent_cell.font = Font(color=font)

    insight_sheet = workbook.create_sheet(INSIGHT_SHEET_TITLE)
    insight_sheet.column_dimensions["A"].width = INSIGHT_COLUMN_WIDTH
    headlines = {headline.casefold(): headline for headline in HEADLINE_EMOJIS}
    for line in blurb.splitlines():
        # match the headline even if the AI dressed it up, like "**Top Gainers**" or "## Top gainers:"
        headline = headlines.get(line.strip(" *#_:").casefold())
        if headline:
            insight_sheet.append(["{} {}".format(HEADLINE_EMOJIS[headline], headline)])
            insight_sheet.cell(row=insight_sheet.max_row, column=1).font = Font(bold=True)
        else:
            insight_sheet.append([line])

    workbook.save(xlsx_location)
