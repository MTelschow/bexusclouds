/*
    EURECA's e9u_LSMD_EDU camera software – connect to a e9u_LSMD_EDU camera USB module
    Copyright (C) 2020 -2022 Eureca Messtechnik GmbH, <info@eureca.de>

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

#ifdef __linux__
    #include "e9u_LSMD_EDU_Linux.h"

    /* Define with no value on non-Windows OSes. */
    #define DLL_API
    #define DLL_CALL
#endif


#ifdef _WIN32
    #include "e9u_LSMD_EDU_Windows.h"

    /* You should define DLL__EXPORTS *only* when building the DLL. */
    #ifdef DLL_EXPORTS
        #define DLL_API __declspec(dllexport)
    #else
        #define DLL_API __declspec(dllimport)
    #endif

    /* Define calling convention in one place, for convenience. */
    #define DLL_CALL __cdecl
#endif


#define e9u_LSMD_EDU_API_VERSION 0x22022501

enum e9u_LSMD_EDU_return {
	e9u_LSMD_EDU_FAIL            =-1,
	e9u_LSMD_EDU_OK              =0x0000,
	e9u_LSMD_EDU_ALIVE           =0x0001,
	e9u_LSMD_EDU_TIMEOUT         =0x0002,
};


enum e9u_LSMD_EDU_interface {
	e9u_LSMD_EDU_UART            =0,
	e9u_LSMD_EDU_USB             =1,
};


enum e9u_LSMD_EDU_feature {
        e9u_LSMD_TRIG_INT        = 0x00000010,
        e9u_LSMD_TRIG_EXT        = 0x00000020,
        e9u_LSMD_TRIG_USB        = 0x00000040,
        e9u_LSMD_GPIO            = 0x00000100
};


enum e9u_LSMD_EDU_flag {
        e9u_LSMD_TWOBYTE      = 0x01,
        e9u_LSMD_TRIGEN       = 0x02,
        e9u_LSMD_CONNTEN      = 0x04,
        e9u_LSMD_TRIGERED     = 0x08,
        e9u_LSMD_WRITEEN      = 0x20,
        e9u_LSMD_KEEPALIVE    = 0x40,
        e9u_LSMD_HIGHSPEED    = 0x80
};




DLL_API int DLL_CALL e9u_LSMD_EDU_SLEEP_ms    (unsigned int ui_ms);
DLL_API int DLL_CALL e9u_LSMD_EDU_UART_exists (char* c_devname);
