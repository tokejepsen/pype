import requests
import pyblish.api

from openpype.pipeline import PublishXmlValidationError
from openpype_modules.deadline.abstract_submit_deadline import requests_get


class ValidateDeadlineConnection(pyblish.api.InstancePlugin):
    """Validate Deadline Web Service is running"""

    label = "Validate Deadline Web Service"
    order = pyblish.api.ValidatorOrder
    hosts = ["maya", "nuke", "tvpaint"]
    families = ["renderlayer", "render"]

    # cache
    responses = {}

    def process(self, instance):
        # Deadline connection is validated even when rendering locally.
        if "render.local" in instance.data["families"]:
            return
        if "render.frames" in instance.data["families"]:
            return

        # get default deadline webservice url from deadline module
        deadline_url = instance.context.data["defaultDeadline"]
        # if custom one is set in instance, use that
        if instance.data.get("deadlineUrl"):
            deadline_url = instance.data.get("deadlineUrl")
            self.log.debug(
                "We have deadline URL on instance {}".format(deadline_url)
            )

        if not deadline_url:
            raise PublishXmlValidationError(
                plugin=self,
                key="unconfigured",
                message="Deadline Web Service URL is not configured."
            )

        if deadline_url not in self.responses:
            try:
                self.responses[deadline_url] = requests_get(deadline_url)
            except requests.exceptions.Timeout as e:
                raise PublishXmlValidationError(
                    plugin=self,
                    key="timeout",
                    message="Connection to Deadline Web Service at {url} timed out.".format(
                        url=deadline_url)
                )
            except requests.exceptions.ConnectionError as e:
                raise PublishXmlValidationError(
                    plugin=self,
                    message="Could not connect to Deadline Web Service at {url}.".format(
                        url=deadline_url)
                )
            except requests.exceptions.RequestException as e:
                raise PublishXmlValidationError(
                    plugin=self,
                    message="Failed to connect to Deadline Web Service at {url}.".format(
                        url=deadline_url)
                )

        response = self.responses[deadline_url]

        if not response.ok:
            raise PublishXmlValidationError(
                plugin=self,
                message="Deadline Web Service returned HTTP {status}.".format(
                    status=response.status_code)
            )

        if not response.text.startswith("Deadline Web Service "):
            raise PublishXmlValidationError(
                plugin=self,
                message="Unexpected response from Deadline Web Service."
            )
