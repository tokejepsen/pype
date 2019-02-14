import pyblish.api


class IntegrateHierarchyToFtrack(pyblish.api.InstancePlugin):
    """
    Create entities in ftrack based on collected data from premiere
    Example of entry data:
    {
        "ProjectXS": {
            "entity_type": "Project",
            "custom_attributes": {
                "fps": 24,...
            },
            "tasks": [
                "Compositing",
                "Lighting",... *task must exist as task type in project schema*
            ],
            "childs": {
                "sq01": {
                    "entity_type": "Sequence",
                    ...
                }
            }
        }
    }
    """

    order = pyblish.api.IntegratorOrder
    label = 'Integrate Hierarchy To Ftrack'
    families = ["ftrack"]
    optional = False

    def process(self, instance):
        if "hierarchyContext" not in instance.data:
            return

        self.ft_project = None
        self.session = instance.context.data["ftrackSession"]

        input_data = instance.data["hierarchyContext"]
        self.import_to_ftrack(input_data)

    def import_to_ftrack(self, input_data, parent=None):
        for entity_name in input_data:
            entity_data = input_data[entity_name]
            entity_type = entity_data['entity_type']

            if entity_type.lower() == 'project':
                query = 'Project where full_name is "{}"'.format(entity_name)
                entity = self.session.query(query).one()
                self.ft_project = entity
                self.task_types = self.get_all_task_types(entity)

            elif self.ft_project is None or parent is None:
                raise AssertionError(
                    "Collected items are not in right order!"
                )

            # try to find if entity already exists
            else:
                query = '{} where name is "{}" and parent_id is "{}"'.format(
                    entity_type, entity_name, parent['id']
                )
                try:
                    entity = self.session.query(query).one()
                except Exception:
                    entity = None

            # Create entity if not exists
            if entity is None:
                entity = self.create_entity(
                    name=entity_name,
                    type=entity_type,
                    parent=parent
                )
            # CUSTOM ATTRIBUTES
            custom_attributes = entity_data.get('custom_attributes', [])
            for key in custom_attributes:
                assert (key in entity['custom_attributes']), (
                    'Missing custom attribute')

                entity['custom_attributes'][key] = custom_attributes[key]
                self.session.commit()

            # TASKS
            tasks = entity_data.get('tasks', [])
            existing_tasks = []
            tasks_to_create = []
            for child in entity['children']:
                if child.entity_type.lower() == 'task':
                    existing_tasks.append(child['type']['name'])

            for task in tasks:
                if task in existing_tasks:
                    print("Task {} already exists".format(task))
                    continue
                tasks_to_create.append(task)

            for task in tasks_to_create:
                self.create_task(
                    name=task,
                    task_type=task,
                    parent=entity
                )
                self.session.commit()

            if 'childs' in entity_data:
                self.import_to_ftrack(entity_data['childs'], entity)

    def get_all_task_types(self, project):
        tasks = {}
        proj_template = project['project_schema']
        temp_task_types = proj_template['_task_type_schema']['types']

        for type in temp_task_types:
            if type['name'] not in tasks:
                tasks[type['name']] = type

        return tasks

    def create_task(self, name, task_type, parent):
        task = self.session.create('Task', {
            'name': name,
            'parent': parent
        })
        # TODO not secured!!! - check if task_type exists
        task['type'] = self.task_types[task_type]

        self.session.commit()

        return task

    def create_entity(self, name, type, parent):
        entity = self.session.create(type, {
            'name': name,
            'parent': parent
        })
        self.session.commit()

        return entity
