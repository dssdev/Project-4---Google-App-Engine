#!/usr/bin/env python

"""
Session API endpoint 

"""


from datetime import datetime
import json
import os
import time

import endpoints
from protorpc import messages
from protorpc import message_types
from protorpc import remote

from google.appengine.api import memcache
from google.appengine.api import taskqueue
from google.appengine.api import urlfetch
from google.appengine.ext import ndb
from google.appengine.ext.db import GqlQuery

from models import Session
from models import SessionForm
from models import Speaker
from models import SpeakerForm
from models import SpeakerForms
from models import SpeakerQueryForm
from models import Conference
from models import SessionType

from settings import WEB_CLIENT_ID
from settings import ANDROID_CLIENT_ID
from settings import IOS_CLIENT_ID
from settings import ANDROID_AUDIENCE


EMAIL_SCOPE = endpoints.EMAIL_SCOPE
API_EXPLORER_CLIENT_ID = endpoints.API_EXPLORER_CLIENT_ID
MEMCACHE_ANNOUNCEMENTS_KEY = "RECENT_ANNOUNCEMENTS"

SESSION_POST_REQUEST = endpoints.ResourceContainer(
	SessionForm,
	websafeConferenceKey=messages.StringField(1)
)


def _getUserId():
    """A workaround implementation for getting userid."""
    auth = os.getenv('HTTP_AUTHORIZATION')
    bearer, token = auth.split()
    token_type = 'id_token'
    if 'OAUTH_USER_ID' in os.environ:
        token_type = 'access_token'
    url = ('https://www.googleapis.com/oauth2/v1/tokeninfo?%s=%s'
           % (token_type, token))
    user = {}
    wait = 1
    for i in range(3):
        resp = urlfetch.fetch(url)
        if resp.status_code == 200:
            user = json.loads(resp.content)
            break
        elif resp.status_code == 400 and 'invalid_token' in resp.content:
            url = ('https://www.googleapis.com/oauth2/v1/tokeninfo?%s=%s'
                   % ('access_token', token))
        else:
            time.sleep(wait)
            wait = wait + i
    return user.get('user_id', '')



@endpoints.api(name='session', version='v1',
    audiences=[ANDROID_AUDIENCE],
    allowed_client_ids=[WEB_CLIENT_ID, API_EXPLORER_CLIENT_ID, ANDROID_CLIENT_ID, IOS_CLIENT_ID],
    scopes=[EMAIL_SCOPE])
class SessionApi(remote.Service):
    """Session API v0.1"""

    def _copySessionToForm(self, session):
        """Create SessionForm object from Session entity"""
        sf = SessionForm()
        for field in sf.all_fields():
            if hasattr(session, field.name):
            #need strings for date/time property and speaker - Enum for session
                if field.name in ['date', 'starttime']:
                    setattr(sf, field.name, str(getattr(session, field.name)))
                #get the speaker name from the key
                elif field.name == 'speaker':
                    setattr(sf, field.name, getattr(session, field.name).get().name)
                #get enum for session
                elif field.name == 'typeofsession' and getattr(session, field.name) is not None:
                    setattr(sf, field.name, getattr(SessionType, getattr(session, field.name)))
                else:
                    setattr(sf, field.name, getattr(session, field.name))
            elif field.name == "websafeKey":
                setattr(sf, field.name, session.key.urlsafe())
        sf.check_initialized()
        return sf

    @endpoints.method(SpeakerQueryForm,SpeakerForms, path='querySpeakers', http_method='POST',
                      name='querySpeakers')
    def querySpeakers(self, request):
        """
        Searches speakers (currently limited to name) if name is entered or
        returns all speaks for no name.
        :param request: form request data
        :return: List of SpeakerFrom for query result
        """
        speakers = Speaker()
        if request.name is None:
           speakers = speakers.query().fetch()
        else:
           speakers = speakers.query(Speaker.name == request.name).fetch()
        sfList = []

        for speaker in speakers:
            sf = SpeakerForm()
            setattr(sf, "name", speaker.name)
            setattr(sf, "websafeKey", speaker.key.urlsafe())
            sfList.append(sf)
        return SpeakerForms(items=sfList)

    @endpoints.method(SpeakerForm,SpeakerForm, path='speaker', http_method='POST', 
    	name='createSpeaker')
    def createSpeaker(self, request):
        """
        Add a speaker
        :param request: form data with speaker name
        :return: the request that was processed
        """
    	if not request.name:
    		raise endpoints.BadRequestException("Speaker name required")

    	data = {field.name: getattr(request, field.name) for field in request.all_fields()}
    	speaker = Speaker()
    	speaker.name = data["name"]

    	speaker.put()

        return request

    @endpoints.method(SESSION_POST_REQUEST,SessionForm, path='createSession', http_method='POST',
                      name='createSession')
    def createSession(self, request):

        #Move this to a method if we need to do it somewhere else
        user = endpoints.get_current_user()
        print "user: %s" % user
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')

        if not request.name:
            raise endpoints.BadRequestException("Session name required")
        # get Profile from datastore
        user_id = _getUserId()
        print "user id: %s" % user_id

        #Get the conference object for the websafe key
        conf = ndb.Key(urlsafe=request.websafeConferenceKey).get()

        if not conf:
            raise endpoints.BadRequestException("Invalid conference key")

        if conf.organizerUserId != user_id:
            raise endpoints.UnauthorizedException("You can only add sessions to your conferences")

        data = {field.name: getattr(request, field.name) for field in request.all_fields()}
        print data
        del data['websafeConferenceKey']

        #I'm ok with 'None' entries, except for Speaker
        #Requires DB be seeded with an undefined Speaker
        #We could check if the speaker doesn't exist and add them first
        #but it wouldn't jive with the overall design and how I envision the APIs
        #being consumed. Might consider using the speaker key and not the name as well.
        if data['speaker'] is None:
            data['speaker'] = Speaker.query(Speaker.name == 'Undefined').get().key
        else:
            speaker = Speaker.query(Speaker.name == data['speaker']).get().key
            if not speaker:
                raise endpoints.BadRequestException("Unknown speaker")
            data['speaker'] = speaker

        if data['date']:
            data['date'] = datetime.strptime(data['date'], "%Y-%m-%d").date()

        if data['starttime']:
            data['starttime'] = datetime.strptime(data['starttime'], "%H:%M").time()

        if data['typeofsession']:
            data['typeofsession'] = str(data['typeofsession'])

        data['parent'] = conf.key

        return self._copySessionToForm((Session(**data).put()).get())



