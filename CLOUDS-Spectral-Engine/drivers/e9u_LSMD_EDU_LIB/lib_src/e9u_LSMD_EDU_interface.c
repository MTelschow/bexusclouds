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

// include for "malloc" and "exit"
#include <stdlib.h>

// include for fixed length integer
#include <stdint.h>

// include for "memset" and "strlen"
#include <string.h>

#include "e9u_LSMD_EDU_defs.h"
#include "e9u_LSMD_EDU_interface.h"


struct e9u_LSMD_EDU_TYPE e9u_LSMD_EDU_type[] = { {"e9u_LSMD-TCD1304-EDU", 3648, 8., 200.,  20,  20, e9u_LSMD_TRIG_EXT | e9u_LSMD_TRIG_USB},
                                                 {"", 0, 0., 0., 0, 0, 0} };




/** @brief ??
 * @param[??] ?? ??
 * @returns ??
 */
int e9u_LSMD_EDU_IO_allocate_interface (struct e9u_LSMD_EDU *e9u_lsmd_edu)
{
// make sure we have pointers initialized with NULL to detect, if free or close is valid:
    e9u_lsmd_edu->ui8_data  	   = NULL;
    e9u_lsmd_edu->ui16_data 	   = NULL;
    e9u_lsmd_edu->ui8_eeprom	   = NULL;
    e9u_lsmd_edu->c_type[0]  	   = 0;
    e9u_lsmd_edu->c_ttyUSB_name[0] = 0;
    e9u_lsmd_edu->i_ttyUSB_open    = 0;
    
    return (e9u_LSMD_EDU_OK);
}




int e9u_LSMD_EDU_IO_set_tty_device (struct e9u_LSMD_EDU *e9u_lsmd_edu, const char *c_device)
{
    strcpy (e9u_lsmd_edu->c_ttyUSB_name, c_device);
    return (e9u_LSMD_EDU_OK);
}



int e9u_LSMD_EDU_IO_open_camera (struct e9u_LSMD_EDU* e9u_lsmd_edu, int i_USB)
{
int    status;
int    i_try_no = 0;
char   c_string[32];
size_t sz_size;

    status = e9u_LSMD_EDU_UART_open (&e9u_lsmd_edu->hd_ttyUSB, e9u_lsmd_edu->c_ttyUSB_name, i_USB);
    if (status == 0) {
        e9u_lsmd_edu->i_ttyUSB_open = 1;

        do {
            ++i_try_no;
            
            if (i_try_no > 1)
                e9u_LSMD_EDU_UART_sendbreak (e9u_lsmd_edu->hd_ttyUSB);
                
            e9u_LSMD_EDU_UART_flush (e9u_lsmd_edu->hd_ttyUSB);
            
            c_string[0] = 0x55;                // "U" like UART
            c_string[1] = 0x49;                // "I" like Identify
            status = e9u_LSMD_EDU_UART_write (e9u_lsmd_edu->hd_ttyUSB, c_string, 2 * sizeof (char), &sz_size);
  
            status = e9u_LSMD_EDU_UART_read (e9u_lsmd_edu->hd_ttyUSB, e9u_lsmd_edu->c_type, 21, &sz_size);
            e9u_lsmd_edu->c_type[21] = 0;

        } while ((strcmp (e9u_lsmd_edu->c_type, e9u_LSMD_EDU_type[0].c_type) != 0) && (++i_try_no < 3));
  
        if (strcmp (e9u_lsmd_edu->c_type, e9u_LSMD_EDU_type[0].c_type) == 0) {
            e9u_lsmd_edu->ui16_pixel_cnt = e9u_LSMD_EDU_type[0].ui16_pixel_cnt;
            strcpy (e9u_lsmd_edu->c_type, e9u_LSMD_EDU_type[0].c_type);

printf ("%s %d\n", e9u_lsmd_edu->c_type, e9u_lsmd_edu->ui16_pixel_cnt);

            return (e9u_LSMD_EDU_OK);
        } else {
            status = e9u_LSMD_EDU_UART_close (e9u_lsmd_edu->hd_ttyUSB);
            e9u_lsmd_edu->i_ttyUSB_open = 0;
        }
    }

    return (e9u_LSMD_EDU_FAIL);
}





