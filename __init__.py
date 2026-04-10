# SPDX-License-Identifier: GPL-3.0-or-later

bl_info = {
    "name": "Turntable Camera Render Helper",
    "author": "PatchworkGoose",
    "version": (0, 0, 3),
    "blender": (5, 0, 0),
}

import bpy
from bpy.types import (
    PropertyGroup,
    Panel,
    Operator,
)
from bpy.props import (
    IntProperty,
    EnumProperty,
    StringProperty,
)
import math
import os
import mathutils

IS_RENDER_RUNNING = False
ACTIVE_RENDER_OPERATOR = None

def get_camera_items(self, context):
    items = []
    for obj in bpy.data.objects:
        if obj.type == "CAMERA":
            items.append((obj.name, obj.name, ""))
    if not items:
        items.append(("None", "---", "No Camera Available"))
    return items


def get_empty_items(self, context):
    items = []
    for obj in bpy.data.objects:
        if obj.type == "EMPTY":
            items.append((obj.name, obj.name, ""))
    if not items:
        items.append(("CameraPivot", "---", "No Current Camera Pivot"))
    return items


def ensure_pivot(name="CameraPivot", new_pivot: bool = False):
    pivot = bpy.data.objects.get(name)

    if pivot is None or new_pivot:
        props = bpy.context.scene.turntable_properties
        pivot = bpy.data.objects.new(name, None)
        bpy.context.collection.objects.link(pivot)
        pivot.empty_display_type = props.pivot_display_type
        pivot.location = (0, 0, 0)

    return pivot


class TurntableProperties(PropertyGroup):
    camera: EnumProperty(
        name="Camera",
        items=get_camera_items,
        description="The selected camera will be parented to an empty and rotated around it."
    )

    pivot: EnumProperty(
        name="Pivot",
        items=get_empty_items,
        description="The selected pivot the camera will be parented to."
    )

    pivot_display_type: EnumProperty(
        name="Pivot Display Type",
        items=[
            ("PLAIN_AXES", "Plain Axes", ""),
            ("ARROWS", "Arrows", ""),
            ("SINGLE_ARROW", "Single Arrow", ""),
            ("CIRCLE", "Circle", ""),
            ("CUBE", "Cube", ""),
            ("SPHERE", "Sphere", ""),
            ("CONE", "Cone", ""),
            ("IMAGE", "Image", "")
        ],
        default=1,
        description="How the generated pivot empty will display."
    )

    output_name: StringProperty(
        name="Output Name",
        default="name",
        description="Optional string prefixed to output: {output_name}_{output_suffix}_{frame_number}",
    )

    output_suffix: StringProperty(
        name="Suffix",
        default="d",
        description="Optional string to specify diffuse, normal, etc: {output_name}_{output_suffix}_{frame_number}"
    )

    output_directory: StringProperty(
        name="Output Folder",
        default="/tmp\\",
        subtype="DIR_PATH",
        description="Where the output will be saved."
    )

    steps: IntProperty(
        name="Steps",
        default=8,
        min=1,
        description="How many directions to render."
    )


class OBJECT_OT_create_camera_pivot(Operator):
    bl_idname = "object.create_camera_pivot"
    bl_label = "Create Camera Pivot"

    bl_description = "Adds an empty that will be used as a camera pivot, if none is present it will be automatically added in the center when Turntable Render is pressed."
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        props = context.scene.turntable_properties
        pivot = ensure_pivot(props.pivot if props.pivot else "CameraPivot", new_pivot=True)
        props.pivot = pivot.name
        self.report({"INFO"}, "CameraPivot created or already exists")
        return {"FINISHED"}


class OBJECT_OT_snap_pivot(Operator):
    bl_idname = "object.snap_pivot_to_selected"
    bl_label = "Snap Pivot to Selected"

    bl_description = "Snaps the camera pivot to the selected object. If multiple objects are selected it will snap to the mean average location."
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        props = context.scene.turntable_properties
        pivot = ensure_pivot(props.pivot if props.pivot else "CameraPivot", False)

        selected_objs = context.selected_objects
        active_obj = context.active_object

        if active_obj is None:
            self.report({"ERROR"}, "No active object selected")
            return {"CANCELLED"}

        if active_obj == pivot:
            self.report({"WARNING"}, "Pivot can't snap to itself")
            return {"CANCELLED"}

        if pivot in selected_objs:
            self.report({"WARNING"}, "De-select the pivot before snapping")
            return {"CANCELLED"}

        if len(selected_objs) > 1:
            total_location = sum((obj.matrix_world.to_translation() for obj in selected_objs), mathutils.Vector())
            avg_location = total_location / len(selected_objs)
            pivot.location = avg_location
            self.report({"INFO"}, f"Pivot snapped to {avg_location}")
        else:
            pivot.location = active_obj.location
            self.report({"INFO"}, f"Pivot snapped to {active_obj.name}")
        return {"FINISHED"}


class RENDER_OT_cancel(Operator):
    bl_idname = "render.cancel_render"
    bl_label = "Cancel Render"

    bl_description = "Cancel the remaining renders."
    def execute(self, context):
        global ACTIVE_RENDER_OPERATOR
        if ACTIVE_RENDER_OPERATOR is not None:
            ACTIVE_RENDER_OPERATOR.cancel_requested = True
            self.report({"WARNING"}, "Cancel requested")
        else:
            self.report({"INFO"}, "No active render")

        return {"FINISHED"}


