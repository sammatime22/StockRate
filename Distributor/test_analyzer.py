# Unit tests for analyzer.py, one per function. No MariaDB or Gemini is needed.
# sammatime22, 2026
#
# Setup on iSH (Alpine):
#   apk add python3 py3-pytest py3-openpyxl
#
# Run from the Distributor directory:
#   python3 -m pytest test_analyzer.py
import os
import sys
import types

import openpyxl
import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

# analyzer imports google.generativeai at the top, so stand it in before importing analyzer
if "google.generativeai" not in sys.modules:
    fake_genai = types.ModuleType("google.generativeai")
    fake_genai.GenerativeModel = None
    fake_google = types.ModuleType("google")
    fake_google.generativeai = fake_genai
    sys.modules["google"] = fake_google
    sys.modules["google.generativeai"] = fake_genai

import analyzer

# (stock_id, stock_name, acronym, yesterday's price, today's price); every rate of change is different
STOCKS = [
    (1, "Alphabet Inc Class A", "GOOGL:NASDAQ", 100.0, 110.0),      # +10%
    (2, "Apple Inc", "AAPL:NASDAQ", 200.0, 150.0),                  # -25%
    (3, "Microsoft Corp", "MSFT:NASDAQ", 50.0, 50.0),               # 0%
    (4, "Amazon.com Inc", "AMZN:NASDAQ", 180.0, 189.0),             # +5%
    (5, "NVIDIA Corp", "NVDA:NASDAQ", 120.0, 138.0),                # +15%
    (6, "Meta Platforms Inc", "META:NASDAQ", 500.0, 490.0),         # -2%
    (7, "Tesla Inc", "TSLA:NASDAQ", 250.0, 200.0),                  # -20%
    (8, "Netflix Inc", "NFLX:NASDAQ", 600.0, 612.0),                # +2%
    (9, "Advanced Micro Devices Inc", "AMD:NASDAQ", 160.0, 164.0),  # +2.5%
    (10, "Intel Corp", "INTC:NASDAQ", 30.0, 27.0),                  # -10%
    (11, "International Business Machines Corp", "IBM:NYSE", 200.0, 207.0),  # +3.5%
    (12, "Oracle Corp", "ORCL:NYSE", 140.0, 133.0),                 # -5%
    (13, "Salesforce Inc", "CRM:NYSE", 300.0, 324.0),               # +8%
    (14, "Adobe Inc", "ADBE:NASDAQ", 500.0, 470.0),                 # -6%
    (15, "PayPal Holdings Inc", "PYPL:NASDAQ", 80.0, 79.0),         # -1.25%
    (16, "Uber Technologies Inc", "UBER:NYSE", 70.0, 84.0),         # +20%
    (17, "Walt Disney Co", "DIS:NYSE", 100.0, 97.0),                # -3%
    (18, "Coca-Cola Co", "KO:NYSE", 200.0, 202.0),                  # +1%
    (19, "JPMorgan Chase & Co", "JPM:NYSE", 150.0, 138.0),          # -8%
    (20, "Walmart Inc", "WMT:NYSE", 100.0, 104.0),                  # +4%
]
# A canned Gemini answer for the 20 test stocks. The articles and links are made up (example.com), not real news.
CANNED_INSIGHT = """Today's biggest movers (canned test insight - these articles are made up)

Top gainers
- Uber Technologies Inc (UBER:NYSE) +20.00%: Shares jumped after Uber announced its robotaxi service is expanding to ten more cities.
  Article: "Uber Takes Robotaxis Nationwide" - https://news.example.com/2026/10/uber-robotaxi-expansion
- NVIDIA Corp (NVDA:NASDAQ) +15.00%: A new data center chip order from several cloud providers lifted the stock.
  Article: "Cloud Giants Line Up for NVIDIA's Next Chip" - https://news.example.com/2026/10/nvidia-data-center-orders
- Alphabet Inc Class A (GOOGL:NASDAQ) +10.00%: Strong cloud and ad revenue in its quarterly report beat expectations.
  Article: "Alphabet Earnings Beat on Cloud Growth" - https://news.example.com/2026/10/alphabet-earnings-beat

Top losers
- Apple Inc (AAPL:NASDAQ) -25.00%: Reports of weaker phone demand and a delayed product launch weighed on the stock.
  Article: "Apple Delays Launch Amid Soft Demand" - https://news.example.com/2026/10/apple-launch-delay
- Tesla Inc (TSLA:NASDAQ) -20.00%: Quarterly deliveries came in well below analyst forecasts.
  Article: "Tesla Deliveries Miss Estimates" - https://news.example.com/2026/10/tesla-deliveries-miss
- Intel Corp (INTC:NASDAQ) -10.00%: Intel cut its full-year outlook, citing slower PC sales.
  Article: "Intel Lowers Guidance on PC Slump" - https://news.example.com/2026/10/intel-guidance-cut
"""

