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

// include for "sprintf"
#include <stdio.h>

// include for "exit"
#include <stdlib.h>

// include for "strcpy"
#include <string.h>

// include for fixed length integer
#include <stdint.h>

#include "e9u_LSMD_EDU_defs.h"
#include "e9u_LSMD_EDU.h"
#include "e9u_LSMD_EDU_macros.h"





/** @brief ??
 * @param[??] ?? ??
 * @returns ??
 */
int DLL_CALL e9u_LSMD_EDU_search_for_camera (unsigned int ui_camera_index, int i_USB) {
int             i_status;
int             i_UART;
char            c_dev_name[256];

// test UARTs:
    i_UART = 99;
    do {
        sprintf (c_dev_name, "%s%s%d", e9u_LSMD_EDU_UART_DIRPREFIX, e9u_LSMD_EDU_UART_DEVPREFIX, i_UART);
        i_status = e9u_LSMD_EDU_UART_exists (c_dev_name);
        if (i_status == e9u_LSMD_EDU_OK) {
            i_status = e9u_LSMD_EDU_begin (ui_camera_index, c_dev_name, i_USB);
//            if (i_status == e9u_LSMD_EDU_FAIL)
//                e9u_LSMD_EDU_end (ui_camera_index);
        }
        
        if (i_status == e9u_LSMD_EDU_FAIL) {
            --i_UART;
            if (i_UART < 0) {
                printf ("ERROR: did not find any e9u_LSMD_EDU camera!\n");
                return (e9u_LSMD_EDU_FAIL);
            }
        }
    } while (i_status == e9u_LSMD_EDU_FAIL);

// print camera information:
/*
    printf ("API Version %X, using device %s:\n", e9u_LSMD_EDU_API_VERSION, c_dev_name);
    i_status = e9u_LSMD_EDU_board_info (ui_camera_index);
    i_status |= e9u_LSMD_EDU_eeprom_info (ui_camera_index, e9u_LSMD_EDU_SENSOR_BOARD);
    if (i_status == e9u_LSMD_EDU_FAIL)
        return (e9u_LSMD_EDU_FAIL);
*/
    return (e9u_LSMD_EDU_OK);
}


/** @brief ??
 * @param[??] ?? ??
 * @returns ??
 */
int DLL_CALL e9u_LSMD_EDU_start_camera_async (unsigned int ui_camera_index) {
int i_status = e9u_LSMD_EDU_OK;

    return (i_status);
}






/** @brief ??
 * @param[??] ?? ??
 * @returns ??
 */
int DLL_CALL e9u_LSMD_EDU_set_exp_time (unsigned int ui_camera_index, double d_exp_time) {
unsigned int ui_exp_time;

// calculate ms float to us int:
    if (d_exp_time <= 0.)
        ui_exp_time = 0;
    else
        ui_exp_time = d_exp_time * 1000;

    return (e9u_LSMD_EDU_set_exp_time_us (ui_camera_index, ui_exp_time));
}



/** @brief ??
 * @param[??] ?? ??
 * @returns ??
 */
int DLL_CALL e9u_LSMD_EDU_set_exp_time_us (unsigned int ui_camera_index, unsigned int ui_exp_time) {
int      i_status;

// calculate exposure time value to send:
    if (ui_exp_time < 65535l * 20)
        ui_exp_time /= 20;
    else
        ui_exp_time = 65535;

// check for minimum exposure:
    if (ui_exp_time < 1)
        ui_exp_time = 1;

    i_status = e9u_LSMD_EDU_send_byte (ui_camera_index, 'E');

    if (i_status == e9u_LSMD_EDU_OK)
        i_status = e9u_LSMD_EDU_send_word (ui_camera_index, ui_exp_time);

    return (i_status);
}





/** @brief ??
 * @param[??] ?? ??
 * @returns ??
 */
int DLL_CALL e9u_LSMD_EDU_get_next_frame (unsigned int ui_camera_index) {
int     i_status = e9u_LSMD_EDU_OK;

// trigger async USB, if not in free run or external trigger mode:

    if (!(e9u_LSMD_EDU_get_flags (ui_camera_index) & (e9u_LSMD_TRIGEN | e9u_LSMD_TRIGERED))) {	// prüfe auf Trigger
        i_status = e9u_LSMD_EDU_send_byte (ui_camera_index, 'S');
        e9u_LSMD_EDU_set_flags (ui_camera_index, e9u_LSMD_EDU_get_flags (ui_camera_index) | e9u_LSMD_TRIGERED);        
    }
    
    if (i_status == e9u_LSMD_EDU_OK)
        i_status = e9u_LSMD_EDU_read_camera (ui_camera_index);

    return (i_status);
}