int e9u_LSMD_EDU_IO_allocate_data (struct e9u_LSMD_EDU *e9u_lsmd_edu)
{

    e9u_lsmd_edu->ui8_data = (uint8_t *)malloc (sizeof (uint8_t) * e9u_lsmd_edu->ui16_pixel_cnt);
    if (e9u_lsmd_edu->ui8_data == NULL) {
        perror ("malloc e9u_lsmd_buffer:");
        return (e9u_LSMD_EDU_FAIL);
    }

    e9u_lsmd_edu->ui16_data = (uint16_t *)malloc (sizeof (uint16_t) * e9u_lsmd_edu->ui16_pixel_cnt);
    if (e9u_lsmd_edu->ui16_data == NULL) {
        perror ("malloc e9u_lsmd_buffer:");
        return (e9u_LSMD_EDU_FAIL);
    }

    e9u_lsmd_edu->ui8_eeprom = (uint8_t *)malloc (sizeof (uint8_t) * 16384);
    if (e9u_lsmd_edu->ui8_eeprom == NULL) {
        perror ("malloc e9u_lsmd_eeprom:");
        return (e9u_LSMD_EDU_FAIL);
    }

    return (e9u_LSMD_EDU_OK);
}




int e9u_LSMD_EDU_IO_stop_camera (struct e9u_LSMD_EDU *e9u_lsmd_edu)
{
int status;

// send break:

// flush pending transfer:
    status = e9u_LSMD_EDU_UART_flush (e9u_lsmd_edu->hd_ttyUSB);
    return (status);
}



int e9u_LSMD_EDU_IO_read_camera (struct e9u_LSMD_EDU *e9u_lsmd_edu)
{
uint8_t  ui8_value;
uint16_t ui16_sync;
uint32_t ui32_counter;

size_t   sz_transfered = 0;
int      status;

    ui16_sync = 0xaaaa;
    do {
        status = e9u_LSMD_EDU_UART_read (e9u_lsmd_edu->hd_ttyUSB, (char *)&ui8_value, sizeof (uint8_t), &sz_transfered);
        if (status != e9u_LSMD_EDU_OK)
            return (status);

        if (sz_transfered == sizeof (uint8_t))
            ui16_sync = ui16_sync << 8 | ui8_value;
            
    } while ((ui16_sync != 0x0000) && (ui8_value != 0xff));
    
    if (ui8_value == 0xff)
        return (e9u_LSMD_EDU_ALIVE);


    if (ui16_sync == 0x0000) {

        status = e9u_LSMD_EDU_UART_read (e9u_lsmd_edu->hd_ttyUSB, (char *)(&e9u_lsmd_edu->ui16_exp), sizeof (uint16_t), &sz_transfered);
        if (status != e9u_LSMD_EDU_OK)
            return (status);

        status = e9u_LSMD_EDU_UART_read (e9u_lsmd_edu->hd_ttyUSB, (char *)(&e9u_lsmd_edu->ui8_flags), sizeof (uint8_t), &sz_transfered);
        if (status != e9u_LSMD_EDU_OK)
            return (status);

        if (e9u_lsmd_edu->ui8_flags & 0x01) {
            status = e9u_LSMD_EDU_UART_read (e9u_lsmd_edu->hd_ttyUSB, (char *)e9u_lsmd_edu->ui16_data, sizeof (uint16_t) * e9u_lsmd_edu->ui16_pixel_cnt, &sz_transfered);
            if (status != e9u_LSMD_EDU_OK)
                return (status); 
        } else {
            status = e9u_LSMD_EDU_UART_read (e9u_lsmd_edu->hd_ttyUSB, (char *)e9u_lsmd_edu->ui8_data, sizeof (uint8_t) * e9u_lsmd_edu->ui16_pixel_cnt, &sz_transfered);
            if (status != e9u_LSMD_EDU_OK)
                return (status); 

            for (ui32_counter = 0; ui32_counter < e9u_lsmd_edu->ui16_pixel_cnt; ++ui32_counter)
                e9u_lsmd_edu->ui16_data[ui32_counter] = ((uint16_t)e9u_lsmd_edu->ui8_data[ui32_counter] << 8);
        }
    }
    
    return (e9u_LSMD_EDU_OK);
}




int32_t e9u_LSMD_EDU_IO_get_pixel_value (struct e9u_LSMD_EDU *e9u_lsmd_edu, size_t sz_x_position)
{
/*
    if (e9u_lsmd_edu->ui8_flags & 0x01)
      return ((int32_t)e9u_lsmd_edu->ui16_data[sz_x_position]);
    else
      return ((int32_t)e9u_lsmd_edu->ui8_data[sz_x_position]);
*/

      return ((int32_t)e9u_lsmd_edu->ui16_data[sz_x_position]);
}


/** @brief ??
 * @param[??] ?? ??
 * @returns ??
 */
int e9u_LSMD_EDU_IO_send_byte (struct e9u_LSMD_EDU *e9u_lsmd_edu, char c_byte)
{
int	status;
size_t sz_size;

    status = e9u_LSMD_EDU_UART_write (e9u_lsmd_edu->hd_ttyUSB, &c_byte, sizeof (char), &sz_size);
    return (status);
}



