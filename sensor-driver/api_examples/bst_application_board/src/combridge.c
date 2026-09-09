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
 * @file combridge.c
 *
 * @brief This file contains the serial communication interface (e.g. SPI and I2C) functions. 
 * Messages can be read and written. In addition, there is a waiting mechanism that waits for a defined time.
 */


#include <stdio.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include "combridge.h"

/******************************************************************************/
/*!                 Macro definitions                                         */

/*! Macro that defines read write length */
#define BMV080_I2C_ADDRESS          0x54
#define BMV080_SHUTTLE_ID           UINT16_C(0x197)
#define COINES_API_VERSION          "v2.10"
#define APP31_BOARD_IDENTIFIER      UINT8_C(9)

/******************************************************************************/
/*!                Static variable definition                                 */

/*! Variable that holds the I2C device address or SPI chip selection */
static uint8_t dev_addr;

/*! Variable that holds the I2C or SPI bus instance */
static uint8_t bus_inst;

/******************************************************************************/
/*!                User interface functions                                   */

/*!
 * I2C read function map to COINES platform
 */
int8_t bmv080_i2c_read(bmv080_sercom_handle_t handle, uint16_t header, uint16_t *payload, uint16_t payload_length)
{
    int8_t return_value;
    struct coines_intf_config intf_info = *(struct coines_intf_config *)handle;
    uint16_t header_adjusted = header << 1;
    return_value = coines_read_16bit_i2c(intf_info.bus, intf_info.dev_addr, header_adjusted, payload, payload_length, COINES_I2C_TRANSFER_16BIT);

    return return_value;
}

/*!
 * I2C write function map to COINES platform
 */
int8_t bmv080_i2c_write(bmv080_sercom_handle_t handle, uint16_t header, const uint16_t *payload, uint16_t payload_length)
{
    int8_t return_value;
    struct coines_intf_config intf_info = *(struct coines_intf_config *)handle;
    uint16_t header_adjusted = header << 1;
    return_value = coines_write_16bit_i2c(intf_info.bus, intf_info.dev_addr, header_adjusted, payload, payload_length, COINES_I2C_TRANSFER_16BIT);
    return return_value;
}

/*!
 * SPI read function map to COINES platform
 */
int8_t bmv080_spi_read(bmv080_sercom_handle_t handle, uint16_t header, uint16_t *payload, uint16_t payload_length)
{
    struct coines_intf_config intf_info = *(struct coines_intf_config *)handle;
    return coines_read_16bit_spi(intf_info.bus, intf_info.dev_addr, header, payload, payload_length, COINES_SPI_TRANSFER_16BIT);
}

/*!
 * SPI write function map to COINES platform
 */
int8_t bmv080_spi_write(bmv080_sercom_handle_t handle, uint16_t header, const uint16_t *payload, uint16_t payload_length)
{
    struct coines_intf_config intf_info = *(struct coines_intf_config *)handle;
    return coines_write_16bit_spi(intf_info.bus, intf_info.dev_addr, header, payload, payload_length, COINES_SPI_TRANSFER_16BIT);
}

/*!
 * Delay function map to COINES platform
 */
int8_t bmv080_delay_ms(uint32_t period)
{
    coines_delay_msec(period);
    return E_BMV080_OK;
}

/*!
 * Delay function map to COINES platform
 */
uint32_t bmv080_get_tick(void)
{
    return coines_get_millis();
}

/*!
 *  @brief Function to initialize coines platform
 */
int16_t coines_board_init(enum coines_comm_intf intf_type, bool get_board_info)
{
    struct coines_board_info board_info;

    int16_t result = coines_open_comm_intf(intf_type, NULL);

    if (result < COINES_SUCCESS)
    {
        printf(
            "\n Unable to connect with Application Board ! \n" 
            " 1. Check if the board is connected and powered on. \n" 
            " 2. Check if Application Board USB driver is installed. \n"
            " 3. Check if board is in use by another application. (Insufficient permissions to access USB) \n");
        exit(result);
    }

    if (get_board_info)
    {
        result = coines_get_board_info(&board_info);

#if defined(PC)
        setbuf(stdout, NULL);
#endif

        if (result == COINES_SUCCESS)
        {
            /* Get BST application board version */
            if ((board_info.board != APP31_BOARD_IDENTIFIER))
            {
                printf("Error: unsupported application board version\n");
                result = COINES_E_DEVICE_NOT_FOUND;
            }

            if ((board_info.shuttle_id != BMV080_SHUTTLE_ID))
            {
                printf("Error: unsupported sensor shuttle board\n");
                result = COINES_E_NOT_SUPPORTED;
            }
        }
    }
    coines_delay_msec(100);


    return result;
}

