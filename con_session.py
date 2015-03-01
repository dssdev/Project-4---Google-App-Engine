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
from models import SessionForms
from models import Speaker
from models import SpeakerForm
from models import SpeakerForms
from models import SpeakerQueryForm
from models import Profile
from models import SessionType
from models import FeaturedSpeakerForm

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

SESSION_FOR_CONFERENCE_GET_REQUEST = endpoints.ResourceContainer(
    websafeConferenceKey=messages.StringField(1)
)

SESSION_BY_TYPE_GET_REQUEST = endpoints.ResourceContainer(
    websafeConferenceKey=messages.StringField(1),
    typeOfSession=messages.EnumField(SessionType, 2)
)

SESSION_KEY_POST = endpoints.ResourceContainer(
    websafeSessionKey=messages.StringField(1)
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

    def _copySessionToForms(self, sessions):
        """
        Create SessionForms for multiple sessions
        :param sessions: List of session entities
        :return: SessionForms for given sessions
        """
        sfs = SessionForms()
        sfList = []

        for session in sessions:
            sfList.append(self._copySessionToForm(session))

        return SessionForms(items=sfList)

    def _getProfileFromUser(self):
        """Return user Profile from datastore, creating new one if non-existent."""
        # make sure user is authed
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')

        # get Profile from datastore
        user_id = _getUserId()
        p_key = ndb.Key(Profile, user_id)
        profile = p_key.get()
        # create new Profile if not there
        if not profile:
            raise endpoints.BadRequestException('No profile exists')

        return profile

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
        """
        Create session entity
        :param request: SessionForm + conference key
        :return: Session entity created in SessionForm
        """
        #Move this to a method if we need to do it somewhere else
        user = endpoints.get_current_user()
        print "user: %s" % user
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')

        if (not request.name or not request.websafeConferenceKey):
            raise endpoints.BadRequestException("Session name and conf key required")
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

        ##### Memcaching #######
        #Get sessions for parent conference with the same speaker
        sessions = Session.query(ancestor=data['parent']).filter(Session.speaker == data['speaker']).fetch()
        #We haven't committed this speaker yet, so any return indicates speaker > 1
        if sessions:
            session_names = [session.name for session in sessions]
            session_names.append(data['name'])
            cache = {'speaker': request.speaker if request.speaker is not None else 'Undefined',
                     'sessions': session_names}
            if not memcache.set('featured_speaker', cache):
                print ("memcache ain't working")



        return self._copySessionToForm((Session(**data).put()).get())

    @endpoints.method(SpeakerForm, SessionForms, path='sessionBySpeaker', http_method='GET',
                      name='sessionBySpeaker')
    def sessionBySpeaker(self,request):
        """
        Gets sessions by speaker. Either name or key can be used. If both are used,
        name is used first and if not found, key is used.
        :param request: Request with speaker name and/or key
        :return: SessionForms
        """
        if (not request.name and not request.websafeKey):
            raise endpoints.BadRequestException("Must have name or key")
        s_key = None
        if request.name:
            speaker = Speaker().query(Speaker.name == request.name).get()
            if speaker is not None:
                s_key = speaker.key
        #fall through to key if name was passed but not found and key is present
        if (s_key is None and request.websafeKey):
            s_key = ndb.Key(urlsafe=request.websafeKey)

        if s_key is None:
            raise endpoints.BadRequestException("Invalid name and/or key")

        return self._copySessionToForms(Session().query(Session.speaker == s_key).fetch())

    @endpoints.method(SESSION_FOR_CONFERENCE_GET_REQUEST, SessionForms, path='sessionByConf', http_method='GET',
                    name='sessionByConf')
    def sessionByConf(self, request):
        """
        Gets all session by conference
        :param request: conference key
        :return: SessionForms
        """
        if not request.websafeConferenceKey:
            endpoints.BadRequestException("Must have key")

        c_key = ndb.Key(urlsafe=request.websafeConferenceKey)

        if not c_key:
            endpoints.BadRequestException("Invalid key")

        return self._copySessionToForms(Session.query(ancestor = c_key).fetch())

    @endpoints.method(SESSION_BY_TYPE_GET_REQUEST, SessionForms, path='sessionByType', http_method='GET',
                      name='sessionByType')
    def sessionByType(self, request):
        """
        Get all sessions by type for a given conference
        :param request: conference key and SessionType enum
        :return: SessionForms
        """
        if (not request.websafeConferenceKey and not request.typeOfSession):
            raise endpoints.BadRequestException("Both key and type must be specified")

        #Check the type, just in case
        print("request.typeOfSession %s" % request.typeOfSession)
        if (str(request.typeOfSession) not in SessionType.to_dict().keys()):
            raise endpoints.BadRequestException("Invalid session type")

        c_key = ndb.Key(urlsafe=request.websafeConferenceKey)

        if not c_key:
            endpoints.BadRequestException("Invalid key")

        return self._copySessionToForms(Session.query(ancestor = c_key).
                                        filter(Session.typeofsession == str(request.typeOfSession)).fetch())

    @endpoints.method(SESSION_KEY_POST,SessionForm, path='addSessionToWishlist', http_method='POST',
                      name='addSessionToWishlist')
    def addSessionToWishlist(self,request):
        """
        Add the session to the user's list of favorite sessions
        :param request: key for session
        :return: SessionForm for session selected as favorite
        """
        if not request.websafeSessionKey:
            raise endpoints.BadRequestException('Need a session key')

        session = ndb.Key(urlsafe=request.websafeSessionKey)

        if not session:
            raise endpoints.BadRequestException('Invalid session')

        profile = self._getProfileFromUser()
        profile.favoriteSessions.append(session)
        profile.put()

        return self._copySessionToForm(session.get())

    @endpoints.method(message_types.VoidMessage,SessionForms, path='getSessionsInWishlist', http_method='GET',
                      name='getSessionsInWishlist')
    def getSessionsInWishlist(self,request):
        """
        All sessions in wishlist for current user
        """
        profile = self._getProfileFromUser()

        if not profile:
            raise endpoints.BadRequestException('Profile does not exist for user')

        return SessionForms(items=[self._copySessionToForm(session)
                                   for session in ndb.get_multi(profile.favoriteSessions)])


    @endpoints.method(message_types.VoidMessage,SessionForms, path='nonWorkshopAfterSeven', http_method='GET',
                      name='nonWorkshopAfterSeven')
    def nonWorkshopAfterSeven(self,request):
        """
        get sessions after 1900 and and not a workshop
        """
        #can't have inequality filters w/ multiple properties
        afterSevenSessions = Session.query(ndb.AND(
            Session.starttime >= datetime.strptime('19:00',"%H:%M").time(),
            Session.starttime != None
        )).fetch()

        sessions = []
        for session in afterSevenSessions:
            if (session.typeofsession != 'WORKSHOP'):
                sessions.append(session)


        return self._copySessionToForms(sessions)

    @endpoints.method(message_types.VoidMessage,FeaturedSpeakerForm, path='featuredSpeaker', http_method='GET',
                      name='featuredSpeaker')
    def featuredSpeaker(self, request):
        """
        Returning the featured speakers in the memcache since the project doesn't
        give me any details for this endpoint
        """
        fs = memcache.get('featured_speaker')
        if not fs:
            raise endpoints.BadRequestException('Memcache miss')

        fsf = FeaturedSpeakerForm()

        fsf.speakerName = fs['speaker']
        for sessionName in fs['sessions']:
            fsf.sessionNames.append(sessionName)

        return fsf