class RENDER_OT_turntable(Operator):
    bl_idname = "render.turntable"
    bl_label = "Turntable Render"

    bl_description = "Render with current settings."

    _timer = None

    def modal(self, context, event):
        if event.type == "TIMER":

            if self.cancel_requested:
                self.finish(context, cancelled=True)
                return {"CANCELLED"}

            if self.step >= self.steps:
                self.finish(context)
                return {"FINISHED"}

            # Set pivot rotation
            angle = (360 / self.steps) * self.step
            self.pivot.rotation_euler[2] = math.radians(angle)

            # Set frame
            frame = self.frame_start + self.frame_index
            context.scene.frame_set(frame)

            frame_number = (self.step * self.frame_count) + (self.frame_index + 1)

            filename = f"{self.output_name}_{self.output_suffix}_{frame_number:04d}"
            context.scene.render.filepath = os.path.join(self.output_path, filename)

            if self.cancel_requested:
                self.finish(context, cancelled=True)
                return {"CANCELLED"}

            # Render a single frame
            bpy.ops.render.render(write_still=True)

            # Advance the frame
            self.frame_index += 1

            if self.frame_index >= self.frame_count:
                self.frame_index = 0
                self.step += 1

            if self.cancel_requested:
                self.finish(context, cancelled=True)
                return {"CANCELLED"}

        return {"PASS_THROUGH"}

    def execute(self, context):
        global IS_RENDER_RUNNING, ACTIVE_RENDER_OPERATOR

        if IS_RENDER_RUNNING:
            self.report({"WARNING"}, "Render already running")
            return {"CANCELLED"}
        if ACTIVE_RENDER_OPERATOR is not None and not ACTIVE_RENDER_OPERATOR == self:
            self.report({"ERROR"}, "Another render instance detected")
            return {"CANCELLED"}

        IS_RENDER_RUNNING = True
        ACTIVE_RENDER_OPERATOR = self

        props = context.scene.turntable_properties
        scene = context.scene

        self.cam = bpy.data.objects.get(props.camera)
        self.pivot = ensure_pivot(props.pivot if props.pivot else "CameraPivot", False)

        if not self.cam:
            self.report({"ERROR"}, "Camera not found")
            return {"CANCELLED"}

        # Parent camera
        if self.cam.parent != self.pivot:
            matrix_world = self.cam.matrix_world.copy()
            self.cam.parent = self.pivot
            self.cam.matrix_parent_inverse = self.pivot.matrix_world.inverted()
            self.cam.matrix_world = matrix_world

        scene.camera = self.cam

        # Output
        if props.output_directory:
            self.output_path = bpy.path.abspath(props.output_directory)
        else:
            self.report({"ERROR"}, "No Output Folder")
            return {"CANCELLED"}

        # Save properties
        self.steps = props.steps
        self.output_name = props.output_name
        self.output_suffix = props.output_suffix

        self.frame_start = scene.frame_start
        self.frame_end = scene.frame_end
        self.frame_count = self.frame_end - self.frame_start + 1

        self.step = 0
        self.frame_index = 0

        self.original_rotation = self.pivot.rotation_euler.copy()

        self.cancel_requested = False

        # Start timer
        wm = context.window_manager
        self._timer = wm.event_timer_add(0.1, window=context.window)
        wm.modal_handler_add(self)

        self.report({"INFO"}, "Rendering started")
        return {"RUNNING_MODAL"}

    def finish(self, context, cancelled=False):
        global ACTIVE_RENDER_OPERATOR, IS_RENDER_RUNNING

        context.window_manager.event_timer_remove(self._timer)
        self.pivot.rotation_euler = self.original_rotation

        ACTIVE_RENDER_OPERATOR = None
        IS_RENDER_RUNNING = False

        if cancelled:
            self.report({"WARNING"}, "Render cancelled")
        else:
            self.report({"INFO"}, "Render complete")

    def cancel(self, context):
        self.finish(context, cancelled=True)


class VIEW3D_PT_ui_panel(Panel):
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"

    bl_category = "Tool"
    bl_label = "Turntable Helper"

    def draw(self, context):
        global IS_RENDER_RUNNING
        layout = self.layout
        props = context.scene.turntable_properties

        layout.prop(props, "camera")
        layout.prop(props, "pivot")

        layout.prop(props, "pivot_display_type")
        layout.operator("object.create_camera_pivot", icon="EMPTY_AXIS")
        layout.operator("object.snap_pivot_to_selected", icon="PIVOT_CURSOR")

        layout.separator()

        layout.prop(props, "output_name")
        layout.prop(props, "output_suffix")
        layout.prop(props, "output_directory")
        layout.prop(props, "steps")

        row = layout.row()
        row.enabled = not IS_RENDER_RUNNING
        if not bpy.data.objects.get(props.camera): row.enabled = False
        row.operator("render.turntable", icon="RENDER_STILL")

        layout.operator("render.cancel_render", icon="CANCEL")


classes = (
    OBJECT_OT_create_camera_pivot,
    OBJECT_OT_snap_pivot,
    RENDER_OT_cancel,
    RENDER_OT_turntable,
    TurntableProperties,
    VIEW3D_PT_ui_panel
)


def register():
    from bpy.utils import register_class
    for cls in classes:
        register_class(cls)
    bpy.types.Scene.turntable_properties = bpy.props.PointerProperty(type=TurntableProperties)


def unregister():
    from bpy.utils import unregister_class
    for cls in reversed(classes):
        unregister_class(cls)
    del bpy.types.Scene.turntable_properties


if __name__ == "__main__":
    register()