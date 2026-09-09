"""
Script that holds additional platformio post-build configuration information
"""
import os

Import("env")

# Post build action, more information: https://docs.platformio.org/en/latest/scripting/actions.html
def post_action(source, target, env):
    artifact_build_file_path = target[0].get_path()
    artifact_build_file_path_parts = artifact_build_file_path.split(os.sep)
    build_file_path_part_idx = max(idx for idx, part in enumerate(artifact_build_file_path_parts) if part == "build")
    artifact_build_file_path_parts[build_file_path_part_idx] = "bin"
    artifact_copy_file_path = os.path.join(*artifact_build_file_path_parts)
    artifact_copy_dir_path = os.path.dirname(artifact_copy_file_path)

    if not os.path.isdir(artifact_copy_dir_path):
        os.makedirs(artifact_copy_dir_path)

    os.system(f"copy /y {artifact_build_file_path} {artifact_copy_file_path}")


env.AddPostAction("$BUILD_DIR/${PROGNAME}.elf",  post_action)
env.AddPostAction("$BUILD_DIR/${PROGNAME}.bin",  post_action)