STOCK_NAMES = {stock_id: (name, acronym) for (stock_id, name, acronym, _, _) in STOCKS}

# Biggest gainer first, biggest loser last
EXPECTED_ORDER = ["UBER:NYSE", "NVDA:NASDAQ", "GOOGL:NASDAQ", "CRM:NYSE", "AMZN:NASDAQ", "WMT:NYSE", "IBM:NYSE",
                  "AMD:NASDAQ", "NFLX:NASDAQ", "KO:NYSE", "MSFT:NASDAQ", "PYPL:NASDAQ", "META:NASDAQ", "DIS:NYSE",
                  "ORCL:NYSE", "ADBE:NASDAQ", "JPM:NYSE", "INTC:NASDAQ", "TSLA:NASDAQ", "AAPL:NASDAQ"]

# Newest pull first, as the distributor's query returns it: today's pull then yesterday's
MARIADB_DATA = ([(stock_id, today) for (stock_id, _, _, _, today) in reversed(STOCKS)] +
                [(stock_id, yesterday) for (stock_id, _, _, yesterday, _) in reversed(STOCKS)])


class FakeCursor:
    '''
    Answers the analyzer's stock name query from STOCK_NAMES.
    '''

    def __init__(self):
        self.stock_id = None

    def execute(self, sql):
        self.stock_id = int(sql.rsplit("=", 1)[1].rstrip(";"))

    def fetchall(self):
        return [STOCK_NAMES[self.stock_id]] if self.stock_id in STOCK_NAMES else []


class FakeGenAI:
    '''
    Records the question asked and gives a canned answer.
    '''

    def __init__(self, answer):
        self.answer = answer
        self.questions = []

    def GenerativeModel(self, model_name):
        fake = self

        class Model:
            def generate_content(self, query):
                fake.questions.append(query)
                return types.SimpleNamespace(text=fake.answer)

        return Model()


def finding(stock_id, with_names=True):
    '''
    The finding format_findings should produce for a stock in STOCKS (with names, as run_analyze adds them).
    '''
    (_, name, acronym, yesterday_price, today_price) = STOCKS[stock_id - 1]
    return {"stock_id": stock_id, "stock_name": name if with_names else None, "acronym": acronym if with_names else None,
            "yesterday_price": yesterday_price, "today_price": today_price, "difference": today_price - yesterday_price,
            "rate_of_change": (today_price - yesterday_price) / yesterday_price}


def xlsx_row(acronym):
    f = next(finding(stock_id) for (stock_id, _, stock_acronym, _, _) in STOCKS if stock_acronym == acronym)
    return (f["stock_name"], f["acronym"], f["yesterday_price"], f["today_price"], f["difference"], f["rate_of_change"])


def test_run_analyze(monkeypatch, tmp_path):
    fake_genai = FakeGenAI(CANNED_INSIGHT)
    monkeypatch.setattr(analyzer, "genai", fake_genai)
    xlsx_location = str(tmp_path / "report.xlsx")
    config = {"email_config": {"attachment": xlsx_location}}

    blurb = analyzer.run_analyze(MARIADB_DATA, FakeCursor(), config)

    assert blurb == CANNED_INSIGHT
    assert len(fake_genai.questions) == 1
    rows = list(openpyxl.load_workbook(xlsx_location)["Stock Data"].iter_rows(values_only=True))
    assert rows == [tuple(analyzer.XLSX_HEADER)] + [xlsx_row(acronym) for acronym in EXPECTED_ORDER]
    insight = [row[0] for row in openpyxl.load_workbook(xlsx_location)["Insight"].iter_rows(values_only=True) if row[0]]
    assert insight == [line for line in CANNED_INSIGHT.splitlines() if line]


def test_format_findings():
    # Stock 21 has only one price and stock 22 had a price of 0, so neither can have a rate of change.
    # Stocks 23 and 24 have a missing (-1) old or new price, and stock 25 uses -1 as an int, so all are left out.
    findings = analyzer.format_findings(MARIADB_DATA + [(21, 10.0), (22, 3.0), (22, 0.0), (23, -1.0), (23, 20.0),
                                                        (24, 30.0), (24, -1.0), (25, -1), (25, 40.0)])

    assert len(findings) == len(STOCKS)
    assert {f["stock_id"]: f for f in findings} == {stock_id: finding(stock_id, with_names=False)
                                                    for (stock_id, _, _, _, _) in STOCKS}


