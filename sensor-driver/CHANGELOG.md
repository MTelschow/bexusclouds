# Changelog

## v11.2.0, 2025-Jul-11
### Added
- Support for RISC-V platform:
  * RV32IMC (sensor driver libraries and SDK example targeting ESP32-C6)
  * RV32IMAFC (sensor driver libraries only)
- Support for ARM Cortex-M33 platform (sensor driver libraries only).
- Web Application v1.0.0 for use with the Bosch Sensortec Application Board 3.1 and BMV080 shuttle board 3.1, offering a user interface to configure, perform measurements, and visualize sensor data. 

### Changed
- ESP-IDF version is updated to 5.4.1 (from 5.3.0).
- Improvements in  obstruction notification:
  * Reduced false positive obstruction notifications
  * Memory optimization

### Fixed
- Improved PM10 mass concentration estimation.
- Improved PM number concentrations estimation.

## v11.1.0, 2025-Apr-15
### Added
- Support for Bosch Sensortec Application Board 3.1 and BMV080 shuttle board 3.1 through the COINES SDK.
- Support for ARM Cortex-M7F platform.
  
### Changed
- PlatformIO version is updated to 6.1.17 (from 6.1.0).
- Python version is updated to 3.12 (from 3.8).
- Optimization level changed to `Os` for the SDK examples compilation.
  
### Fixed
- Fix to ensure reported PM values are physically plausible and satisfy the condition: PM10 >= PM2.5 >= PM1.
- Duplicate value of status code E_BMV080_ERROR_MEM_INTERNAL_TEST_2 is fixed by using a value of 181 instead of 161.

## v11.0.0, 2025-Jan-30
### Added
- PM10 mass concentration value is included in the Sensor Driver output structure and logged to console in the SDK example.
- PM2.5, PM1 and PM10 number concentration values are included in the Sensor Driver output structure.
