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

#ifdef __linux__
    #include "e9u_LSMD_Linux.h"

    /* Define with no value on non-Windows OSes. */
    #define DLL_API
    #define DLL_CALL
#endif


#ifdef _WIN32
    #include "e9u_LSMD_Windows.h"

    /* You should define DLL__EXPORTS *only* when building the DLL. */
    #ifdef DLL_EXPORTS
        #define DLL_API __declspec(dllexport)
    #else
        #define DLL_API __declspec(dllimport)
    #endif

    /* Define calling convention in one place, for convenience. */
    #define DLL_CALL __cdecl
#endif


#define e9u_LSMD_API_VERSION 0x22022501

#define e9u_LSMD_CH0_CONTROL           0x00
#define e9u_LSMD_CH0_EXP_TIME          0x01
#define e9u_LSMD_CH0_FRAME_TIME        0x02
#define e9u_LSMD_CH0_TRIG_DELAY        0x03
#define e9u_LSMD_CH0_T_STAMP_EXP_STOP  0x05
#define e9u_LSMD_CH0_T_STAMP_EXP_START 0x06
#define e9u_LSMD_CH0_T_STAMP_TRIG      0x07
#define e9u_LSMD_CH0_DARK_PRE          0x0b
#define e9u_LSMD_CH0_PIXEL             0x0c
#define e9u_LSMD_CH0_DARK_POST         0x0d
#define e9u_LSMD_CH0_ADC               0x0e
#define e9u_LSMD_CH0_TYPE              0x0f
#define e9u_LSMD_GLOBAL_CONTROL        0x80
#define e9u_LSMD_VENDOR                0x8d
#define e9u_LSMD_BOARD_TYPE            0x8e
#define e9u_LSMD_FPGA_VERSION          0x8f
#define e9u_LSMD_I2C                   0x90
#define e9u_LSMD_DATA_CH0              0xf0
#define e9u_LSMD_QUERY_REGS            0xfe
#define e9u_LSMD_STAY_ALIVE            0xff

#define e9u_LSMD_C0C_EXP_INT           0x00000001
#define e9u_LSMD_C0C_EXPOSURE          0x00000002
#define e9u_LSMD_C0C_TRIG_INT          0x00000010
#define e9u_LSMD_C0C_TRIG_EXT          0x00000020
#define e9u_LSMD_C0C_TRIG_USB          0x00000040
#define e9u_LSMD_C0C_TRIG_DEBOUNCE     0x00000080
#define e9u_LSMD_C0C_PIX_DUMMY         0x00000100
#define e9u_LSMD_C0C_PIX_DARK          0x00000200
#define e9u_LSMD_C0C_PIX_VALUE         0x00000400
#define e9u_LSMD_C0C_FILL_DITH         0x00000000
#define e9u_LSMD_C0C_FILL_ZERO         0x00001000
#define e9u_LSMD_C0C_FILL_LIN          0x00002000
#define e9u_LSMD_C0C_FILL_ONES         0x00003000

#define e9u_PDMD_C0C_1e03_V_A          0x00030000
#define e9u_PDMD_C0C_1e04_V_A          0x00040000
#define e9u_PDMD_C0C_1e05_V_A          0x00050000
#define e9u_PDMD_C0C_1e06_V_A          0x00060000
#define e9u_PDMD_C0C_1e07_V_A          0x00070000
#define e9u_PDMD_C0C_1e06_V_C          0x00160000
#define e9u_PDMD_C0C_1e07_V_C          0x00170000
#define e9u_PDMD_C0C_1e08_V_C          0x00180000
#define e9u_PDMD_C0C_1e09_V_C          0x00190000
#define e9u_PDMD_C0C_1e10_V_C          0x001A0000
#define e9u_PDMD_C0C_1e09_V_As         0x00290000
#define e9u_PDMD_C0C_1e10_V_As         0x002A0000
#define e9u_PDMD_C0C_1e11_V_As         0x002B0000
#define e9u_PDMD_C0C_1e12_V_As         0x002C0000
#define e9u_PDMD_C0C_1e13_V_As         0x002D0000
#define e9u_PDMD_C0C_CHK_GAIN          0x003F0000

#define e9u_PDMD_C0C_DISCONNECT        0x00400000
#define e9u_PDMD_C0C_DISCHARGE         0x00800000

