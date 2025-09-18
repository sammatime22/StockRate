# A program used to send collected data via email.
# sammatime22, 2024
import datetime
import google.generativeai as genai
import mariadb
import time
import traceback
import yagmail
import yaml

# Constants to pull from config file
CONFIG = "distributor-config-private.yaml"
MARIA_DB_CONFIG = "maria_db_config"
USER = "user"
PASSWORD = "password"
MARIA_DB_IP = "host"
MARIA_DB_PORT = "port"
MARIA_DB_DATABASE = "database"
GOOGLE_GEMINI_CONFIG = "google_gemini_config"
MY_KEY = "my_key"
EMAIL_CONFIG = "email_config"
ATTACHMENT = "attachment"
EMAIL_ADDRESS = "email_address"
OAUTH2_FILE = "oauth2_file"

SELECT_ALL_DATA_FROM_PAST_DAYS="SELECT stock_id, price FROM CLEANED_DATA ORDER BY pull_id DESC LIMIT {};"
SELECT_STOCK_NAME_AND_ACRONYM="SELECT stock_name, acronym FROM STOCK WHERE stock_id={};"
SELECT_USERS="SELECT email FROM USER;"

LIMIT = 20 # temp
 
def maria_db_factory(user, password, host, port, database):
    '''
    Returns a connection cursor to mariadb
    '''
    conn = mariadb.connect(user=user, password=password, host=host, port=port, database=database)
    conn.autocommit = True
    return conn.cursor()


def format_findings(findings, mariadb_cursor):
    '''
    Properly formats the data retrieved from the DB into a CSV format
    '''
    try:
        contents = "Stock Name,Stock Acronym,Yesterday's Price,Today's Price,Total Difference,Percent Difference\n"
        findings_dict = {}
        for (stock_id, price) in findings:
            # add findings to findings_dict list
            if findings_dict.get(stock_id) == None:
                findings_dict[stock_id] = []
            findings_dict[stock_id].append(price)
        
        # run calculations on findings, putting this in CSV format
        for key, value in findings_dict.items():
            mariadb_cursor.execute(SELECT_STOCK_NAME_AND_ACRONYM.format(key))
            stock_of_interest_data = mariadb_cursor.fetchall()
            for (stock_name, stock_acronym) in stock_of_interest_data:
                contents = contents + "{},{},{},{},{},{}\n".format(stock_name, stock_acronym, value[1], value[0], value[0] - value[1], (value[0] - value[1])/value[1])
        return contents
    except Exception as e:
        traceback.print_exc()
        return None


if __name__ == '__main__':

    # get config loaded
    with open(CONFIG, 'r') as emailer_config_file:
        emailer_config_config = yaml.safe_load(emailer_config_file)

    # connect to the DB
    mariadb_cursor = maria_db_factory(emailer_config_config[MARIA_DB_CONFIG][USER], \
        emailer_config_config[MARIA_DB_CONFIG][PASSWORD], \
        emailer_config_config[MARIA_DB_CONFIG][MARIA_DB_IP], \
        emailer_config_config[MARIA_DB_CONFIG][MARIA_DB_PORT], \
        emailer_config_config[MARIA_DB_CONFIG][MARIA_DB_DATABASE])

    # Gemini setup
    genai.configure(api_key=emailer_config_config[GOOGLE_GEMINI_CONFIG][MY_KEY])
    model = genai.GenerativeModel("gemini-1.5-flash")

    # check and gather the stock data from one pull ago and the most recent pull
    mariadb_cursor.execute(SELECT_ALL_DATA_FROM_PAST_DAYS.format(LIMIT))
    data = format_findings(mariadb_cursor.fetchall(), mariadb_cursor)

    # ask AI for some insight
    if data is not None:
        query = "Can you please tell me out of this data which three stocks had the biggest change?\n" + data

        # put AI response in email
        ai_response = model.generate_content(query)

        # get recipients from DB
        mariadb_cursor.execute(SELECT_USERS)
        recipient_list = mariadb_cursor.fetchall()
        recipients = []
        for recipient in recipient_list:
            recipients.append(recipient[0])

        # put content in .csv
        csv_content = open(emailer_config_config[EMAIL_CONFIG][ATTACHMENT], "w+")
        csv_content.truncate(0) # erase data before writing
        csv_content.write(data)
        csv_content.close()
        yag = yagmail.SMTP(emailer_config_config[EMAIL_CONFIG][EMAIL_ADDRESS], oauth2_file=emailer_config_config[EMAIL_CONFIG][OAUTH2_FILE])
        yag.send(
            to=recipients,
            subject="Todays Stock Data " + str(datetime.datetime.now()),
            contents=ai_response.text,
            attachments=[emailer_config_config[EMAIL_CONFIG][ATTACHMENT]]
        )
    else:
        query = "Can you write an apology statement saying the data pipeline had an issue developing today's results, and we are working to fix it? Don't provide a date."

        # put AI response in email
        ai_response = model.generate_content(query)

        # get recipients from DB
        mariadb_cursor.execute(SELECT_USERS)
        recipient_list = mariadb_cursor.fetchall()
        recipients = []
        for recipient in recipient_list:
            recipients.append(recipient[0])

        yag = yagmail.SMTP(emailer_config_config[EMAIL_CONFIG][EMAIL_ADDRESS], oauth2_file=emailer_config_config[EMAIL_CONFIG][OAUTH2_FILE])
        yag.send(
            to=recipients,
            subject="StockRate Pipeline Issue " + str(datetime.datetime.now()),
            contents=ai_response.text
        )
