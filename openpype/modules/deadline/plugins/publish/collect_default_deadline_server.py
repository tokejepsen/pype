# -*- coding: utf-8 -*-
"""Collect default Deadline server."""
import pyblish.api

from openpype.lib import TextDef
from openpype.pipeline.publish import OpenPypePyblishPluginMixin


class CollectDefaultDeadlineServer(
        pyblish.api.ContextPlugin, OpenPypePyblishPluginMixin):
    """Collect default Deadline Webservice URL.

    DL webservice addresses must be configured first in System Settings for
    project settings enum to work.

    Default webservice could be overriden by
    `project_settings/deadline/deadline_servers`. Currently only single url
    is expected.

    This url could be overriden by some hosts directly on instances with
    `CollectDeadlineServerFromInstance`.
    """

    # Run before collect_deadline_server_instance.
    order = pyblish.api.CollectorOrder + 0.0025
    label = "Default Deadline Webservice"

    pass_mongo_url = False

    @classmethod
    def get_attribute_defs(cls):
        return [
            TextDef(
                "deadline_server_name",
                label="Deadline Server Name",
                default="default"
            )
        ]

    def process(self, context):
        try:
            deadline_module = context.data.get("openPypeModules")["deadline"]
        except AttributeError:
            self.log.error("Cannot get OpenPype Deadline module.")
            raise AssertionError("OpenPype Deadline module not found.")

        # get default deadline webservice url from deadline module
        self.log.debug(deadline_module.deadline_urls)
        context.data["defaultDeadline"] = deadline_module.deadline_urls["default"]  # noqa: E501

        context.data["deadlinePassMongoUrl"] = self.pass_mongo_url

        # Determine deadline_server_name: attr value > project settings > "default"
        attr_values = self.get_attr_values_from_data(context.data)
        deadline_server_name = attr_values.get("deadline_server_name") or "default"

        context.data["deadline_server_name"] = deadline_server_name

        deadline_webservice = deadline_module.deadline_urls.get(
            deadline_server_name)
        if deadline_webservice:
            context.data["defaultDeadline"] = deadline_webservice
            self.log.debug(
                "Using Deadline server '{}': {}".format(
                    deadline_server_name, deadline_webservice))

        context.data["defaultDeadline"] = \
            context.data["defaultDeadline"].strip().rstrip("/")