def test_sort_findings():
    findings = [finding(stock_id) for (stock_id, _, _, _, _) in STOCKS]

    sorted_findings = analyzer.sort_findings(findings)

    assert [f["acronym"] for f in sorted_findings] == EXPECTED_ORDER


def test_get_insight(monkeypatch):
    fake_genai = FakeGenAI(CANNED_INSIGHT)
    monkeypatch.setattr(analyzer, "genai", fake_genai)
    sorted_data = analyzer.sort_findings([finding(stock_id) for (stock_id, _, _, _, _) in STOCKS])

    blurb = analyzer.get_insight(sorted_data)

    assert blurb == CANNED_INSIGHT
    question = fake_genai.questions[0]
    gainers, losers = question.split("Top losers:")
    assert "Uber Technologies Inc (UBER:NYSE): 70.0 -> 84.0 (+20.00%)" in gainers
    assert "NVIDIA Corp (NVDA:NASDAQ): 120.0 -> 138.0 (+15.00%)" in gainers
    assert "Alphabet Inc Class A (GOOGL:NASDAQ): 100.0 -> 110.0 (+10.00%)" in gainers
    assert "Apple Inc (AAPL:NASDAQ): 200.0 -> 150.0 (-25.00%)" in losers
    assert "Tesla Inc (TSLA:NASDAQ): 250.0 -> 200.0 (-20.00%)" in losers
    assert "Intel Corp (INTC:NASDAQ): 30.0 -> 27.0 (-10.00%)" in losers
    # only the top three of each are asked about
    assert "Salesforce" not in question
    assert "JPMorgan" not in question
    assert "Microsoft" not in question


def test_shade_for_rate():
    # the biggest move gets the darkest shade, with white text
    assert analyzer.shade_for_rate(0.25, 0.25) == ("1E7B34", "FFFFFF")
    assert analyzer.shade_for_rate(-0.25, 0.25) == ("B3261E", "FFFFFF")
    # a small move is close to the light shade, with black text
    assert analyzer.shade_for_rate(0.0025, 0.25) == ("E4F3E8", "000000")
    assert analyzer.shade_for_rate(-0.0025, 0.25) == ("FBE6E4", "000000")
    # halfway is halfway between light and dark
    assert analyzer.shade_for_rate(0.125, 0.25) == ("82B88F", "000000")
    # no change, or nothing moved at all, gets no shading
    assert analyzer.shade_for_rate(0.0, 0.25) is None
    assert analyzer.shade_for_rate(0.0, 0.0) is None


def test_develop_xlsx(tmp_path):
    xlsx_location = str(tmp_path / "report.xlsx")
    sorted_data = analyzer.sort_findings([finding(stock_id) for (stock_id, _, _, _, _) in STOCKS])

    analyzer.develop_xlsx(sorted_data, CANNED_INSIGHT, xlsx_location)

    workbook = openpyxl.load_workbook(xlsx_location)
    assert workbook.sheetnames == ["Stock Data", "Insight"]
    data_sheet = workbook["Stock Data"]
    assert list(data_sheet.iter_rows(values_only=True)) == \
        [tuple(analyzer.XLSX_HEADER)] + [xlsx_row(acronym) for acronym in EXPECTED_ORDER]

    # each percent difference is shaded green (gain) or red (loss), darker the further from 0;
    # Apple's -25% is the biggest move, so it is the darkest
    for row, f in enumerate(sorted_data, start=2):
        cell = data_sheet.cell(row=row, column=6)
        shade = analyzer.shade_for_rate(f["rate_of_change"], 0.25)
        if f["rate_of_change"] == 0:
            assert shade is None and cell.fill.fill_type is None
            assert cell.number_format == "0" and cell.font.color.rgb[-6:] == "000000"
        else:
            assert cell.fill.fill_type == "solid" and cell.fill.start_color.rgb[-6:] == shade[0]
            assert cell.font.color.rgb[-6:] == shade[1] and cell.number_format == "0.00%"
    assert data_sheet["F21"].fill.start_color.rgb[-6:] == "B3261E"
    green = [data_sheet.cell(row=row, column=6).fill.start_color.rgb for row in range(2, 12)]
    assert green[0] != green[-1]

    insight = [row[0] for row in workbook["Insight"].iter_rows(values_only=True) if row[0]]
    assert insight == [line for line in CANNED_INSIGHT.splitlines() if line]
