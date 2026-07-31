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

// für die Kommunikation mit dem UART:
int e9u_LSMD_EDU_UART_open   (e9u_LSMD_EDU_TTY_HANDLE *h_ttyUSB, char* c_devname, int i_USB);
int e9u_LSMD_EDU_UART_close  (e9u_LSMD_EDU_TTY_HANDLE h_ttyUSB);
int e9u_LSMD_EDU_UART_write  (e9u_LSMD_EDU_TTY_HANDLE h_ttyUSB, char* c_buffer, size_t sz_count, size_t* sz_written);
int e9u_LSMD_EDU_UART_read   (e9u_LSMD_EDU_TTY_HANDLE h_ttyUSB, char* c_buffer, size_t sz_count, size_t* sz_read);
int e9u_LSMD_EDU_UART_flush  (e9u_LSMD_EDU_TTY_HANDLE h_ttyUSB);
int e9u_LSMD_EDU_UART_sendbreak (e9u_LSMD_EDU_TTY_HANDLE h_ttyUSB);


struct e9u_LSMD_EDU_TYPE { char        c_type[32];
                           uint16_t    ui16_pixel_cnt;
                           double      d_pixel_width;
                           double      d_pixel_height;
                           uint32_t    ui32_min_exp;
                           uint32_t    ui32_step_exp;
                           uint32_t    ui32_features; };


struct e9u_LSMD_EDU { uint8_t                   *ui8_data;
                      uint16_t                  *ui16_data;
                      uint16_t			ui16_pixel_cnt;
                      uint8_t                   ui8_flags;
                      uint16_t                  ui16_exp;
                      uint8_t                   *ui8_eeprom;
                      char			c_type[32];
                      char                      c_ttyUSB_name[128];
                      e9u_LSMD_EDU_TTY_HANDLE   hd_ttyUSB;
                      int                       i_ttyUSB_open; };



// Funktion zum setzen des UART Device Namens:
int e9u_LSMD_EDU_IO_set_tty_device (struct e9u_LSMD_EDU *e9u_lsmd_edu, const char *c_device);

// Funktion zum initialisieren der Variablen:
int e9u_LSMD_EDU_IO_allocate_interface (struct e9u_LSMD_EDU *e9u_lsmd_edu);

// Funktion zum Initialisieren der Kamera:
int e9u_LSMD_EDU_IO_open_camera(struct e9u_LSMD_EDU *e9u_lsmd_edu, int i_USB);

// Funktion zum Schließen der Kamera:
int e9u_LSMD_EDU_IO_close_camera (struct e9u_LSMD_EDU *e9u_lsmd_edu);

// Funktion zum Lesen von der Kamera:
int e9u_LSMD_EDU_IO_read_camera (struct e9u_LSMD_EDU *e9u_lsmd_edu);

// Funktion zum Lesen eines Pixels aus dem Array:
int32_t e9u_LSMD_EDU_IO_get_pixel_value (struct e9u_LSMD_EDU *e9u_lsmd_edu, size_t sz_x_position);

// Funktion zum Senden von Daten an die Kamera:
int e9u_LSMD_EDU_IO_send_byte (struct e9u_LSMD_EDU *e9u_lsmd_edu, char c_byte);
int e9u_LSMD_EDU_IO_send_word (struct e9u_LSMD_EDU *e9u_lsmd_edu, uint16_t ui16_word);

// Makro zur Initialisierung von UART und Kamera:
int e9u_LSMD_EDU_IO_begin (struct e9u_LSMD_EDU *e9u_lsmd_edu, const char *c_device, int i_USB);

// Marko, um den Pointer auf das Pixel Array direkt zu bekommen:
void *e9u_LSMD_EDU_IO_get_pixel_pointer (struct e9u_LSMD_EDU *e9u_lsmd_edu);
int e9u_LSMD_EDU_IO_get_byte_per_pixel (struct e9u_LSMD_EDU *e9u_lsmd_edu);
int e9u_LSMD_EDU_IO_get_flags (struct e9u_LSMD_EDU *e9u_lsmd_edu);
int e9u_LSMD_EDU_IO_set_flags (struct e9u_LSMD_EDU *e9u_lsmd_edu, uint8_t ui8_flags);
int e9u_LSMD_EDU_IO_get_pixel_count (struct e9u_LSMD_EDU *e9u_lsmd_edu);
int e9u_LSMD_EDU_IO_get_exp_time (struct e9u_LSMD_EDU *e9u_lsmd_edu);
