import pyblish.api

try:
    import ftrack_api_old as ftrack_api
except Exception:
    import ftrack_api


class IntegrateFtrackTask(pyblish.api.InstancePlugin):
    """ Integrate an ftrack session and the current task id. """

    order = pyblish.api.IntegratorOrder + 0.1
    label = "Integrate Ftrack Tasks"
    families = ['clip']

    def process(self, instance):

        # Collect session
        if instance.context.data.get("ftrackSession", None) is None:
            session = ftrack_api.Session()
            instance.context.data["ftrackSession"] = session
        else:
            session = instance.context.data["ftrackSession"]

        project = instance.context.data['avalonSession']['AVALON_PROJECT']
        asset = instance.data['asset']

        # TODO: how to process task iterable
        task = instance.data['tasks'][0]

        query = (
            'Task where project.full_name is "{0}" and '
            'name is "{1}" and '
            'parent.name is "{2}"'
        )
        result = session.query(query.format(project, task, asset)).one()
        self.log.info(result)

        instance.data["ftrackTask"] = result
        instance.data["ftrackTaskId"] = result['id']
