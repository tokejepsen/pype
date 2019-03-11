# import ftrack_api
# from pype.ftrack import BaseEvent
#
#
# class DataStatusEvents(BaseEvent):
#
#     def launch(self, session, entities, event):
#         '''just a testing event'''
#
#         # self.log.info(event)
#         # start of event procedure ----------------------------------
#         for entity in event['data'].get('entities', []):
#
#             # Update task thumbnail from published version
#             if (entity['entityType'] == 'assetversion' and
#                     entity['action'] == 'add'):
#
#                 version = session.get('AssetVersion', entity['entityId'])
#
#                 asset_type = version['asset']['type']['name']
#
#                 query = 'Status where name is "{}"'.format('data')
#                 data_status = session.query(query).one()
#                 self.log.info(
#                     '>>> data status {}'.format(data_status))
#
#                 # # getting version status
#                 if asset_type in ['Scene']:
#                     # version_status = utils.get_status_by_name('data')
#                     version['status'] = data_status
#                     self.log.info(
#                         '>>> updating data status on {}'.format(version))
#                     session.commit()
#
#
# def register(session, **kw):
#     '''Register plugin. Called when used as an plugin.'''
#     if not isinstance(session, ftrack_api.session.Session):
#         return
#
#     event = DataStatusEvents(session)
#     event.register()
