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
custom_link_flags = [
        "-static",
        "-mthumb", 
        "-u _printf_float"
  ]

use_fpu = 'm4f' in env.subst("$PIOENV").lower()
if use_fpu:
    custom_link_flags.extend(["-mfpu=fpv4-sp-d16", "-mfloat-abi=hard"])
else:
    custom_link_flags.extend(["-mfloat-abi=soft"])

env.Append(
  LINKFLAGS=custom_link_flags
)

# Custom firmware name, more information: https://docs.platformio.org/en/latest/scripting/examples/custom_program_name.html
env.Replace(PROGNAME=f'{env.GetProjectOption("custom_prog_name")}')