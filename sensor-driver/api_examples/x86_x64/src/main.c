/**
 * Copyright (C) Bosch Sensortec GmbH. All Rights Reserved. Confidential.
 *
 * Disclaimer
 *
 * Common:
 * Bosch Sensortec products are developed for the consumer goods industry. They may only be used
 * within the parameters of the respective valid product data sheet. Bosch Sensortec products are
 * provided with the express understanding that there is no warranty of fitness for a particular purpose.
 * They are not fit for use in life-sustaining, safety or security sensitive systems or any system or device
 * that may lead to bodily harm or property damage if the system or device malfunctions. In addition,
 * Bosch Sensortec products are not fit for use in products which interact with motor vehicle systems.
 * The resale and/or use of products are at the purchaser's own risk and his own responsibility. The
 * examination of fitness for the intended use is the sole responsibility of the Purchaser.
 *
 * The purchaser shall indemnify Bosch Sensortec from all third party claims, including any claims for
 * incidental, or consequential damages, arising from any product use not covered by the parameters of
 * the respective valid product data sheet or not approved by Bosch Sensortec and reimburse Bosch
 * Sensortec for all costs in connection with such claims.
 *
 * The purchaser must monitor the market for the purchased products, particularly with regard to
 * product safety and inform Bosch Sensortec without delay of all security relevant incidents.
 *
 * Engineering Samples are marked with an asterisk (*) or (e). Samples may vary from the valid
 * technical specifications of the product series. They are therefore not intended or fit for resale to third
 * parties or for use in end products. Their sole purpose is internal client testing. The testing of an
 * engineering sample may in no way replace the testing of a product series. Bosch Sensortec
 * assumes no liability for the use of engineering samples. By accepting the engineering samples, the
 * Purchaser agrees to indemnify Bosch Sensortec from all claims arising from the use of engineering
 * samples.
 *
 * Special:
 * This software module (hereinafter called "Software") and any information on application-sheets
 * (hereinafter called "Information") is provided free of charge for the sole purpose to support your
 * application work. The Software and Information is subject to the following terms and conditions:
 *
 * The Software is specifically designed for the exclusive use for Bosch Sensortec products by
 * personnel who have special experience and training. Do not use this Software if you do not have the
 * proper experience or training.
 *
 * This Software package is provided `` as is `` and without any expressed or implied warranties,
 * including without limitation, the implied warranties of merchantability and fitness for a particular
 * purpose.
 *
 * Bosch Sensortec and their representatives and agents deny any liability for the functional impairment
 * of this Software in terms of fitness, performance and safety. Bosch Sensortec and their
 * representatives and agents shall not be liable for any direct or indirect damages or injury, except as
 * otherwise stipulated in mandatory applicable law.
 *
 * The Information provided is believed to be accurate and reliable. Bosch Sensortec assumes no
 * responsibility for the consequences of use of such Information nor for any infringement of patents or
 * other rights of third parties which may result from its use. No license is granted by implication or
 * otherwise under any patent or patent rights of Bosch. Specifications mentioned in the Information are
 * subject to change without notice.
 *
 * It is not allowed to deliver the source code of the Software to any third party without permission of
 * Bosch Sensortec.
 *
 * @file main.c
 *
 * @brief Example application demonstrating how to execute a particle measurement with a BMV080 sensor unit.
 *
 *
 */

#include <stdint.h>
#include <stdio.h>
#include <string.h>

 /* The BMV080 sensor driver usage example header */
#include "bmv080_example.h"

/* The BMV080 sensor driver requires a serial communication (sercom) for interacting with the BMV080 sensor unit.
 * This SDK uses an exemplary implementation of a sercom interface called "combridge".
 * Code regarding this exemplary implementation is marked and not relevant to other implementations.
 * Actual applications should provide their own sercom implementation tailored to their specific needs. */
#include "combridge_defs.h"
#include "combridge.h"


int main()
{
    /* Combridge only: All combridge functions returns status codes and use a unique handle. */
    combridge_status_t combridge_current_status = E_COMBRIDGE_OK;

    /* The return value of this main function will be overwritten by the first not-okay status */
    combridge_status_t combridge_final_status = combridge_current_status;

    bmv080_sercom_handle_t combridge_handle = NULL;

    /* Combridge only: Initialize a serial communication to a FTDI FT4222 device */
    uint32_t num_channels = 0;
    char* channel_id = { "default" };
    char** channel_ids = &channel_id;
    combridge_current_status = combridge_initialize(&num_channels, &channel_ids);
    if (combridge_current_status != E_COMBRIDGE_OK)
    {
        printf("Initializing a serial communication failed with combridge status %d\n", (int)combridge_current_status);
        UPDATE_OPERATION_STATUS(combridge_final_status, combridge_current_status);
        goto exit;
    }


    /* Combridge only: Open a channel via this serial communication interface */
    uint32_t channel_index = 0;
    uint32_t clock_rate_in_hz = 10000000;
    combridge_spi_mode_t spi_mode = MODE_0;
    combridge_current_status = combridge_setup(&combridge_handle, channel_index, clock_rate_in_hz, spi_mode);
    if (combridge_current_status != E_COMBRIDGE_OK)
    {
        printf("Setting up a serial communication failed with combridge status %d\n", (int)combridge_current_status);
        UPDATE_OPERATION_STATUS(combridge_final_status, combridge_current_status);
        goto combridge_terminate;
    }

    /* Sensor API execution */
    bmv080_status_code_t bmv080_final_status = bmv080(combridge_handle,
        (const bmv080_callback_read_t)combridge_read_16bit,
        (const bmv080_callback_write_t)combridge_write_16bit,
        (const bmv080_callback_delay_t)combridge_delay,
        (const bmv080_callback_tick_t)combridge_get_tick,
        (const print_function_t)printf,
        ( (const enable_ext_interrupt_function_t) NULL) );
    if (bmv080_final_status != E_BMV080_OK)
    {
        printf("Executing the sensor APIs failed with bmv080 status %d\n", (int)bmv080_final_status);
    }

    /* Combridge only: A setup combridge channel must be released */
    combridge_current_status = combridge_release(&combridge_handle);
    if (combridge_current_status != E_COMBRIDGE_OK)
    {
        printf("Releasing the serial communication failed with combridge status %d\n", (int)combridge_current_status);
        UPDATE_OPERATION_STATUS(combridge_final_status, combridge_current_status);
    }

combridge_terminate:
    /*  Combridge only: An initialized combridge must be terminated */
    combridge_current_status = combridge_terminate();
    if (combridge_current_status != E_COMBRIDGE_OK)
    {
        printf("Terminating the serial communication failed with combridge status %d\n", (int)combridge_current_status);
        UPDATE_OPERATION_STATUS(combridge_final_status, combridge_current_status);
    }

exit:
    return (int)combridge_final_status;
}
