import os
import sys
import re
import ftrack_api
from pype.ftrack import BaseEvent
from app import api


ignore_me = True


class Test_Event(BaseEvent):

    priority = 10000

    def launch(self, session, event):

        '''just a testing event'''

        self.log.info(event['source']['user']['username'])

        return True


def register(session, **kw):
    '''Register plugin. Called when used as an plugin.'''
    if not isinstance(session, ftrack_api.session.Session):
        return

    Test_Event(session).register()
