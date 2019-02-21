
import pype.api as pype

import pyblish.api


class CollectTemplates(pyblish.api.ContextPlugin):
    """Inject the current working file into context"""

    order = pyblish.api.CollectorOrder
    label = "Collect Templates"

    def process(self, context):
        pype.reset_data_from_templates()
        pype.load_data_from_templates()
        context.data['anatomy'] = pype.Anatomy
        self.log.info("Anatomy templates collected...")
