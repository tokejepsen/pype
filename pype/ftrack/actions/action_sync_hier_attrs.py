import os
import sys
import argparse
import logging
import collections

from pype.vendor import ftrack_api
from pype.ftrack import BaseAction, lib
from avalon.tools.libraryloader.io_nonsingleton import DbConnector
from bson.objectid import ObjectId


class SyncHierarchicalAttrs(BaseAction):

    db_con = DbConnector()
    ca_mongoid = lib.get_ca_mongoid()

    #: Action identifier.
    identifier = 'sync.hierarchical.attrs'
    #: Action label.
    label = 'Sync hierarchical attributes'
    #: Action description.
    description = 'Synchronize hierarchical attributes'
    #: Icon
    icon = '{}/ftrack/action_icons/SyncHierarchicalAttrs.svg'.format(
        os.environ.get('PYPE_STATICS_SERVER', '')
    )

    #: roles that are allowed to register this action
    role_list = ['Administrator']

    def discover(self, session, entities, event):
        ''' Validation '''
        for entity in entities:
            if (
                entity.get('context_type', '').lower() in ('show', 'task') and
                entity.entity_type.lower() != 'task'
            ):
                return True
        return False

    def launch(self, session, entities, event):
        # Collect hierarchical attrs
        custom_attributes = {}
        all_avalon_attr = session.query(
            'CustomAttributeGroup where name is "avalon"'
        ).one()
        for cust_attr in all_avalon_attr['custom_attribute_configurations']:
            if 'avalon_' in cust_attr['key']:
                continue

            if not cust_attr['is_hierarchical']:
                continue

            if cust_attr['default']:
                self.log.warning((
                    'Custom attribute "{}" has set default value.'
                    ' This attribute can\'t be synchronized'
                ).format(cust_attr['label']))
                continue

            custom_attributes[cust_attr['key']] = cust_attr

        if not custom_attributes:
            msg = 'No hierarchical attributes to sync.'
            self.log.debug(msg)
            return {
                'success': True,
                'message': msg
            }

        entity = entities[0]
        if entity.entity_type.lower() == 'project':
            project_name = entity['full_name']
        else:
            project_name = entity['project']['full_name']

        self.db_con.install()
        self.db_con.Session['AVALON_PROJECT'] = project_name

        for entity in entities:
            for key in custom_attributes:
                # check if entity has that attribute
                if key not in entity['custom_attributes']:
                    self.log.debug(
                        'Hierachical attribute "{}" not found on "{}"'.format(
                            key, entity.get('name', entity)
                        )
                    )
                    continue

                value = self.get_hierarchical_value(key, entity)
                if value is None:
                    self.log.warning(
                        'Hierarchical attribute "{}" not set on "{}"'.format(
                            key, entity.get('name', entity)
                        )
                    )
                    continue

                self.update_hierarchical_attribute(entity, key, value)

        self.db_con.uninstall()

        return True

    def get_hierarchical_value(self, key, entity):
        value = entity['custom_attributes'][key]
        if (
            value is not None or
            entity.entity_type.lower() == 'project'
        ):
            return value

        return self.get_hierarchical_value(key, entity['parent'])

    def update_hierarchical_attribute(self, entity, key, value):
        if (
            entity['context_type'].lower() not in ('show', 'task') or
            entity.entity_type.lower() == 'task'
        ):
            return
        # collect entity's custom attributes
        custom_attributes = entity.get('custom_attributes')
        if not custom_attributes:
            return

        mongoid = custom_attributes.get(self.ca_mongoid)
        if not mongoid:
            self.log.debug('Entity "{}" is not synchronized to avalon.'.format(
                entity.get('name', entity)
            ))
            return

        try:
            mongoid = ObjectId(mongoid)
        except Exception:
            self.log.warning('Entity "{}" has stored invalid MongoID.'.format(
                entity.get('name', entity)
            ))
            return
        # Find entity in Mongo DB
        mongo_entity = self.db_con.find_one({'_id': mongoid})
        if not mongo_entity:
            self.log.warning(
                'Entity "{}" is not synchronized to avalon.'.format(
                    entity.get('name', entity)
                )
            )
            return

        # Change value if entity has set it's own
        entity_value = custom_attributes[key]
        if entity_value is not None:
            value = entity_value

        data = mongo_entity.get('data') or {}

        data[key] = value
        self.db_con.update_many(
            {'_id': mongoid},
            {'$set': {'data': data}}
        )

        for child in entity.get('children', []):
            self.update_hierarchical_attribute(child, key, value)


def register(session, **kw):
    '''Register plugin. Called when used as an plugin.'''

    if not isinstance(session, ftrack_api.session.Session):
        return

    SyncHierarchicalAttrs(session).register()


def main(arguments=None):
    '''Set up logging and register action.'''
    if arguments is None:
        arguments = []

    parser = argparse.ArgumentParser()
    # Allow setting of logging level from arguments.
    loggingLevels = {}
    for level in (
        logging.NOTSET, logging.DEBUG, logging.INFO, logging.WARNING,
        logging.ERROR, logging.CRITICAL
    ):
        loggingLevels[logging.getLevelName(level).lower()] = level

    parser.add_argument(
        '-v', '--verbosity',
        help='Set the logging output verbosity.',
        choices=loggingLevels.keys(),
        default='info'
    )
    namespace = parser.parse_args(arguments)

    # Set up basic logging
    logging.basicConfig(level=loggingLevels[namespace.verbosity])

    session = ftrack_api.Session()
    register(session)

    # Wait for events
    logging.info(
        'Registered actions and listening for events. Use Ctrl-C to abort.'
    )
    session.event_hub.wait()


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))