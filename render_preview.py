import bpy
import sys

argv = sys.argv
blend_path = argv[argv.index("--") + 1] if "--" in argv else argv[-2]
out_png = argv[argv.index("--") + 2] if "--" in argv else argv[-1]

bpy.ops.wm.open_mainfile(filepath=blend_path)

scene = bpy.context.scene

# Add a top-down orthographic camera looking down at the model
bpy.ops.object.camera_add(location=(0, 0, 30), rotation=(0, 0, 0))
cam = bpy.context.object
cam.data.type = 'ORTHO'
cam.data.ortho_scale = 30
scene.camera = cam

# Simple sun light
bpy.ops.object.light_add(type='SUN', location=(0, 0, 20))

scene.render.engine = 'BLENDER_WORKBENCH'
scene.render.resolution_x = 1000
scene.render.resolution_y = 1000
scene.render.filepath = out_png
bpy.ops.render.render(write_still=True)
