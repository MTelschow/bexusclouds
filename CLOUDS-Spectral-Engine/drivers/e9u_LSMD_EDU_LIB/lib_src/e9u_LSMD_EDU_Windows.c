/*
    EURECA's e9u_LSMD_EDU camera software – connect to a e9u_LSMD_EDU camera USB module
    Copyright (C) 2020 -2025 Eureca Messtechnik GmbH, <info@eureca.de>

    This file is part of EURECA's e9u_LSMD_EDU camera software.

    EURECA's e9u_LSMD_EDU camera software is free software: you can redistribute
    it and/or modify it under the terms of the GNU Lesser General Public
    License as published by the Free Software Foundation, either
    version 3 of the License, or (at your option) any later version.

    EURECA's e9u_LSMD_EDU_EUD camera software is distributed in the hope that it
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

    EURECAs e9u_LSMD_EDU_EUD Kamera-Software wird in der Hoffnung, dass es nützlich
    sein wird, aber OHNE JEDE GEWÄHRLEISTUNG, bereitgestellt; sogar ohne
    die implizite Gewährleistung der MARKTFÄHIGKEIT oder EIGNUNG FÜR
    EINEN BESTIMMTEN ZWECK.  Siehe die GNU General Public License für
    weitere Details.

    Sie sollten eine Kopie der GNU General Public License zusammen mit diesem
    Programm erhalten haben. Wenn nicht, siehe <https://www.gnu.org/licenses/>.

*/


// for API documentation comments see the function declarations in e9u_LSMD_EDU.h


#ifdef _WIN32

// include for Windows
#include <windows.h>

// include for "printf"
#include <stdio.h>

// include for fixed length integer
#include <stdint.h>

// include for "memset" and "strlen"
#include <string.h>

// include for "clock_gettime"
#include <time.h>

//#include <iostream.h>
//#include <synchapi.h>

#include "e9u_LSMD_EDU_defs.h"
#include "e9u_LSMD_EDU_interface.h"


// sleep in [ms]
int DLL_CALL e9u_LSMD_EDU_SLEEP_ms (unsigned int ui_ms)
{
    Sleep (ui_ms);
    return (e9u_LSMD_EDU_OK);
}




// test, if device exists:
/** @brief Test whether the device exists.
 * @param[in] c_devname the device's name
 * 
 * @todo Was sind mögliche Rückgabe-Werte?
 * @todo Gibt es einen Grund, warum hier der Return-Wert von 0 statt #e9u_LSMD_EDU_OK steht?
 */
int DLL_CALL e9u_LSMD_EDU_UART_exists (char* c_devname)
{
e9u_LSMD_EDU_TTY_HANDLE h_ttyUSB;

// open UART to test, if exists:
    h_ttyUSB = CreateFileA (c_devname,
                             GENERIC_READ | GENERIC_WRITE,
                             0,                          // no share
                             NULL,                       // no security
                             OPEN_EXISTING,
                             FILE_FLAG_NO_BUFFERING | FILE_FLAG_WRITE_THROUGH, // no threads
                             NULL);                      // no templates


    if (h_ttyUSB == INVALID_HANDLE_VALUE)
        return (-1);
    
// close UART:
    CloseHandle(h_ttyUSB);
 
    return (0);
}




/** @brief Open the UART.
 * @param[out] h_ttyUSB handle to the UART once it's opened
 * @param[in] c_devname device name as file name
 * @returns #e9u_LSMD_EDU_OK in case of success, #e9u_LSMD_EDU_ERROR_OPEN in case of any problems
 */
