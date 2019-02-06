import pyblish.api
import pype.api


class ValidateAutoSyncOff(pyblish.api.ContextPlugin):
    """Ensure that autosync value in ftrack project is set to False.

    In case was set to True and event server with the sync to avalon event
    is running will cause integration to avalon will be override.

    """

    order = pype.api.ValidatorOrder
    hosts = ["premiere"]
    families = []
    label = 'Ftrack project\'s auto sync off'
    actions = [pype.api.RepairAction]

    def process(self, instance):
        invalid = self.get_invalid(instance)

        assert (invalid is not None), (
                "Ftrack Project has 'Auto sync' set to On."
                " That may cause issues during integration."
        )

    @staticmethod
    def get_invalid(instance):
        session = instance.context.data["ftrackSession"]
        # project_name =
        query = 'Project where full_name is "{}"'.format(project_name)
        project = session.query(query).one()

        invalid = None

        if (
            project.get('custom_attributes', {}).get(
                'avalon_auto_sync', False) is True
        ):
            invalid = project

        return invalid

    @classmethod
    def repair(cls, instance):
        session = instance.context.data["ftrackSession"]
        invalid = cls.get_invalid(instance)
        invalid['custom_attributes']['avalon_auto_sync'] = False
        session.commit()
