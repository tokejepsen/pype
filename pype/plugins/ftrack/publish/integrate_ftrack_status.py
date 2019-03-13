import pyblish.api


class IntegrateFtrackStatus(pyblish.api.ContextPlugin):
    """ Sets the task to "In Progress". """

    order = pyblish.api.IntegratorOrder + 0.499
    label = "Ftrack Status"
    optional = True
    families = ['ftrack']

    def process(self, context):

        task = context.data["ftrackTask"]

        if context.data.get('ftrackSuccess'):
            status_name = 'Artist Review'
        else:
            status_name = "Render Failed"

        session = context.data["ftrackSession"]
        status = session.query(
            "Status where name is \"{}\"".format(status_name)).one()
        self.log.info(status)
        context.data["ftrackTask"]["status"] = status
        session.commit()