int e9u_LSMD_EDU_UART_open(e9u_LSMD_EDU_TTY_HANDLE *h_ttyUSB, char* c_devname, int i_USB)
{

DCB          dcb_SerialParams;     // DCB structure
COMMTIMEOUTS comm_timeouts;        // Time out structure

// open UART:
    *h_ttyUSB = CreateFileA (c_devname,
                             GENERIC_READ | GENERIC_WRITE,
                             0,                          // no share
                             NULL,                       // no security
                             OPEN_EXISTING,
                             FILE_FLAG_NO_BUFFERING | FILE_FLAG_WRITE_THROUGH, // no threads
                             NULL);                      // no templates

    if (*h_ttyUSB == INVALID_HANDLE_VALUE) {
        printf("Error int CreateFileA\n");
        return (e9u_LSMD_EDU_FAIL);
    }

    LockFile (*h_ttyUSB, 0, 0, 1, 1);

// set buffer size:
    SetupComm (*h_ttyUSB, 4096, 4096);

// initialize serial parameter structure:
    memset (&dcb_SerialParams, 0, sizeof (dcb_SerialParams));
    dcb_SerialParams.DCBlength = sizeof (dcb_SerialParams);
    if (GetCommState (*h_ttyUSB, &dcb_SerialParams) == FALSE) { //retreives  the current settings
        printf("Error in GetCommState\n");
        return (e9u_LSMD_EDU_FAIL);
    }

// set serial parameters:
//    dcb_SerialParams.BaudRate = 916200;                 // Setting BaudRate

    if (i_USB == 1)
        dcb_SerialParams.BaudRate = 3000000;                 // Setting BaudRate maximum supported by FT231 is 3 MBaud
    else
        dcb_SerialParams.BaudRate = 2000000;                 // Maximum for UART

    dcb_SerialParams.ByteSize = 8;                      // Setting ByteSize = 8
    dcb_SerialParams.StopBits = ONESTOPBIT;             // Setting StopBits = 1
    dcb_SerialParams.Parity = NOPARITY;                 // Setting Parity = None
    dcb_SerialParams.fOutxCtsFlow = TRUE;                    // CTS used for output flow control
    dcb_SerialParams.fRtsControl = RTS_CONTROL_HANDSHAKE;    // Enable RTS 

    if (SetCommState(*h_ttyUSB, &dcb_SerialParams) == FALSE) {  //Configuring the port according to settings in DCB 
        printf("Error in Setting DCB Structure\n");
        return (e9u_LSMD_EDU_FAIL);
    }

// initialize serial timeout structure:
    memset(&comm_timeouts, 0, sizeof(comm_timeouts));
    comm_timeouts.ReadIntervalTimeout         = 1500;
    comm_timeouts.ReadTotalTimeoutConstant    = 0;
    comm_timeouts.ReadTotalTimeoutMultiplier  = 0;
    comm_timeouts.WriteTotalTimeoutConstant   = 0;
    comm_timeouts.WriteTotalTimeoutMultiplier = 0;

// set serial timeouts:
    if (SetCommTimeouts(*h_ttyUSB, &comm_timeouts) == FALSE) {
        printf("Error in Setting Time Outs\n");
        return (e9u_LSMD_EDU_FAIL);
    }
    
//    SetPriorityClass (GetCurrentProcess(), REALTIME_PRIORITY_CLASS);
    SetPriorityClass (GetCurrentProcess(), HIGH_PRIORITY_CLASS);
    return (e9u_LSMD_EDU_OK);
}



/** @brief Close the UART.
 * @param[in] h_ttyUSB handle to the UART
 * @returns #e9u_LSMD_EDU_OK.
 */
int e9u_LSMD_EDU_UART_close(e9u_LSMD_EDU_TTY_HANDLE h_ttyUSB)
{
    UnlockFile (h_ttyUSB, 0, 0, 1, 1);
    CloseHandle(h_ttyUSB);
    return (e9u_LSMD_EDU_OK);
}



/** @brief Send bytes to the e9u_LSMD_EDU device.
 *
 *  This funktion replaces the "normal" write by a function which guarantees
 *  that all data are written and which is independent of buffer size.
 *  @param[in] h_ttyUSB handle to the e9u_LSMD_EDU device
 *  @param[in] c_buffer buffer containing the bytes to be sent
 *  @param[in] sz_count number of bytes to be sent
 *  @param[out] sz_written upon exit, this parameter contains the number of bytes sent
 *  @returns #e9u_LSMD_EDU_OK upon success, #e9u_LSMD_EDU_TIMEOUT_WRITE if a timeout occurs, #e9u_LSMD_EDU_ERROR_WRITE in case of any other write errors
 *
 *  @todo kann man den Timeout setzen? Der war mal hier Parameter...
 */
