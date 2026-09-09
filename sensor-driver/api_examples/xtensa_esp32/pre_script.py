"""
Script that holds additional platformio pre-build configuration information
"""
import os

Import("env")

# External source files, more information: https://docs.platformio.org/en/stable/scripting/examples/external_sources.html
env.BuildSources(env.subst("$BUILD_DIR"), 
                 os.path.join(f'{env.GetProjectOption("custom_common_dir")}', "src")
)

# Additional linker flags, more information: https://docs.platformio.org/en/latest/scripting/examples/extra_linker_flags.html
env.Append(
  LINKFLAGS=[
        "-static",
        "-u _printf_float"
  ]
)

# Custom build directory such that it fits target/compiler/build_configuration structure
mcu = env['BOARD_MCU'].lower()
env['PROJECT_BUILD_DIR'] = os.path.join(env['PROJECT_DIR'], "build", env.GetProjectOption(f"custom_target_{mcu}"), env.GetProjectOption(f"custom_compiler_{mcu}"))
env_parts = env["PIOENV"].split("_")
build_configuration_name = '_'.join(env_parts[:len(env_parts) - 1])
env['BUILD_DIR'] = os.path.join(env['PROJECT_BUILD_DIR'], build_configuration_name)

# Custom firmware name, more information: https://docs.platformio.org/en/latest/scripting/examples/custom_program_name.html
env.Replace(PROGNAME=f'{env.GetProjectOption("custom_prog_name")}')