/*!
 *  @brief Function to select the interface between SPI and I2C.
 */
int8_t bmv080_interface_init(struct coines_intf_config* intf_info, uint8_t intf)
{
    int8_t rslt = E_COMBRIDGE_OK;

    /* Set true to get board info */
    int16_t result = coines_board_init(COINES_COMM_INTF_USB, true);

    if (result != COINES_SUCCESS)
    {
        printf("\nError: Unable to open device\n");

        return E_COMBRIDGE_UNABLE_OPEN_DEVICE;
    }

    /* Get COINES_API version */
    if(strstr(coines_get_version(), COINES_API_VERSION) == NULL)
    {
        printf("\nWarning: untested COINES API version\n");
    }

    /* Bus configuration : I2C */
    if (intf == BMV080_I2C_INTF)
    {
        printf("I2C Interface\n");

        /* To initialize the user I2C function */
        dev_addr = BMV080_I2C_ADDRESS;

        /*set PS to High to select I2C */
        coines_set_pin_config(COINES_MINI_SHUTTLE_PIN_1_4, COINES_PIN_DIRECTION_OUT, COINES_PIN_VALUE_HIGH);
        /*set CSB and MISO to low for 0x54 I2C address */
        coines_set_pin_config(COINES_MINI_SHUTTLE_PIN_2_1, COINES_PIN_DIRECTION_OUT, COINES_PIN_VALUE_LOW);
        coines_set_pin_config(COINES_MINI_SHUTTLE_PIN_2_3, COINES_PIN_DIRECTION_OUT, COINES_PIN_VALUE_LOW);
        /* Power up the board */
        coines_set_shuttleboard_vdd_vddio_config(3300, 3300);
        coines_delay_msec(200);
        result = coines_config_i2c_bus(COINES_I2C_BUS_0, COINES_I2C_STANDARD_MODE);
        bus_inst = COINES_I2C_BUS_0;
    }
    /* Bus configuration : SPI */
    else if (intf == BMV080_SPI_INTF)
    {
        printf("SPI Interface\n");
        /*set PS to Low to select SPI */
         coines_set_pin_config(COINES_MINI_SHUTTLE_PIN_1_4, COINES_PIN_DIRECTION_OUT, COINES_PIN_VALUE_LOW);
        /* Power up the board */
        coines_set_shuttleboard_vdd_vddio_config(3300, 3300);
        coines_delay_msec(200);
        /* To initialize the user SPI function */
        dev_addr = COINES_MINI_SHUTTLE_PIN_2_1;
        result = coines_config_spi_bus(COINES_SPI_BUS_0, COINES_SPI_SPEED_1_MHZ, COINES_SPI_MODE0);
        coines_set_pin_config(COINES_MINI_SHUTTLE_PIN_2_1, COINES_PIN_DIRECTION_OUT, COINES_PIN_VALUE_HIGH);
        bus_inst = COINES_SPI_BUS_0;
    }

    if (COINES_SUCCESS == result)
    {
        /* Assign device address and bus instance to interface pointer */
        intf_info->bus = bus_inst;
        intf_info->dev_addr = dev_addr;
    }
    else
    {
        rslt = E_COMBRIDGE_ERROR_UNABLE_CLAIM_INTF;
    }

    return rslt;
}


/*!
 *  @brief De-initializes coines platform
 *
 *  @return void.
 */
void coines_board_deinit(void)
{
    fflush(stdout);
    coines_set_shuttleboard_vdd_vddio_config(0, 0);
    coines_delay_msec(100);

    /* Coines interface reset */
    coines_soft_reset();
    coines_delay_msec(100);
    coines_close_comm_intf(COINES_COMM_INTF_USB, NULL);
}
