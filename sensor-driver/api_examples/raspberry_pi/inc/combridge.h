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
 * @file combridge.h
 *
 * @brief Header for the serial communication interface functions in combridge.c.
 */
#ifndef COMBRIDGE_H_
#define COMBRIDGE_H_

#ifdef __cplusplus
extern "C" {
#endif /* __cplusplus */


/* Includes ------------------------------------------------------------------*/
#include <stdint.h>
#include "bmv080.h"

/*********************************************************************************************************************
* Defines / Constants
*********************************************************************************************************************/
/* BMV080 I2C address
 * note that the BMV080 pins are connected such that I2C Address Bit 0 = 0 and I2C Address Bit 1 = 0
 */
#define BMV080_I2C_ADDRESS              0x54
#define BMV080_I2C_BAUDRATE             1000000 // (1MHz)

/*********************************************************************************************************************
* Error codes
*********************************************************************************************************************/
/*!
* @brief Status codes returned by the combridge serial communication interface.
*/
typedef enum
{
    /* Ok ***********************************************************************************************************/

    /*! 0: Default result if there is no warning or error */
	E_COMBRIDGE_OK = 0,

    /* Errors *******************************************************************************************************/

    /*! 10: The endpoint was not initialized */
    E_COMBRIDGE_ERROR_ENDPOINT_NOT_INITIALIZED = 10,
    /*! 15: The endpoint was already initialized */
	E_COMBRIDGE_ERROR_ENDPOINT_ALREADY_INITIALIZED = 15,

    /*! 20: The requested feature is not available */
    E_COMBRIDGE_ERROR_FEATURE_NOT_AVAILABLE = 20,

    /*! 16: The key does not correspond to a supported parameter */
    E_COMBRIDGE_ERROR_PARAMETER_INVALID_KEY = 16,
    /*! 31: The parameter value is invalid, i.e. not supported or out of bounds */
    E_COMBRIDGE_ERROR_PARAMETER_INVALID_VALUE = 31,
    /*! 32: A Null-pointer is passed as parameter */
    E_COMBRIDGE_ERROR_PARAMETER_NULL_POINTER = 32,

    /*! 17: An error happened during the transfer to the endpoint, i.e. package loss */
    E_COMBRIDGE_ERROR_TRANSFER = 17,

    /*! 50: Signaling error regarding interrupts */
    E_COMBRIDGE_ERROR_IRQ = 50,

    /*! 60: Accessing a file, i.e. for logs, failed */
    E_COMBRIDGE_ERROR_FILE_ACCESS = 60,

    /*! 70: An internal error occurred which hints at unexpected issues in the source code */
    E_COMBRIDGE_ERROR_INTERNAL = 70,

    /*! 80: An external library returned an error during a configuration */
    E_COMBRIDGE_ERROR_EXTERNAL_LIB_CONFIG = 80,

    /*! 81: An external library returned an error during communication */
    E_COMBRIDGE_ERROR_EXTERNAL_LIB_COM = 81,

    /*! 13: Permission denied */
    E_COMBRIDGE_SPIDEV_EACCES = 13,

    /*! 14: Bad address */
    E_COMBRIDGE_SPIDEV_EFAULT = 14,

    /*! 4: Interrupted system call */
    E_COMBRIDGE_SPIDEV_EINTR = 4,

    /*! 22: Invalid argument */
    E_COMBRIDGE_SPIDEV_EINVAL = 22,

    /*! 21: Is a directory */
    E_COMBRIDGE_SPIDEV_EISDIR = 21,

    /*! 40: Too many symbolic links encountered */
    E_COMBRIDGE_SPIDEV_ELOOP = 40,

    /*! 24: Too many open files */
    E_COMBRIDGE_SPIDEV_EMFILE = 24,

    /*! 23: File table overflow */
    E_COMBRIDGE_SPIDEV_ENFILE = 23,

    /*! 19: No such device */
    E_COMBRIDGE_SPIDEV_ENODEV = 19,

    /*! 2: No such file or directory */
    E_COMBRIDGE_SPIDEV_ENOENT = 2,

    /*! 12: Out of memory */
    E_COMBRIDGE_SPIDEV_ENOMEM = 12,

    /*! 28: No space left on device */
    E_COMBRIDGE_SPIDEV_ENOSPC = 28,

    /*! 6: No such device or address */
    E_COMBRIDGE_SPIDEV_ENXIO = 6,

    /*! 1: Operation not permitted */
    E_COMBRIDGE_SPIDEV_EPERM = 1,

    /*! 30: Read-only file system */
    E_COMBRIDGE_SPIDEV_EROFS = 30,

    /*! 26: Text file busy */
    E_COMBRIDGE_SPIDEV_ETXTBSY = 26,

    /*! 11: Try again */
    E_COMBRIDGE_SPIDEV_EAGAIN = 11,

    /*! 25: Not a typewriter */
    E_COMBRIDGE_SPIDEV_ENOTTY = 25,

    /*! 9: Bad file number */
    E_COMBRIDGE_SPIDEV_EBADF = 9,

    /*! 102: Address family not supported by protocol */
    E_COMBRIDGE_I2CDEV_EAFNOSUPPORT = 102,

    /*! 74: Bad message */
    E_COMBRIDGE_I2CDEV_EBADMSG = 74,

    /*! 16: Device or resource busy */
    E_COMBRIDGE_I2CDEV_EBUSY = 16,

    /*! 5: Input/output error */
    E_COMBRIDGE_I2CDEV_EIO = 5,

    /*! 95: Operation not supported on transport endpoint */
    E_COMBRIDGE_I2CDEV_EOPNOTSUPP = 94,

    /*! 71: Protocol error */
    E_COMBRIDGE_I2CDEV_EPROTO = 71,

    /*! 110: Connection timed out */
    E_COMBRIDGE_I2CDEV_ETIMEDOUT = 110
} combridge_status_t;

/*!
* @brief Valid SPI modes.
*/
typedef enum
{
	MODE_0 = 0,	/**< data captured on rising edge, propagated on falling */
	MODE_1 = 1,
	MODE_2 = 2,
	MODE_3 = 3	/**< data captured on rising edge, propagated on falling */
}combridge_spi_mode_t;

/* Combridge setup functions - SPI & I2C */
combridge_status_t combridge_spi_init(bmv080_sercom_handle_t* handle, uint32_t channel_index, uint32_t clock_rate_hz, combridge_spi_mode_t spi_mode);
combridge_status_t combridge_i2c_init(bmv080_sercom_handle_t* handle, uint32_t channel_index, uint32_t i2c_addr, uint32_t baud_rate);

/* SPI read and write functions */
combridge_status_t combridge_spi_read_16bit(bmv080_sercom_handle_t handle, uint16_t header, uint16_t *payload, uint16_t payload_length);
combridge_status_t combridge_spi_write_16bit(bmv080_sercom_handle_t handle, uint16_t header, const uint16_t *payload, uint16_t payload_length);

/* I2C read and write functions */
combridge_status_t combridge_i2c_read_16bit(bmv080_sercom_handle_t handle, uint16_t header, uint16_t *payload, uint16_t payload_length);
combridge_status_t combridge_i2c_write_16bit(bmv080_sercom_handle_t handle, uint16_t header, const uint16_t* payload, uint16_t payload_length);

/* Combridge release function */
combridge_status_t combridge_release(bmv080_sercom_handle_t* handle);

/* Combridge delay function */
int8_t combridge_delay(uint32_t period);

/* Get tick function */
uint32_t combridge_get_tick(void);

#ifdef __cplusplus
}
#endif

#endif /* COMBRIDGE_H_ */
