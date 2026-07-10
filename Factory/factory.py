# A means to develop various common connectors and other utilities.
# sammatime22, 2026
import stomp

HB_INTERVAL = 0
IP = "ip"
PORT = "port"
USERNAME = "username"
PASSWORD = "password"
SUBSCRIPTIONS = "subscriptions"

def stomp_factory(listener, id, stomp_config):
    ''' 
    Creates a STOMP connection to listen for incoming jobs
    
    A stomp config should have the following:
      ip
      port
      heartbeat_interval
      username
      password
      a list of data destinations
    '''
    stomp_connection = stomp.Connection([(stomp_config[IP], stomp_config[PORT])], heartbeats=(HB_INTERVAL, HB_INTERVAL))
    stomp_connection.set_listener('', listener)
    stomp_connection.connect(stomp_config[USERNAME], stomp_config[PASSWORD])
    for sub in stomp_config[SUBSCRIPTIONS]:
        stomp_connection.subscribe(destination=sub, id=id)
        id = id + 1
    listener.set_stomp_connection(stomp_connection)
