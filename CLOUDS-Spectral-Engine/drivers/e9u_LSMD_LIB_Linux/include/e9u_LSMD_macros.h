/*
    EURECA's e9u_LSMD camera software – connect to a e9u_LSMD camera USB module
    Copyright (C) 2020 -2022 Eureca Messtechnik GmbH, <info@eureca.de>

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

DLL_API int DLL_CALL e9u_LSMD_search_for_camera (unsigned int ui_camera_index);
DLL_API int DLL_CALL e9u_LSMD_start_camera_freerun (unsigned int ui_camera_index);
DLL_API int DLL_CALL e9u_LSMD_start_camera_trigger (unsigned int ui_camera_index);
DLL_API int DLL_CALL e9u_LSMD_start_camera_async (unsigned int ui_camera_index);
DLL_API int DLL_CALL e9u_LSMD_set_times (unsigned int ui_camera_index, double d_exp_time, double d_frame_time);
DLL_API int DLL_CALL e9u_LSMD_set_times_us (unsigned int ui_camera_index, unsigned int ui_exp_time, unsigned int ui_frame_time);
DLL_API int DLL_CALL e9u_LSMD_get_next_frame (unsigned int ui_camera_index);
DLL_API int DLL_CALL e9u_LSMD_wait_times (unsigned int ui_camera_index, double d_exp_time, double d_frame_time);
DLL_API int DLL_CALL e9u_LSMD_wait_times_us (unsigned int ui_camera_index, unsigned int ui_exp_time, unsigned int ui_frame_time);
DLL_API int DLL_CALL e9u_LSMD_discard_frames (unsigned int ui_camera_index, unsigned int ui_frames);