int e9u_LSMD_EDU_UART_write(e9u_LSMD_EDU_TTY_HANDLE h_ttyUSB, char* c_buffer, size_t sz_count, size_t* sz_written)
{
BOOL  b_Status;
DWORD dw_bytes;
DWORD dw_total;
DWORD dw_package;
DWORD dw_transfered;

    dw_transfered = 0;
    dw_total = sz_count;
    do {
        dw_package = dw_total - dw_transfered;
        if (dw_package > 256)
            dw_package = 256;

        b_Status = WriteFile (h_ttyUSB,                 // Handle to the Serialport
                              c_buffer + dw_transfered,	// Data to be written to the port 
                              dw_total,                 // No of bytes to be writen to the port
                              &dw_bytes,                // real No of bytes written to the port
                              NULL);
        dw_transfered += dw_bytes;
        *sz_written = dw_transfered;

        if (b_Status == FALSE)
            return (e9u_LSMD_EDU_FAIL);

        if (dw_bytes == 0)
            return (e9u_LSMD_EDU_TIMEOUT);

    } while (dw_transfered < dw_total);
    
    return (e9u_LSMD_EDU_OK);
}



/** @brief Receive bytes from the e9u_LSMD_EDU device.
 *
 *  This funktion replaces the "normal" read by a function which guarantees
 *  that all data are received and which is independent of buffer size.
 *  @param[in]  h_ttyUSB handle to the e9u_LSMD_EDU device
 *  @param[out] c_buffer buffer which will receive the bytes received
 *  @param[in] sz_count number of bytes to be received
 *  @param[out] sz_read upon exit, this parameter contains the number of bytes received
 *  @returns #e9u_LSMD_EDU_OK upon success, #e9u_LSMD_EDU_TIMEOUT_READ if a timeout occurs, #e9u_LSMD_EDU_ERROR_READ in case of any other read errors
 *
 *  @todo kann man den Timeout setzen? Der war mal hier Parameter...
 */
int e9u_LSMD_EDU_UART_read(e9u_LSMD_EDU_TTY_HANDLE h_ttyUSB, char* c_buffer, size_t sz_count, size_t* sz_read)
{
BOOL  b_Status;
DWORD dw_bytes;
DWORD dw_total;
DWORD dw_package;
DWORD dw_transfered;

    dw_transfered = 0;
    dw_total = sz_count;
    do {
        dw_package = dw_total - dw_transfered;
        if (dw_package > 256)
            dw_package = 256;
        b_Status = ReadFile (h_ttyUSB, 
                             c_buffer + dw_transfered, 
                             dw_package, 
                             &dw_bytes, 
                             NULL);
        dw_transfered += dw_bytes;
        *sz_read = dw_transfered;
        
        if (b_Status == FALSE)
            return (e9u_LSMD_EDU_FAIL);

        if (dw_bytes == 0)
            return (e9u_LSMD_EDU_TIMEOUT);

    } while (dw_transfered < dw_total);

    return (e9u_LSMD_EDU_OK);
}



/** @brief Flush all data from the device's buffers.
 * @param[in] h_ttyUSB handle to the device
 * @returns #e9u_LSMD_EDU_OK
 */
int e9u_LSMD_EDU_UART_flush (e9u_LSMD_EDU_TTY_HANDLE h_ttyUSB)
{
    // wait until data are written to camera:
    FlushFileBuffers (h_ttyUSB);

    // flush input buffers a second time:
    // the camera still sends up to 16 KiB of data from internal fifo,
    // this is up to fife times the buffer size:
    Sleep (10);                                        // give the camera time to fill the buffer
    PurgeComm (h_ttyUSB, PURGE_TXCLEAR | PURGE_RXCLEAR); // flush all input buffers, if not empty
    Sleep (10);
    PurgeComm (h_ttyUSB, PURGE_TXCLEAR | PURGE_RXCLEAR);
    Sleep (10);
    PurgeComm (h_ttyUSB, PURGE_TXCLEAR | PURGE_RXCLEAR);
    Sleep (10);
    PurgeComm (h_ttyUSB, PURGE_TXCLEAR | PURGE_RXCLEAR);
    Sleep (10);
    PurgeComm (h_ttyUSB, PURGE_TXCLEAR | PURGE_RXCLEAR);
    
    return (e9u_LSMD_EDU_OK);
}




/** @brief Send a break via serial port
 * @param[in] h_ttyUSB handle to the device
 * @returns #e9u_LSMD_EDU_OK
 */
int e9u_LSMD_EDU_UART_sendbreak (e9u_LSMD_EDU_TTY_HANDLE h_ttyUSB)
{
    SetCommBreak (h_ttyUSB);
    Sleep (200);
    ClearCommBreak (h_ttyUSB);
    
    return (e9u_LSMD_EDU_OK);
}

#endif // ifdef _WIN32
