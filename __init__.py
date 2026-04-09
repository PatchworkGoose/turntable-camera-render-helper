bl_info = {
    "name": "Turntable Camera Render Helper",
    "author": "PatchworkGoose",
    "version": (0, 0, 1),
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

def get_camera_items(self, context):
    return [(obj.name, obj.name, "") for obj in bpy.data.objects if obj.type == "CAMERA"]


def get_empty_items(self, context):
    return [(obj.name, obj.name, "") for obj in bpy.data.objects if obj.type == "EMPTY"]


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
        name="CameraPivot",
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
    bl_label = "Render Turntable"
    bl_description = "Do the thing"

    def execute(self, context):
        props = context.scene.turntable_properties
        scene = context.scene

        cam = bpy.data.objects.get(props.camera)
        pivot = ensure_pivot(props.pivot if props.pivot else "CameraPivot")

        if cam is None:
            self.report({"ERROR"}, "Camera or Pivot not found")
            return {"CANCELLED"}

        # Parent Camera
        if cam.parent != pivot:
            # Keep world transform
            matrix_world = cam.matrix_world.copy()
            cam.parent = pivot
            cam.matrix_parent_inverse = pivot.matrix_world.inverted()
            cam.matrix_world = matrix_world

        scene.camera = cam

        # Output
        if props.output_directory:
            output_path = bpy.path.abspath(props.output_directory)
        else:
            self.report({"ERROR"}, "No Output Folder")
            return {"CANCELLED"}

        frame_count = scene.frame_end - scene.frame_start + 1
        original_rotation = pivot.rotation_euler.copy()

        for i in range(props.steps):
            angle = (360 / props.steps) * i
            pivot.rotation_euler[2] = math.radians(angle)

            for frame in range(scene.frame_start, scene.frame_end + 1):
                scene.frame_set(frame)

                frame_number = (i * frame_count) + (frame - scene.frame_start + 1)

                filename = f"{props.output_name}_{props.output_suffix}_{frame_number:04d}.png"
                scene.render.filepath = os.path.join(output_path, filename)

                bpy.ops.render.render(write_still=True)

        # Reset
        pivot.rotation_euler = original_rotation
        scene.render.filepath = props.output_directory

        self.report({"INFO"}, f"Rendering complete: {output_path}")
        return {"FINISHED"}


class VIEW3D_PT_ui_panel(Panel):
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"

    bl_category = "Tool"
    bl_label = "Turntable Helper"

    def draw(self, context):

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

        layout.operator("render.turntable", icon="RENDER_STILL")


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