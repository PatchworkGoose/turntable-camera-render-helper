bl_info = {
    "name": "Turntable Camera Render Helper",
    "author": "PatchworkGoose",
    "version": (0, 0, 2),
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


def ensure_pivot(name="CameraPivot"):
    pivot = bpy.data.objects.get(name)

    if pivot is None:
        pivot = bpy.data.objects.new(name, None)
        bpy.context.collection.objects.link(pivot)
        pivot.empty_display_type = "ARROWS"
        pivot.location = (0, 0, 0)

    return pivot


class TurntableProperties(PropertyGroup):
    camera: EnumProperty(
        name="Camera",
        items=get_camera_items,
    )

    pivot: EnumProperty(
        name="Pivot",
        items=get_empty_items,
    )

    output_name: StringProperty(
        name="Output Name",
    )

    output_suffix: StringProperty(
        name="Suffix",
        default="d",
    )

    output_directory: StringProperty(
        name="Output Folder",
        subtype="DIR_PATH",
    )

    steps: IntProperty(
        name="Steps",
        default=8,
        min=1,
    )


class OBJECT_OT_create_camera_pivot(Operator):
    bl_idname = "object.create_camera_pivot"
    bl_label = "Create Camera Pivot"

    bl_description = "Creates an empty that will be used as a camera pivot"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        props = context.scene.turntable_properties
        pivot = ensure_pivot(props.pivot if props.pivot else "CameraPivot")
        props.pivot = pivot.name
        self.report({"INFO"}, "CameraPivot created or already exists")
        return {"FINISHED"}


class OBJECT_OT_snap_pivot(Operator):
    bl_idname = "object.snap_pivot_to_selected"
    bl_label = "Snap Pivot to Selected"

    bl_description = "Snap the camera pivot to selected object"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        props = context.scene.turntable_properties
        pivot = ensure_pivot(props.pivot if props.pivot else "CameraPivot")

        obj = context.active_object
        if obj is None:
            self.report({"ERROR"}, "No active object selected")
            return {"CANCELLED"}

        if obj == pivot:
            self.report({"WARNING"}, "Pivot can't snap to itself")
            return {"CANCELLED"}

        if pivot in context.selected_objects:
            self.report({"WARNING"}, "De-select the pivot before snapping")
            return {"CANCELLED"}

        pivot.location = obj.location
        self.report({"INFO"}, f"Pivot snapped to {obj.name}")
        return {"FINISHED"}


class RENDER_OT_turntable(Operator):
    bl_idname = "render.turntable"
    bl_label = "Turntable Render"

    bl_description = "Render with current settings."

    _timer = None

    def modal(self, context, event):
        if event.type == "TIMER":

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

            filename = f"{self.output_name}_{self.output_suffix}_{frame_number:04d}.png"
            context.scene.render.filepath = os.path.join(self.output_path, filename)

            # Render a single frame
            bpy.ops.render.render(write_still=True)

            # Advance the frame
            self.frame_index += 1

            if self.frame_index >= self.frame_count:
                self.frame_index = 0
                self.step += 1

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
        self.pivot = ensure_pivot(props.pivot if props.pivot else "CameraPivot")

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

        self.report({"INFO"}, "Render complete")


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


classes = (
    OBJECT_OT_create_camera_pivot,
    OBJECT_OT_snap_pivot,
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