import ftrack_api
from pype.ftrack import BaseEvent


class TaskToVersionStatus(BaseEvent):

    def launch(self, session, entities, event):
        '''Propagates status from version to task when changed'''
        session.commit()
        self.log.info('>>> event {}'.format(
            event['data'].get('entities', [])[0]))
        # start of event procedure ----------------------------------
        for entity in event['data'].get('entities', []):

            # project = session.get('Show', entity['parents'][-1]['entityId'])

            # Filter non-assetversions
            if (
                entity['entityType'] == 'task' and
                'statusid' in entity['keys']
            ):

                task = session.get('Task', entity['entityId'])
                # self.log.info('>>> TASK {}'.format(task.items()))
                asset = session.query('Asset where parent.id is {0} and '
                                      'name is "renderAnimation"'.format(task['parent']['id'], )).first()
                last_version = asset['versions'][-1]
                self.log.info('>>> VERSION {}'.format(
                    asset['versions'][0]['version']))

                # self.log.info('>>>  {}'.format(task['parent']))
                ft_project = None
                # get project
                base_proj = task['link'][0]
                ft_project = session.get(base_proj['type'], base_proj['id'])
                if ft_project['name'] != 'lbb2':
                    self.log.info('>>> a dev project. SKIPPING')
                    continue

                task_status = session.get(
                    'Status', entity['changes']['statusid']['new']
                )

                self.log.info(task_status)

                task_type = task['type']['name']
                self.log.info(task_type)
                status_to_set = None

                if task_type in ['Animation']:
                    self.log.info(
                        '>>> task STATUS to set: [ {} ]'.format(task_status['name']))
                    status_to_set = task_status

                # if status_to_set is not None:
                #     query = 'Status where name is "{}"'.format(status_to_set)
                #     try:
                #         task_status = session.query(query).one()
                #     except Exception:
                #         self.log.info(
                #             'During update {}: Status {} was not found'.format(
                #                 entity['name'], status_to_set
                #             )
                #         )
                #         continue
                #
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