/** @brief ??
 * @param[??] ?? ??
 * @returns ??
 */
int e9u_LSMD_EDU_IO_send_word (struct e9u_LSMD_EDU *e9u_lsmd_edu, uint16_t ui16_word)
{
int	status;
size_t sz_size;

    status = e9u_LSMD_EDU_UART_write (e9u_lsmd_edu->hd_ttyUSB, (char *)(&ui16_word), sizeof (uint16_t), &sz_size);
    return (status);
}



/** @brief ??
 * @param[??] ?? ??
 * @returns ??
 */
int e9u_LSMD_EDU_IO_free_memory (struct e9u_LSMD_EDU *e9u_lsmd_edu)
{
    if (e9u_lsmd_edu->ui8_data != NULL)
        free (e9u_lsmd_edu->ui8_data);

    if (e9u_lsmd_edu->ui16_data != NULL)
        free (e9u_lsmd_edu->ui16_data);

    if (e9u_lsmd_edu->ui8_eeprom != NULL)
        free (e9u_lsmd_edu->ui8_eeprom);

    return (e9u_LSMD_EDU_OK);
}





/** @brief ??
 * @param[??] ?? ??
 * @returns ??
 */
int e9u_LSMD_EDU_IO_begin (struct e9u_LSMD_EDU *e9u_lsmd_edu, const char *c_device, int i_USB)
{
int status;

// allocate memory and initialize registers with default values:
    status = e9u_LSMD_EDU_IO_allocate_interface (e9u_lsmd_edu);
    if (status != e9u_LSMD_EDU_OK)
        return (status);

// set device name and open camera:
    status = e9u_LSMD_EDU_IO_set_tty_device (e9u_lsmd_edu, c_device);
    if (status != e9u_LSMD_EDU_OK)
        return (status);

    status = e9u_LSMD_EDU_IO_open_camera (e9u_lsmd_edu, i_USB);
    if (status != e9u_LSMD_EDU_OK)
        return (status);

// allocate image data:
    status = e9u_LSMD_EDU_IO_allocate_data (e9u_lsmd_edu);
    if (status != e9u_LSMD_EDU_OK)
        return (status);

    return (0);
}





/** @brief ??
 * @param[??] ?? ??
 * @returns ??
 */
int e9u_LSMD_EDU_IO_end (struct e9u_LSMD_EDU *e9u_lsmd_edu)
{
int status;

// free memory and close uart:
    status = e9u_LSMD_EDU_IO_close_camera (e9u_lsmd_edu);
    if (status != e9u_LSMD_EDU_OK)
        return (status);

    status = e9u_LSMD_EDU_IO_free_memory (e9u_lsmd_edu);
    if (status != e9u_LSMD_EDU_OK)
        return (status);

    return (e9u_LSMD_EDU_OK);
}





/** @brief ??
 * @param[??] ?? ??
 * @returns ??
 */
int e9u_LSMD_EDU_IO_close_camera (struct e9u_LSMD_EDU *e9u_lsmd_edu)
{
int status = e9u_LSMD_EDU_OK;

    if (e9u_lsmd_edu->i_ttyUSB_open != 0)
        status = e9u_LSMD_EDU_UART_close (e9u_lsmd_edu->hd_ttyUSB);

    e9u_lsmd_edu->i_ttyUSB_open = 0;
    return (status);
}



void * e9u_LSMD_EDU_IO_get_pixel_pointer (struct e9u_LSMD_EDU *e9u_lsmd_edu)
{
        return ((void *)e9u_lsmd_edu->ui16_data);
}



int e9u_LSMD_EDU_IO_get_byte_per_pixel (struct e9u_LSMD_EDU *e9u_lsmd_edu)
{
    if (e9u_lsmd_edu->ui8_flags & e9u_LSMD_TWOBYTE)
        return (2);
    else
        return (1);
}



int e9u_LSMD_EDU_IO_get_pixel_count (struct e9u_LSMD_EDU *e9u_lsmd_edu)
{
    return (e9u_lsmd_edu->ui16_pixel_cnt);

}



int e9u_LSMD_EDU_IO_get_flags (struct e9u_LSMD_EDU *e9u_lsmd_edu)
{
    return (e9u_lsmd_edu->ui8_flags);

}



int e9u_LSMD_EDU_IO_set_flags (struct e9u_LSMD_EDU *e9u_lsmd_edu, uint8_t ui8_flags)
{
    e9u_lsmd_edu->ui8_flags = ui8_flags;
    return (e9u_lsmd_edu->ui8_flags);
}



int e9u_LSMD_EDU_IO_get_exp_time (struct e9u_LSMD_EDU *e9u_lsmd_edu)
{
    return (e9u_lsmd_edu->ui16_exp);

}
