import ftrack_api
from pype.ftrack import BaseEvent


class VersionToTaskStatus(BaseEvent):

    def launch(self, session, entities, event):
        '''Propagates status from version to task when changed'''
        # session.commit()

        # start of event procedure ----------------------------------
        for entity in event['data'].get('entities', []):

            # project = session.get('Show', entity['parents'][-1]['entityId'])

            # Filter non-assetversions
            if (
                entity['entityType'] == 'assetversion'
                and 'statusid' in entity['keys']
            ):

                version = session.get('AssetVersion', entity['entityId'])

                ft_project = None
                # get project
                base_proj = version['link'][0]
                ft_project = session.get(base_proj['type'], base_proj['id'])
                if ft_project['name'] != 'lbb2':
                    self.log.info('>>> not a LBB project. SKIPPING')
                    continue

                try:
                    version_status = session.get(
                        'Status', entity['changes']['statusid']['new']
                    )
                except Exception:
                    continue

                task_status = version_status
                task = version['task']

                query = 'Status where name is "{}"'.format('data')
                data_status = session.query(query).one()

                asset_name = version['asset']['name']
                asset_type = version['asset']['type']['name']

                status_to_set = None

                # Filter to versions with status change to "render complete"
                if version_status['name'].lower() == 'reviewed':
                    status_to_set = 'Change requested'

                if version_status['name'].lower() == 'approved':
                    status_to_set = 'Complete'

                if asset_type in ['Audio', 'Scene', 'Upload'] or 'renderReference' in asset_name:
                    self.log.info(
                        '>>> VERSION status to set: [ {} ]'.format(data_status['name']))
                    version['status'] = data_status
                    session.commit()
                    continue

                self.log.info(
                    '>>> status to set: [ {} ]'.format(status_to_set))

                if status_to_set is not None:
                    query = 'Status where name is "{}"'.format(status_to_set)
                    try:
                        task_status = session.query(query).one()
                    except Exception:
                        self.log.info(
                            'During update {}: Status {} was not found'.format(
                                entity['name'], status_to_set
                            )
                        )
                        continue

                # Proceed if the task status was set
                if task_status is not None:
                    # Get path to task
                    path = task['name']
                    for p in task['ancestors']:
                        path = p['name'] + '/' + path

                    # Setting task status
                    try:
                        if task['status'] is not task_status:
                            task['status'] = task_status
                            session.commit()
                            self.log.info('>>> [ {} ] updated to [ {} ]'.format(
                                path, task_status['name']))
                    except Exception as e:
                        self.log.warning('!!! [ {} ] status couldnt be set:\
                            [ {} ]'.format(path, e))


def register(session, **kw):
    '''Register plugin. Called when used as an plugin.'''
    if not isinstance(session, ftrack_api.session.Session):
        return

    VersionToTaskStatus(session).register()
