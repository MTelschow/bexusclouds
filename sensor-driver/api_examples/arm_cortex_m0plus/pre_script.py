"""
Script that holds additional platformio pre-build configuration information
"""
import os

Import("env")

env = DefaultEnvironment()

# External source files, more information: https://docs.platformio.org/en/stable/scripting/examples/external_sources.html
env.BuildSources(env.subst("$BUILD_DIR"), 
                 os.path.join(f'{env.GetProjectOption("custom_common_dir")}', "src")
)

# Custom firmware name, more information: https://docs.platformio.org/en/latest/scripting/examples/custom_program_name.html
env.Replace(PROGNAME=f'{env.GetProjectOption("custom_prog_name")}')




