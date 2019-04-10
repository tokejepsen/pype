import ftrack_api
from pype.ftrack import BaseEvent


class TaskToVersionStatus(BaseEvent):

    def launch(self, session, event):
        '''Propagates status from version to task when changed'''
        session.commit()

        user = event['source']['user']['username']

        if user == "license@clothcatanimation.com":
            self.log.info(
                'status triggered automatically. Skipping version update')
            return
        # start of event procedure ----------------------------------
        for entity in event['data'].get('entities', []):

            # Filter non-assetversions
            if (
                entity['entityType'] == 'task'
                and 'statusid' in entity['keys']
            ):

                task = session.get('Task', entity['entityId'])
                asset = session.query('Asset where parent.id is {0} and '
                                      'name is "renderAnimation"'.format(task['parent']['id'], )).first()
                last_version = asset['versions'][-1]
                self.log.info('>>> VERSION {}'.format(
                    asset['versions'][0]['version']))

                task_status = session.get(
                    'Status', entity['changes']['statusid']['new']
                )

                self.log.info(task_status)

                task_type = task['type']['name']
                self.log.info(task_type)
                status_to_set = None

                if task_type in ['Animation']:
                    status_to_set = task_status
                if task_status['name'] == "Render":
                    status_to_set = None
                if "Review" not in task_status['name']:
                    status_to_set = None

                # self.log.info('>>> task STATUS to set: [ {} ]'.format(task_status['name']))

                # Proceed if the task status was set
                if status_to_set is not None:
                    # Get path to task
                    path = task['name']
                    for p in task['ancestors']:
                        path = p['name'] + '/' + path

                    # Setting task status
                    try:
                        if last_version['status'] is not task_status:
                            last_version['status'] = task_status
                            session.commit()
                            self.log.info('>>> [ {} / {} ] updated to [ {} ]'.format(
                                path, last_version['version'], task_status['name']))
                        else:
                            self.log.info('>>> Status identical. not updating')
                    except Exception as e:
                        self.log.warning('!!! [ {} ] status couldnt be set:\
                            [ {} ]'.format(path, e))


def register(session, **kw):
    '''Register plugin. Called when used as an plugin.'''
    if not isinstance(session, ftrack_api.session.Session):
        return

    event = TaskToVersionStatus(session)
    event.register()
