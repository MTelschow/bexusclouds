/*
    EURECA's e9u_LSMD camera software – connect to a e9u_LSMD camera USB module
    Copyright (C) 2020 - 2022 Eureca Messtechnik GmbH, <info@eureca.de>

	This file is part of EURECA's e9u_LSMD camera software.

	EURECA's e9u_LSMD camera software is free software: you can redistribute
	it and/or modify it under the terms of the GNU Lesser General Public
	License as published by the Free Software Foundation, either
	version 3 of the License, or (at your option) any later version.

	EURECA's e9u_LSMD camera software is distributed in the hope that it
	will be useful, but WITHOUT ANY WARRANTY; without even the implied
	warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
	See the GNU General Public License for more details.

    You should have received a copy of the GNU General Public License
	along with Foobar.  If not, see <http://www.gnu.org/licenses/>.



    Diese Datei ist Teil von EURECAs e9u_LSMD Kamera-Software.

	EURECAs e9u_LSMD Kamera-Software ist Freie Software: Sie können sie
	unter den Bedingungen der GNU Lesser General Public License, wie von
	der Free Software Foundation, Version 3 der Lizenz oder (nach Ihrer
	Wahl) jeder neueren veröffentlichten Version, weiter verteilen
	und/oder modifizieren.

	EURECAs e9u_LSMD Kamera-Software wird in der Hoffnung, dass es nützlich
	sein wird, aber OHNE JEDE GEWÄHRLEISTUNG, bereitgestellt; sogar ohne
	die implizite Gewährleistung der MARKTFÄHIGKEIT oder EIGNUNG FÜR
	EINEN BESTIMMTEN ZWECK.  Siehe die GNU General Public License für
	weitere Details.

    Sie sollten eine Kopie der GNU General Public License zusammen mit diesem
    Programm erhalten haben. Wenn nicht, siehe <https://www.gnu.org/licenses/>.

*/


DLL_API int DLL_CALL e9u_LSMD_read_camera (unsigned int ui_camera_index);

DLL_API int DLL_CALL e9u_LSMD_add_status_flag (unsigned int ui_camera_index, int i_flag);
DLL_API int DLL_CALL e9u_LSMD_remove_status_flag (unsigned int ui_camera_index, int i_flag);
DLL_API int DLL_CALL e9u_LSMD_get_status_flag (unsigned int ui_camera_index);

DLL_API int DLL_CALL e9u_LSMD_get_dark_value (unsigned int ui_camera_index, unsigned int ui_channel, unsigned int ui_x_position, unsigned int ui_y_position);
DLL_API int DLL_CALL e9u_LSMD_get_pixel_value (unsigned int ui_camera_index, unsigned int ui_channel, unsigned int ui_x_position, unsigned int ui_y_position);

DLL_API int DLL_CALL e9u_LSMD_set_dark_value (unsigned int ui_camera_index, unsigned int ui_channel, unsigned int ui_x_position, unsigned int ui_y_position, unsigned int ui_value);
DLL_API int DLL_CALL e9u_LSMD_set_pixel_value (unsigned int ui_camera_index, unsigned int ui_channel, unsigned int ui_x_position, unsigned int ui_y_position, unsigned int ui_value);

DLL_API unsigned int DLL_CALL e9u_LSMD_get_frame_counter (unsigned int ui_camera_index, unsigned int ui_channel);
DLL_API unsigned int DLL_CALL e9u_LSMD_check_new_frames (unsigned int ui_camera_index, unsigned int ui_channel);
DLL_API unsigned int DLL_CALL e9u_LSMD_diff32 (unsigned int ui_minuend, unsigned int ui_subtrahend);

DLL_API int DLL_CALL e9u_LSMD_update_memory (unsigned int ui_camera_index, unsigned int ui_channel);

DLL_API int DLL_CALL e9u_LSMD_set_reg (unsigned int ui_camera_index, unsigned int ui_register, unsigned int ui_value);

