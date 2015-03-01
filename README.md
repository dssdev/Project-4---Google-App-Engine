App Engine application for the Udacity training course.

App ID for endpoint - dssdevnano

The web client ID in this app supports http://localhost:8080 and http://localhost:10080

Once you clone this repository, just drag the folder into the GoogleAppEngineLauncher

For instruction on installing the Google App Engine SDK and AppEngineLauncher -
https://cloud.google.com/appengine/downloads

IMPORTANT: Once the app is running, Speaker must be seeded in the datastore with an entity with the name of
'Undefined'.

Design Choices -

I want to maintain a many-to-many type relationship between Sessions and Speakers, so Sessions stores Speaker as a
KeyProperty and Speaker is it's own entity. Having Speaker as it's own entity would allow to give Speaker additional
properties other than name and easily get all the Speaker information when querying Sessions. Sessions are always
assigned a parent Conference to assist with querying for Sessions by Conference.

Session is stood up as it's own service and not combined with conference mainly because I wanted to learn how to do
that. One could make an argument that Session is coupled with Conference and deserves to be in the same Service. I
wouldn't necessarily argue against that, but it was nice to not have to dig through all the Conference endpoints in
API Explorer to find the Session related ones, so I left it as it.

The two additional queries implemented are createSpeaker and querySpeaker. Since Speaker is it's own entity, we need
to be able to interact with it.

Query problem -

You can't have inequality filters with multiple properties, so we can filter the rest in Python.
See nonWorkshopAfterSeven for solution.

