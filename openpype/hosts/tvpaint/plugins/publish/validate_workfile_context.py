import pyblish.api
from openpype.pipeline import PublishValidationError
from openpype.hosts.tvpaint.api.pipeline import save_current_workfile_context


class RepairWorkfileContext(pyblish.api.Action):
    """Overwrite workfile context with environment context."""

    label = "Use environment context"
    icon = "wrench"
    on = "failed"

    def process(self, context, _plugin):
        """Update workfile metadata with correct environment context."""
        env_context = context.data.get("env_context", {})
        workfile_context = context.data.get("workfile_context", {})

        if not env_context or not workfile_context:
            self.log.warning(
                "Cannot repair context: missing env_context or workfile_context"
            )
            return

        # Merge environment context values into workfile context
        # This overwrites the mismatched asset_name and task_name
        updated_context = workfile_context.copy()
        updated_context["asset_name"] = env_context["asset_name"]
        updated_context["task_name"] = env_context["task_name"]

        # Save the corrected context to workfile metadata
        self.log.info(
            "Updating workfile context to asset: '{}', task: '{}'".format(
                env_context["asset_name"],
                env_context["task_name"]
            )
        )
        save_current_workfile_context(updated_context)
        self.log.info("Workfile context updated successfully")


class ValidateWorkfileContext(pyblish.api.ContextPlugin):
    """Validate that workfile context matches environment context.

    When a workfile is duplicated from another task, the metadata will
    still reflect the original task. This validator ensures the asset_name
    and task_name in the workfile match the current environment.
    """

    label = "Validate Workfile Context"
    order = pyblish.api.ValidatorOrder
    hosts = ["tvpaint"]

    actions = [RepairWorkfileContext]

    def process(self, context):
        workfile_context = context.data.get("workfile_context")
        env_context = context.data.get("env_context")

        self.log.info(workfile_context)
        self.log.info(env_context)

        # If workfile context is missing, let ValidateWorkfileMetadata handle it
        if not workfile_context:
            self.log.info(
                "Workfile context is empty, skipping context validation"
            )
            return

        # If env context is missing, something is wrong with collector
        if not env_context:
            self.log.warning(
                "Environment context is missing from pyblish context"
            )
            return

        mismatches = {}

        # Compare asset_name
        workfile_asset = workfile_context.get("asset_name")
        env_asset = env_context.get("asset_name")
        if workfile_asset != env_asset:
            mismatches["asset_name"] = {
                "workfile": workfile_asset,
                "environment": env_asset
            }

        # Compare task_name
        workfile_task = workfile_context.get("task_name")
        env_task = env_context.get("task_name")
        if workfile_task != env_task:
            mismatches["task_name"] = {
                "workfile": workfile_task,
                "environment": env_task
            }

        if mismatches:
            # Build detailed error message
            mismatch_details = []
            for field, values in mismatches.items():
                mismatch_details.append(
                    "  {}: workfile='{}' vs environment='{}'".format(
                        field, values["workfile"], values["environment"]
                    )
                )

            raise PublishValidationError(
                "Workfile context does not match environment context:\n{}".format(
                    "\n".join(mismatch_details)
                ),
                title="Workfile Context Mismatch"
            )

        self.log.info("Workfile context matches environment context")
