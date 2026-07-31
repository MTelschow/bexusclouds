/*
    EURECA's e9u_LSMD_EDU camera software – connect to a e9u_LSMD_EDU camera USB module
    Copyright (C) 2020 - 2025 Eureca Messtechnik GmbH, <info@eureca.de>

	This file is part of EURECA's e9u_LSMD_EDU camera software.

	EURECA's e9u_LSMD_EDU camera software is free software: you can redistribute
	it and/or modify it under the terms of the GNU Lesser General Public
	License as published by the Free Software Foundation, either
	version 3 of the License, or (at your option) any later version.

	EURECA's e9u_LSMD_EDU camera software is distributed in the hope that it
	will be useful, but WITHOUT ANY WARRANTY; without even the implied
	warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
	See the GNU General Public License for more details.

    You should have received a copy of the GNU General Public License
	along with Foobar.  If not, see <http://www.gnu.org/licenses/>.



    Diese Datei ist Teil von EURECAs e9u_LSMD_EDU Kamera-Software.

	EURECAs e9u_LSMD_EDU Kamera-Software ist Freie Software: Sie können sie
	unter den Bedingungen der GNU Lesser General Public License, wie von
	der Free Software Foundation, Version 3 der Lizenz oder (nach Ihrer
	Wahl) jeder neueren veröffentlichten Version, weiter verteilen
	und/oder modifizieren.

	EURECAs e9u_LSMD_EDU Kamera-Software wird in der Hoffnung, dass es nützlich
	sein wird, aber OHNE JEDE GEWÄHRLEISTUNG, bereitgestellt; sogar ohne
	die implizite Gewährleistung der MARKTFÄHIGKEIT oder EIGNUNG FÜR
	EINEN BESTIMMTEN ZWECK.  Siehe die GNU General Public License für
	weitere Details.

    Sie sollten eine Kopie der GNU General Public License zusammen mit diesem
    Programm erhalten haben. Wenn nicht, siehe <https://www.gnu.org/licenses/>.

*/


DLL_API int DLL_CALL e9u_LSMD_EDU_read_camera (unsigned int ui_camera_index);

DLL_API int DLL_CALL e9u_LSMD_EDU_get_pixel_value (unsigned int ui_camera_index, unsigned int ui_x_position);

DLL_API int DLL_CALL e9u_LSMD_EDU_send_byte (unsigned int ui_camera_index, char c_byte);
DLL_API int DLL_CALL e9u_LSMD_EDU_send_word (unsigned int ui_camera_index, unsigned int ui_value);

DLL_API int DLL_CALL e9u_LSMD_EDU_begin (unsigned int ui_camera_index, const char *c_device, int i_USB);

DLL_API int DLL_CALL e9u_LSMD_EDU_board_info (unsigned int ui_camera_index);
DLL_API char * DLL_CALL e9u_LSMD_EDU_board_type (unsigned int ui_camera_index);
DLL_API char * DLL_CALL e9u_LSMD_EDU_eeprom_string (unsigned int ui_camera_index, unsigned int ui_string_index);

DLL_API void * DLL_CALL e9u_LSMD_EDU_get_pixel_pointer (unsigned int ui_camera_index);
DLL_API int DLL_CALL e9u_LSMD_EDU_get_byte_per_pixel (unsigned int ui_camera_index);
DLL_API int DLL_CALL e9u_LSMD_EDU_get_flags (unsigned int ui_camera_index);
DLL_API int DLL_CALL e9u_LSMD_EDU_set_flags (unsigned int ui_camera_index, unsigned int ui_flags);
DLL_API int DLL_CALL e9u_LSMD_EDU_get_pixel_count (unsigned int ui_camera_index);
DLL_API int DLL_CALL e9u_LSMD_EDU_get_exp_time (unsigned int ui_camera_index);

