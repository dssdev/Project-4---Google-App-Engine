from conference import ConferenceApi
from con_session import SessionApi
import endpoints

api = endpoints.api_server([ConferenceApi, SessionApi]) # register API