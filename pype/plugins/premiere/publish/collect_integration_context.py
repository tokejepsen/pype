import pyblish.api
from avalon import api


class CollectContextForIntegration(pyblish.api.ContextPlugin):
    """Collecting data from temp json sent from premiera context"""

    label = "Collect Context For Integration"
    order = pyblish.api.CollectorOrder + 0.1

    def update_dict(self, ex_dict, new_dict):
        for key in ex_dict:
            if key in new_dict and isinstance(ex_dict[key], dict):
                new_dict[key] = self.update_dict(ex_dict[key], new_dict[key])
            else:
                new_dict[key] = ex_dict[key]
        return new_dict

    def process(self, context):
        data_path = context.data['rqst_json_data_path']
        self.log.info("Context is: {}".format(data_path))
        # TODO: 100% sure way of get project! Will be Name or Code?
        project_name = api.Session["AVALON_PROJECT"]
        temp_context = {}
        # TODO: how to get instances? --> Context??? Load JSON???
        for instance in instances:
            in_info = {}
            name = instance['name']
            # suppose that all instances are Shots
            in_info['entity_type'] = 'Shot'
            # TODO: get custom attributes
            in_info['custom_attributes'] = {}
            # TODO: get tasks
            in_info['tasks'] = {}
            parents = instance.get('hierarchy', [])
            actual = {name: in_info}
            for parent in reversed(parents):
                next_dict = {}
                parent_name = parent["entityName"]
                next_dict[parent_name] = {}
                next_dict[parent_name]["entityType"] = parent["entityType"]
                next_dict[parent_name]["childs"] = actual
                actual = next_dict

            temp_context = self.update_dict(temp_context, actual)

        final_context = {}
        final_context[project_name] = {}
        final_context[project_name]['childs'] = temp_context
