/*
    EURECA's e9u_LSMD_EDU camera software – connect to a e9u_LSMD_EDU camera USB module
    Copyright (C) 2020 - 2022 Eureca Messtechnik GmbH, <info@eureca.de>

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

// include for "printf"
#include <stdio.h>

// include for fixed length integer
#include <stdint.h>

#include "e9u_LSMD_EDU_defs.h"
#include "e9u_LSMD_EDU_interface.h"
#include "e9u_LSMD_EDU.h"



// make use of C99 Standard 6.7.8.21:
// If there are fewer initializers in a brace-enclosed list than there are elements
// or members of an aggregate, or fewer characters in a string literal used to
// initialize an array of known size than there are elements in the array,
// the remainder of the aggregate shall be initialized implicitly the same
// as objects that have static storage duration.

struct e9u_LSMD_EDU e9u_lsmd_edu[8] = { {NULL, NULL, 0, 0, 0, NULL, "", "", 0, 0} };


/** @brief ??
 * @param[in] ui_camera_index ??
 * @returns ??
 * @todo sanitize input
 */
int DLL_CALL e9u_LSMD_EDU_read_camera (unsigned int ui_camera_index)
{
int     status;

    status = e9u_LSMD_EDU_IO_read_camera (&e9u_lsmd_edu[ui_camera_index]);
    
    return (status);
}    


/** @brief ??
 * @param[??] ?? ??
 * @returns ??
 */
int DLL_CALL e9u_LSMD_EDU_get_pixel_value (unsigned int ui_camera_index, unsigned int ui_x_position)
{
    return (e9u_LSMD_EDU_IO_get_pixel_value (&e9u_lsmd_edu[ui_camera_index], ui_x_position));
}



/** @brief ??
 * @param[??] ?? ??
 * @returns ??
 */
int DLL_CALL e9u_LSMD_EDU_send_byte (unsigned int ui_camera_index, char c_byte)
{
int status;

    status = e9u_LSMD_EDU_IO_send_byte (&e9u_lsmd_edu[ui_camera_index], c_byte);
    if (status != e9u_LSMD_EDU_OK)
        return (e9u_LSMD_EDU_FAIL);
        
    return (0);
}    


int DLL_CALL e9u_LSMD_EDU_send_word (unsigned int ui_camera_index, unsigned int ui_value)
{
int status;

    status = e9u_LSMD_EDU_IO_send_word (&e9u_lsmd_edu[ui_camera_index], ui_value);
    if (status != e9u_LSMD_EDU_OK)
        return (e9u_LSMD_EDU_FAIL);
        
    return (0);
}    
   



/** @brief ??
 * @param[??] ?? ??
 * @returns ??
 */
int DLL_CALL e9u_LSMD_EDU_begin (unsigned int ui_camera_index, const char *c_device, int i_USB)
{
int status;

    status = e9u_LSMD_EDU_IO_begin (&e9u_lsmd_edu[ui_camera_index], c_device, i_USB);
    if (status != e9u_LSMD_EDU_OK)
        return (e9u_LSMD_EDU_FAIL);
        
    return (0);
}    





/** ggf **/
/*
int DLL_CALL e9u_LSMD_EDU_board_info (unsigned int ui_camera_index)
{
int status;

    status = e9u_LSMD_EDU_IO_board_info (&e9u_lsmd_edu[ui_camera_index]);
    if (status != e9u_LSMD_EDU_OK)
        return (e9u_LSMD_EDU_FAIL);
        
    return (0);
}    



char * DLL_CALL e9u_LSMD_EDU_board_type (unsigned int ui_camera_index)
{
    return (e9u_LSMD_EDU_IO_board_type (&e9u_lsmd_edu[ui_camera_index]));
}


char * DLL_CALL e9u_LSMD_EDU_eeprom_string (unsigned int ui_camera_index, unsigned int ui_string_index)
{
    return (e9u_LSMD_EDU_IO_eeprom_string (&e9u_lsmd_edu[ui_camera_index], ui_string_index));
}
*/


/** @brief ??
 * @param[??] ?? ??
 * @returns ??
 */
void * DLL_CALL e9u_LSMD_EDU_get_pixel_pointer (unsigned int ui_camera_index)
{
    return (e9u_LSMD_EDU_IO_get_pixel_pointer (&e9u_lsmd_edu[ui_camera_index]));
}


/** @brief ??
 * @param[??] ?? ??
 * @returns ??
 */
int DLL_CALL e9u_LSMD_EDU_get_byte_per_pixel (unsigned int ui_camera_index)
{
    return (e9u_LSMD_EDU_IO_get_byte_per_pixel (&e9u_lsmd_edu[ui_camera_index]));
}




/** @brief ??
 * @param[??] ?? ??
 * @returns ??
 */
int DLL_CALL e9u_LSMD_EDU_get_flags (unsigned int ui_camera_index)
{
    return (e9u_LSMD_EDU_IO_get_flags (&e9u_lsmd_edu[ui_camera_index]));
}




/** @brief ??
 * @param[??] ?? ??
 * @returns ??
 */
int DLL_CALL e9u_LSMD_EDU_set_flags (unsigned int ui_camera_index, unsigned int ui_flags)
{
    return (e9u_LSMD_EDU_IO_set_flags (&e9u_lsmd_edu[ui_camera_index], ui_flags));
}




/** @brief ??
 * @param[??] ?? ??
 * @returns ??
 */
int DLL_CALL e9u_LSMD_EDU_get_pixel_count (unsigned int ui_camera_index)
{
    return (e9u_LSMD_EDU_IO_get_pixel_count (&e9u_lsmd_edu[ui_camera_index]));
}



/** @brief ??
 * @param[??] ?? ??
 * @returns ??
 */
int DLL_CALL e9u_LSMD_EDU_get_exp_time (unsigned int ui_camera_index)
{
    return (e9u_LSMD_EDU_IO_get_exp_time (&e9u_lsmd_edu[ui_camera_index]));
}






/** ggf **/
/*
int DLL_CALL e9u_LSMD_EDU_eeprom_info (unsigned int ui_camera_index, unsigned int ui_pcb_number)
{
int status;

    status = e9u_LSMD_EDU_IO_eeprom_info (&e9u_lsmd_edu[ui_camera_index], ui_pcb_number);
    if (status != e9u_LSMD_EDU_OK)
        return (e9u_LSMD_EDU_FAIL);
        
    return (0);
}    
*/