#define e9u_LSMD_GC_CHANNEL_0          0x00000001
#define e9u_LSMD_GC_STAY_ALIVE         0x00000100
#define e9u_LSMD_GC_SEND_CONF          0x00000200
#define e9u_LSMD_GC_SEND_TIME          0x00000400
#define e9u_LSMD_GC_SEND_TYPE          0x00000800

//define default values
#define e9u_LSMD_C0C_DEFAULT e9u_LSMD_C0C_EXP_INT | e9u_LSMD_C0C_TRIG_INT | e9u_LSMD_C0C_TRIG_DEBOUNCE | e9u_LSMD_C0C_PIX_DARK | e9u_LSMD_C0C_PIX_VALUE | e9u_LSMD_C0C_FILL_DITH
#define e9u_LSMD_GC_DEFAULT e9u_LSMD_GC_CHANNEL_0 | e9u_LSMD_GC_STAY_ALIVE | e9u_LSMD_GC_SEND_CONF | e9u_LSMD_GC_SEND_TIME

enum e9u_LSMD_return {
	e9u_LSMD_FAIL            =-1,
	e9u_LSMD_OK              =0x0000,
	e9u_LSMD_ERROR_OPEN      =0x0001,
	e9u_LSMD_ERROR_CLOSE     =0x0002,
	e9u_LSMD_ERROR_FLUSH     =0x0004,
	e9u_LSMD_ERROR_WRITE     =0x0010,
	e9u_LSMD_TIMEOUT_WRITE   =0x0020,
	e9u_LSMD_ERROR_READ      =0x0040,
	e9u_LSMD_TIMEOUT_READ    =0x0080,
	e9u_LSMD_WARNING_UNKOWN  =0x0100,
	e9u_LSMD_ERROR_PROTO     =0x0200,
	e9u_LSMD_ERROR_MALLOC    =0x0400,
	e9u_LSMD_ERROR_SEMAPHORE =0x0080,
	e9u_LSMD_QUIT            =0x0800
};

enum e9u_LSMD_status {
	e9u_LSMD_NONE            =0x0000,
	e9u_LSMD_OPENED          =0x0001,
	e9u_LSMD_QUERIED         =0x0002,
	e9u_LSMD_VERIFIED        =0x0004,
	e9u_LSMD_ALLOCATED       =0x0008,
	e9u_LSMD_STARTED         =0x0010,
	e9u_LSMD_SYNC            =0x0020,
	e9u_LSMD_READ            =0x0040,
	e9u_LSMD_COPY            =0x0080,
	e9u_LSMD_LOCK            =0x0100,
	e9u_LSMD_PAUSE           =0x0200,
	e9u_LSMD_THREAD          =0x0400,
	e9u_LSMD_REQUEST_QUIT    =0x0800
};

enum e9u_LSMD_feature {
        e9u_LSMD_EXP_INT         = 0x00000001,
        e9u_LSMD_EXP_EXT         = 0x00000002,
        e9u_LSMD_TRIG_INT        = 0x00000010,
        e9u_LSMD_TRIG_EXT        = 0x00000020,
        e9u_LSMD_TRIG_USB        = 0x00000040,
        e9u_LSMD_GPIO            = 0x00000100
};

// define some constants
#define e9u_LSMD_TX 1
#define e9u_LSMD_RX 0
#define e9u_LSMD_SH 2
#define e9u_LSMD_DT 3
#define e9u_LSMD_VER 0
#define e9u_LSMD_HOR 1
#define e9u_LSMD_FPGA_BOARD   1
#define e9u_LSMD_SENSOR_BOARD 2

#define e9u_LSMD_EEPROM_TYPE	0
#define e9u_LSMD_EEPROM_SN	1
#define e9u_LSMD_EEPROM_BD	2
#define e9u_LSMD_EEPROM_DT	3
#define e9u_LSMD_EEPROM_FP	4
#define e9u_LSMD_EEPROM_FW	5
#define e9u_LSMD_EEPROM_WEB	6
#define e9u_LSMD_EEPROM_AUX	7

DLL_API int DLL_CALL e9u_LSMD_SLEEP_ms    (unsigned int ui_ms);
DLL_API int DLL_CALL e9u_LSMD_UART_exists (char* c_devname);
