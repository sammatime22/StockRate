# A class used to collect email data from the web.
# sammatime22, 2024
import google_bard
import yagmail

def maria_db_factory(user, password, host, port, database):
    '''
    Returns a connection cursor to mariadb
    '''
    conn = mariadb.connect(user=user, password=password, host=host, port=port, database=database)
    conn.autocommit = True
    return conn.cursor()


def format_findings(findings):
    '''

    '''
    return None


if __name__ == '__main__':
    while True:
        # wait a bit
        time.sleep(NAP_TIME)

        # check and gather the stock data from one pull ago and the most recent pull
        data = format_findings(None)

        # ask AI what the biggest change was
        query = "Can you please tell me out of this data which three stocks had the biggest change?" + data

        # put AI response in email

        # get recipients from DB

        # put content in .csv
        with csv_content as open("w", "todaysdata.csv"):
            csv_content.write(data)

            # sign and deliver
            yag.send(
                to=recipients,
                subject="Todays Stock Data",
                contents=ai_response,
                attachments="todaysdata.csv"
            )
            csv_content.truncate(0) # erase the data
