import bpy
import os
import sys

"""
FloorplanToBlender3d
Copyright (C) 2021 Daniel Westberg
"""

"""
Imports a .blender file and exports it as custom object
"""
if __name__ == "__main__":
    argv = sys.argv

    input_path = argv[5]
    bpy.ops.wm.open_mainfile(filepath=input_path)

    format = argv[6]
    output_path = argv[
        7
    ]  # strict argc==5 -> len=6 will be used as argument see Reformat_blender_to_obj.py

    # Blender 3.6+/4.x renamed/moved several exporters; support both the
    # old and new operator names so this works across versions.
    if format == ".obj":
        if hasattr(bpy.ops.wm, "obj_export"):
            bpy.ops.wm.obj_export(filepath=output_path)
        else:
            bpy.ops.export_scene.obj(filepath=output_path)
    elif format == ".fbx":
        bpy.ops.export_scene.fbx(filepath=output_path)
    elif format == ".gltf":
        bpy.ops.export_scene.gltf(filepath=output_path, export_format='GLTF_SEPARATE')
    elif format == ".x3d":
        bpy.ops.export_scene.x3d(filepath=output_path)
    elif format == ".stl":
        if hasattr(bpy.ops.wm, "stl_export"):
            bpy.ops.wm.stl_export(filepath=output_path)
        else:
            bpy.ops.export_mesh.stl(filepath=output_path)
    elif format == ".blend":
        bpy.ops.wm.save_as_mainfile(filepath=output_path)
    else:
        # default
        if hasattr(bpy.ops.wm, "obj_export"):
            bpy.ops.wm.obj_export(filepath=output_path)
        else:
            bpy.ops.export_scene.obj(filepath=output_path)

    # Must exit with 0 to avoid error!
    exit(0)
