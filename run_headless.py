#!/usr/bin/env python3
"""
run_headless.py

Non-interactive wrapper around FloorplanToBlender3d's main.py.
The upstream main.py asks interactive questions (blender path, config vs
stacking file, confirmation, etc.) which doesn't work well when driven from
a script/agent. This wrapper does the same job with plain arguments.

Usage:
    python3 run_headless.py --image path/to/floorplan.png [--out-format .obj]

Output:
    A Blender project (and, optionally, an exported .obj/.gltf/etc.) is
    written under ./Target/
"""
import argparse
import json
import os
import configparser
from subprocess import check_output, CalledProcessError

from FloorplanToBlenderLib import IO, config, const, execution, floorplan

BLENDER_BIN = "/usr/bin/blender"


def ensure_configs(image_path, out_format):
    """(Re)write the Configs/*.ini files so they point at our image and
    our actual blender binary, without any interactive prompts."""
    os.makedirs(os.path.dirname(const.SYSTEM_CONFIG_FILE_NAME), exist_ok=True)

    # --- system.ini ---
    sysconf = configparser.ConfigParser()
    sysconf["SYSTEM"] = {
        const.STR_OVERWRITE_DATA: const.DEFAULT_OVERWRITE_DATA,
        const.STR_BLENDER_INSTALL_PATH: BLENDER_BIN,
        const.STR_OUT_FORMAT: json.dumps(out_format),
    }
    with open(const.SYSTEM_CONFIG_FILE_NAME, "w") as f:
        sysconf.write(f)

    # --- default.ini (image + transform + feature toggles) ---
    imgconf = configparser.ConfigParser()
    imgconf["IMAGE"] = {
        const.STR_IMAGE_PATH: json.dumps(image_path),
        "COLOR": json.dumps([0, 0, 0]),
    }
    imgconf["TRANSFORM"] = {
        "position": json.dumps([0, 0, 0]),
        "rotation": json.dumps([0, 0, 90]),
        "scale": json.dumps([1, 1, 1]),
        "margin": json.dumps([0, 0, 0]),
    }
    imgconf[const.FEATURES] = {
        const.STR_FLOORS: json.dumps(const.DEFAULT_FEATURES),
        const.STR_ROOMS: json.dumps(const.DEFAULT_FEATURES),
        const.STR_WALLS: json.dumps(const.DEFAULT_FEATURES),
        const.STR_DOORS: json.dumps(const.DEFAULT_FEATURES),
        const.STR_WINDOWS: json.dumps(const.DEFAULT_FEATURES),
    }
    imgconf[const.SETTINGS] = {
        const.STR_REMOVE_NOISE: json.dumps(const.DEFAULT_REMOVE_NOISE),
        const.STR_RESCALE_IMAGE: json.dumps(const.DEFAULT_RESCALE_IMAGE),
    }
    imgconf[const.WALL_CALIBRATION] = {
        const.STR_CALIBRATION_IMAGE_PATH: json.dumps(
            const.DEFAULT_CALIBRATION_IMAGE_PATH
        ),
        const.STR_WALL_SIZE_CALIBRATION: json.dumps(const.DEFAULT_WALL_SIZE_CALIBRATION),
    }
    with open(const.IMAGE_DEFAULT_CONFIG_FILE_NAME, "w") as f:
        imgconf.write(f)


def create_blender_project(data_paths, target_folder, program_path, out_format):
    if not os.path.exists("." + target_folder):
        os.makedirs("." + target_folder)

    target_base = target_folder + const.TARGET_NAME
    target_path = target_base + const.BASE_FORMAT
    target_path = (
        IO.get_next_target_base_name(target_base, target_path) + const.BASE_FORMAT
    )

    print(f"Running Blender to build project at .{target_path} ...")
    check_output(
        [
            BLENDER_BIN,
            "-noaudio",
            "--background",
            "--python",
            const.BLENDER_SCRIPT_PATH,
            program_path,
            target_path,
        ]
        + data_paths
    )

    if out_format != ".blend":
        out_path = "." + target_base + out_format
        print(f"Exporting to {out_path} ...")
        check_output(
            [
                BLENDER_BIN,
                "-noaudio",
                "--background",
                "--python",
                "./Blender/blender_export_any.py",
                "." + target_path,
                out_format,
                out_path,
            ]
        )
        print("Object created at: " + program_path + out_path[1:])
        return program_path + out_path[1:]

    print("Blender project created at: " + program_path + target_path)
    return program_path + target_path


def main():
    parser = argparse.ArgumentParser(description="Headless FloorplanToBlender3d runner")
    parser.add_argument(
        "--image",
        default=const.DEFAULT_IMAGE_PATH,
        help="Path to the floorplan image (png/jpg). Defaults to the bundled example.",
    )
    parser.add_argument(
        "--out-format",
        default=".obj",
        choices=list(const.SUPPORTED_BLENDER_FORMATS) + [".blend"],
        help="Extra export format alongside the .blend project (default: .obj)",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Clear cached data in Data/ before running",
    )
    args = parser.parse_args()

    image_path = os.path.abspath(args.image)
    if not os.path.isfile(image_path):
        raise SystemExit(f"Image not found: {image_path}")

    program_path = os.path.dirname(os.path.realpath(__file__))
    os.chdir(program_path)  # the lib assumes CWD == repo root

    ensure_configs(image_path, args.out_format)

    if args.clean:
        IO.clean_data_folder(const.BASE_PATH)

    fp = floorplan.new_floorplan(const.IMAGE_DEFAULT_CONFIG_FILE_NAME)
    print(f"Generating floorplan data files from: {image_path}")
    data_paths = [execution.simple_single(fp)]

    result = create_blender_project(
        data_paths, const.TARGET_PATH, program_path, args.out_format
    )
    print("\nDone. Result: " + result)


if __name__ == "__main__":
    try:
        main()
    except CalledProcessError as e:
        print("Blender subprocess failed:")
        print(e.output.decode("utf-8", errors="replace") if e.output else e)
        raise
