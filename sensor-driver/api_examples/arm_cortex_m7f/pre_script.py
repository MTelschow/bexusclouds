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


def pre_link(source, target, env):
  # Additional linker flags, more information: https://docs.platformio.org/en/latest/scripting/examples/extra_linker_flags.html
  custom_link_flags = [
    '-static',
    '-mthumb',
    '-mcpu=cortex-m7',
    '-mfpu=fpv5-sp-d16',
    '-mfloat-abi=hard',
    '-Wl,--gc-sections',
    '-Wl,-u_printf_float',
    '-Wl,--static',
    '-Wl,-T$LDSCRIPT_PATH',
    '-Wl,--gc-sections',
    '--specs=nano.specs',
    '--specs=nosys.specs',
    '-Wl,-Map="${BUILD_DIR}\\${PROGNAME}.map"',
    ]

  env.Replace(
    LINKFLAGS=custom_link_flags
  )

env.AddPreAction("$PROGPATH", pre_link)
