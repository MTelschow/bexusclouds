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
 */

/* Includes ------------------------------------------------------------------*/
#include <stdio.h>
#include <string.h>
#include <ctype.h>
#include "bmv080_example.h"
#include "combridge.h"

/* Private define ------------------------------------------------------------*/
#define SPI (1)
#define I2C (2)

/* Private macro -------------------------------------------------------------*/

/* Private variables ---------------------------------------------------------*/

/* Private function prototypes -----------------------------------------------*/


/* Private user code ---------------------------------------------------------*/
/*! 
* @brief ISR for external interrupt from BMV080
*
* This routine will be called whenever the BMV080 toggles the interrupt line
* to indicate that new data is available.
* As long as the interrupt line is low there is data available that needs to be processed.
*/

/**
 * @brief  The application entry point.
 * @retval int
 */
int main(void)
{
    struct coines_intf_config intf_info;

    int8_t rslt = E_COMBRIDGE_OK;
#if HOST_INTERFACE == SPI
    rslt = bmv080_interface_init(&intf_info, BMV080_SPI_INTF);
#elif HOST_INTERFACE == I2C
    rslt = bmv080_interface_init(&intf_info, BMV080_I2C_INTF);
#else
    rslt = E_COMBRIDGE_ERROR_UNKNOWN_HOST_INTF;
    #error "Unknown host interface. Supported host communication interfaces are SPI and I2C."
#endif

    if(rslt != E_COMBRIDGE_OK)
    {
        return E_COMBRIDGE_ERROR_INIT_FAILED;
    }

    /* Sensor API execution */
    bmv080_status_code_t bmv080_final_status = bmv080(
#if HOST_INTERFACE == SPI
                    (bmv080_sercom_handle_t)&intf_info,
                    (const bmv080_callback_read_t)bmv080_spi_read,
                    (const bmv080_callback_write_t)bmv080_spi_write,
#elif HOST_INTERFACE == I2C
                    (bmv080_sercom_handle_t)&intf_info,
                    (const bmv080_callback_read_t)bmv080_i2c_read,
                    (const bmv080_callback_write_t)bmv080_i2c_write,
#else
    #error "Unknown host interface. Supported host communication interfaces are SPI and I2C."
#endif 
                    (const bmv080_callback_delay_t)bmv080_delay_ms,
                    (const bmv080_callback_tick_t)bmv080_get_tick,
                    (const print_function_t)printf,
                    NULL);

    if (bmv080_final_status != E_BMV080_OK)
    {
        printf("Executing the sensor APIs failed with bmv080 status %d\n", (int)bmv080_final_status);
    }

    while (1)
    {

    }
}


