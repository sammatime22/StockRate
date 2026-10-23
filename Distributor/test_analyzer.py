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
    fake_genai = FakeGenAI("Uber rose and Apple fell.")
    monkeypatch.setattr(analyzer, "genai", fake_genai)
    xlsx_location = str(tmp_path / "report.xlsx")
    config = {"email_config": {"attachment": xlsx_location}}

    blurb = analyzer.run_analyze(MARIADB_DATA, FakeCursor(), config)

    assert blurb == "Uber rose and Apple fell."
    assert len(fake_genai.questions) == 1
    rows = list(openpyxl.load_workbook(xlsx_location)["Stock Data"].iter_rows(values_only=True))
    assert rows == [tuple(analyzer.XLSX_HEADER)] + [xlsx_row(acronym) for acronym in EXPECTED_ORDER]


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
    fake_genai = FakeGenAI("Here is today's insight.")
    monkeypatch.setattr(analyzer, "genai", fake_genai)
    sorted_data = analyzer.sort_findings([finding(stock_id) for (stock_id, _, _, _, _) in STOCKS])

    blurb = analyzer.get_insight(sorted_data)

    assert blurb == "Here is today's insight."
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


def test_develop_xlsx(tmp_path):
    xlsx_location = str(tmp_path / "report.xlsx")
    sorted_data = analyzer.sort_findings([finding(stock_id) for (stock_id, _, _, _, _) in STOCKS])

    analyzer.develop_xlsx(sorted_data, "First line.\nSecond line.", xlsx_location)

    workbook = openpyxl.load_workbook(xlsx_location)
    assert workbook.sheetnames == ["Stock Data", "Insight"]
    data_sheet = workbook["Stock Data"]
    assert list(data_sheet.iter_rows(values_only=True)) == \
        [tuple(analyzer.XLSX_HEADER)] + [xlsx_row(acronym) for acronym in EXPECTED_ORDER]
    assert all(data_sheet.cell(row=row, column=6).number_format == "0.00%" for row in range(2, len(STOCKS) + 2))
    assert list(workbook["Insight"].iter_rows(values_only=True)) == [("First line.",), ("Second line.",)]
