# SPDX-License-Identifier: GPL-3.0-or-later
"""Friendly error handling for Auto Bake.

Every foreseeable failure raises :class:`AutoBakeError` with a human readable
``message`` and, whenever possible, a ``suggestion`` telling the artist how to
fix the problem.  The UI shows both.
"""


class AutoBakeError(Exception):
    """An error with a user facing message and an optional suggested fix."""

    def __init__(self, message, suggestion=""):
        super().__init__(message)
        self.message = message
        self.suggestion = suggestion

    def __str__(self):
        if self.suggestion:
            return "%s  (%s)" % (self.message, self.suggestion)
        return self.message


class BakeCancelled(Exception):
    """Raised internally when the user confirms a cancellation."""


# ---------------------------------------------------------------------------
# Common error factories - keeps wording consistent across the add-on.
# ---------------------------------------------------------------------------
def no_targets_error(scope):
    if scope == 'SELECTED':
        return AutoBakeError(
            "No bakeable objects are selected.",
            "Select at least one visible mesh object, or switch the bake "
            "scope to 'Entire Scene'.",
        )
    return AutoBakeError(
        "The scene contains no bakeable mesh objects.",
        "Add or unhide at least one mesh object with a material.",
    )


def output_folder_error(path, reason):
    return AutoBakeError(
        "Cannot write to the export folder: %s" % path,
        "%s  Pick a different folder in Output settings." % reason,
    )


def unsupported_node_warning(material_name):
    return (
        "Material '%s' has no Principled BSDF; neutral default values were "
        "baked for its channel passes." % material_name
    )


def bake_failed_error(pass_label, obj_name, detail):
    detail = (detail or "").strip().splitlines()
    detail = detail[-1] if detail else "Unknown Cycles error"
    return AutoBakeError(
        "Baking '%s' failed on object '%s': %s" % (pass_label, obj_name, detail),
        "Check that the object has valid geometry and UVs, then try again. "
        "Lowering the resolution or switching device to CPU can also help.",
    )