DLL_API unsigned int DLL_CALL e9u_LSMD_get_reg32 (unsigned int ui_camera_index, unsigned int ui_register, unsigned int ui_rx_tx);
DLL_API unsigned int DLL_CALL e9u_LSMD_get_reg16 (unsigned int ui_camera_index, unsigned int ui_register, unsigned int ui_value_index, unsigned int ui_rx_tx);
DLL_API unsigned int DLL_CALL e9u_LSMD_get_reg8  (unsigned int ui_camera_index, unsigned int ui_register, unsigned int ui_value_index, unsigned int ui_rx_tx);
DLL_API int DLL_CALL e9u_LSMD_overwrite_reg32 (unsigned int ui_camera_index, unsigned int ui_register, unsigned int ui_value, unsigned int ui_rx_tx);
DLL_API int DLL_CALL e9u_LSMD_overwrite_reg16 (unsigned int ui_camera_index, unsigned int ui_register, unsigned int ui_value, unsigned int ui_value_index, unsigned int ui_rx_tx);
DLL_API int DLL_CALL e9u_LSMD_overwrite_reg8  (unsigned int ui_camera_index, unsigned int ui_register, unsigned int ui_value, unsigned int ui_value_index, unsigned int ui_rx_tx);

DLL_API int DLL_CALL e9u_LSMD_update_regs (unsigned int ui_camera_index);
DLL_API int DLL_CALL e9u_LSMD_begin (unsigned int ui_camera_index, const char *c_device);
DLL_API int DLL_CALL e9u_LSMD_end (unsigned int ui_camera_index);
DLL_API int DLL_CALL e9u_LSMD_stop (unsigned int ui_camera_index);

DLL_API int DLL_CALL e9u_LSMD_board_info (unsigned int ui_camera_index);
DLL_API char * DLL_CALL e9u_LSMD_board_type (unsigned int ui_camera_index);
DLL_API char * DLL_CALL e9u_LSMD_eeprom_string (unsigned int ui_camera_index, unsigned int ui_string_index);
DLL_API double DLL_CALL e9u_LSMD_pixel_width (unsigned int ui_camera_index);
DLL_API double DLL_CALL e9u_LSMD_pixel_height (unsigned int ui_camera_index);
DLL_API unsigned int DLL_CALL e9u_LSMD_minimum_exposure (unsigned int ui_camera_index);
DLL_API unsigned int DLL_CALL e9u_LSMD_step_exposure (unsigned int ui_camera_index);
DLL_API unsigned int DLL_CALL e9u_LSMD_minimum_frame (unsigned int ui_camera_index);
DLL_API unsigned int DLL_CALL e9u_LSMD_step_frame (unsigned int ui_camera_index);
DLL_API unsigned int DLL_CALL e9u_LSMD_features (unsigned int ui_camera_index);

DLL_API void * DLL_CALL e9u_LSMD_get_pixel_pointer (unsigned int ui_camera_index, unsigned int ui_channel);
DLL_API int DLL_CALL e9u_LSMD_get_byte_per_pixel (unsigned int ui_camera_index, unsigned int ui_channel);

DLL_API int DLL_CALL e9u_LSMD_I2C_transfer (unsigned int ui_camera_index, unsigned int ui_i2c_adress, unsigned int ui_i2c_count, unsigned int ui_i2c_writeprotect, char *c_i2c_data);
DLL_API int DLL_CALL e9u_LSMD_eeprom_info (unsigned int ui_camera_index, unsigned int ui_pcb_number);

DLL_API int DLL_CALL e9u_LSMD_begin_shm (unsigned int ui_camera_index, const char *c_device, const char *c_mmap_name);
DLL_API int DLL_CALL e9u_LSMD_end_shm (unsigned int ui_camera_index);
DLL_API int DLL_CALL e9u_LSMD_attach_shm (unsigned int ui_camera_index, const char *c_mmap_name);
DLL_API int DLL_CALL e9u_LSMD_detach_shm (unsigned int ui_camera_index);
