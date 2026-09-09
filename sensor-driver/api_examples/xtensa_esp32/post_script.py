"""
Script that holds additional platformio post-build configuration information
"""
import os

Import("env")

# When using the ESP32-S2 board, boot mode needs to be entered manually before the upload action is executed.
# After upload, the SoC remains in boot mode and a hard reset to exit boot mode is not possible without manual action.
# Hence, no_reset option is used (after upload), in order to prevent an error reporting that the automatic reset failed.

Import("env")

if 'esp32s2' in env.subst("$PIOENV").lower():
    default_upload_flags = env["UPLOADERFLAGS"]
    custom_upload_flags =  ["no_reset" if flag == "hard_reset" else flag for flag in default_upload_flags]

    env.Replace(
        UPLOADERFLAGS = custom_upload_flags
    )


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
env.AddPostAction("$BUILD_DIR/bootloader.elf",  post_action)
env.AddPostAction("$BUILD_DIR/bootloader.bin",  post_action)
env.AddPostAction("$BUILD_DIR/partitions.bin",  post_action)
