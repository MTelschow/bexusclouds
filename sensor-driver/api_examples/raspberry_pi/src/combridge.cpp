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
 * @file combridge.cpp
 *
 * @brief This file contains the serial communication interface (e.g. SPI and I2C) functions. 
 * Messages can be read and written. In addition, there is a waiting mechanism that waits for a defined time.
 */


/* Includes ------------------------------------------------------------------*/
#include <stdlib.h>
#include <string>
#include <vector>
#include <chrono>
#include <stdio.h>
#include <stdlib.h>
#include <fcntl.h>
#include <errno.h>
#include <unistd.h>
#include <sys/ioctl.h>
#include <linux/spi/spidev.h>
#include <linux/i2c-dev.h>
#include <linux/i2c.h>

#include "combridge.h"

using namespace std;


/*****************************************************************************************/
#define BITS_PER_WORD                   8u
#define MAX_TX_RX_BYTES                 2048u
#define REG_ADDR_HEADER_SIZE            2u
#define MICROSECONDS_TO_MILLISECONDS    1000u
#define I2C_READ_NUM_MESSAGES           2
#define I2C_WRITE_NUM_MESSAGES          1

/*****************************************************************************************/
/* file descriptor for spi */
static int spi_handle = 0;
static int i2c_handle = 0;

/* flag to monitor current status of spi & i2c file descriptor */
static bool is_spi_initialized = false;
static bool is_i2c_initialized = false;

/* SPI structure passed to ioctl of linux kernel */
static struct spi_ioc_transfer spi_ioctl;

/* enum to hold current mode of spi */
static combridge_spi_mode_t _spi_mode;

/*****************************************************************************************/
/* Translate error-codes from <errno.h> into corresponding combridge_status_t (SPI) enumeration values */
static combridge_status_t process_spi_dev_error_codes(int error_code);

/* Translate error-codes from <errno.h> into corresponding combridge_status_t (I2C) enumeration values */
static combridge_status_t process_i2c_dev_error_codes(int error_code);

/*****************************************************************************************/
combridge_status_t combridge_i2c_init(bmv080_sercom_handle_t* handle, uint32_t channel_index, uint32_t i2c_addr, uint32_t baud_rate) {

    if (handle == nullptr)
    {
        return E_COMBRIDGE_ERROR_PARAMETER_NULL_POINTER;
    }

    if (is_i2c_initialized)
    {
        return E_COMBRIDGE_ERROR_ENDPOINT_ALREADY_INITIALIZED;
    }

    string i2cdev_string = "/dev/i2c-";
    i2cdev_string += to_string((uint8_t)channel_index);

    /* Open the I2C device */
    i2c_handle = open(i2cdev_string.c_str(), O_RDWR);
    if (i2c_handle < 0)
    {
        return process_i2c_dev_error_codes(errno);
    }

    /* Set the I2C slave address */
    if (ioctl(i2c_handle, I2C_SLAVE, i2c_addr) < 0) 
    {
        close(i2c_handle);
        return process_i2c_dev_error_codes(errno);
    }

    *handle = (bmv080_sercom_handle_t)&i2c_handle;
    is_i2c_initialized = true;
    return E_COMBRIDGE_OK;
}

combridge_status_t combridge_spi_init(bmv080_sercom_handle_t* handle, uint32_t channel_index, uint32_t clock_rate_hz,
    combridge_spi_mode_t spi_mode)
{
    if (handle == nullptr)
    {
        return E_COMBRIDGE_ERROR_PARAMETER_NULL_POINTER;
    }

    if (is_spi_initialized)
    {
        return E_COMBRIDGE_ERROR_ENDPOINT_ALREADY_INITIALIZED;
    }

    uint8_t bits = BITS_PER_WORD;
    _spi_mode = spi_mode;
    string spidev_string = "/dev/spidev";

    spidev_string += to_string((uint8_t)channel_index>>8);
    spidev_string += ".";
    spidev_string += to_string((uint8_t)channel_index);

    spi_handle = open(spidev_string.c_str(), O_RDWR);
    if (spi_handle < 0)
    {
        return process_spi_dev_error_codes(errno);
    }

    /* Bits per word */
    if (ioctl(spi_handle, SPI_IOC_WR_BITS_PER_WORD, &bits) == -1)
    {
        return process_spi_dev_error_codes(errno);
    }

    /* Clock speed */
    if (ioctl(spi_handle, SPI_IOC_WR_MAX_SPEED_HZ, &clock_rate_hz) == -1)
    {
        return process_spi_dev_error_codes(errno);
    }

    /* SPI mode */
    if (ioctl(spi_handle, SPI_IOC_WR_MODE, &spi_mode) == -1)
    {
        return process_spi_dev_error_codes(errno);
    }

    spi_ioctl.speed_hz = clock_rate_hz;
    spi_ioctl.bits_per_word = bits;

    *handle = (bmv080_sercom_handle_t)&spi_handle;
    is_spi_initialized = true;
    return E_COMBRIDGE_OK;
}

/*****************************************************************************************/
combridge_status_t combridge_spi_read_16bit(bmv080_sercom_handle_t handle, uint16_t header, uint16_t* payload, uint16_t payload_length)
{
    if (!is_spi_initialized)
    {
        return E_COMBRIDGE_ERROR_ENDPOINT_NOT_INITIALIZED;
    }

    if ((handle == nullptr) || (payload == nullptr))
    {
        return E_COMBRIDGE_ERROR_PARAMETER_NULL_POINTER;
    }

    if ((payload_length == 0) || (MAX_TX_RX_BYTES < (payload_length * 2)))
    {
        return E_COMBRIDGE_ERROR_PARAMETER_INVALID_VALUE;
    }

    uint8_t spi_buffer[REG_ADDR_HEADER_SIZE + (payload_length * 2)] = {0};
    uint16_t tx_rx_length = static_cast<uint16_t>(REG_ADDR_HEADER_SIZE + (payload_length * 2));

    // Swap byte positions for header
    spi_buffer[0] = static_cast<uint8_t>((header & 0xFF00) >> 8);
    spi_buffer[1] = static_cast<uint8_t>((header) & 0x00FF);
    // Single buffer for tranfer, first two bytes contain the header 
    // information, the rest of the buffer will be used for receiving data
    spi_ioctl.tx_buf = (unsigned long)&spi_buffer;
    spi_ioctl.rx_buf = (unsigned long)&spi_buffer;
    spi_ioctl.len = tx_rx_length;

    if (ioctl(*static_cast<int*>(handle), SPI_IOC_MESSAGE(1), &spi_ioctl) == -1)
    {
        return process_spi_dev_error_codes(errno);
    }

    // Swap byte positions for payload
    for (uint16_t i = 0, j = 2; i < payload_length; i++, j = j + 2)
    {
        // Set initial value to zero before bit manipulation.
        payload[i] = 0;
        payload[i] = ((spi_buffer[j] << 8) & 0xFF00);
        payload[i] = (payload[i] | (spi_buffer[j + 1] & 0x00FF));
    }

    return E_COMBRIDGE_OK;
}

/*****************************************************************************************/
combridge_status_t combridge_spi_write_16bit(bmv080_sercom_handle_t handle, uint16_t header, const uint16_t* payload, uint16_t payload_length)
{
    if (!is_spi_initialized)
    {
        return E_COMBRIDGE_ERROR_ENDPOINT_NOT_INITIALIZED;
    }

    if ((handle == nullptr) || (payload == nullptr))
    {
        return E_COMBRIDGE_ERROR_PARAMETER_NULL_POINTER;
    }

    if ((payload_length == 0) || (MAX_TX_RX_BYTES < (payload_length * 2)))
    {
        return E_COMBRIDGE_ERROR_PARAMETER_INVALID_VALUE;
    }

    uint8_t tx_buf[REG_ADDR_HEADER_SIZE + (payload_length * 2)] = { 0 };
    uint16_t tx_length = static_cast<uint16_t>(REG_ADDR_HEADER_SIZE + (payload_length * 2));

    // Swap byte positions for header
    tx_buf[0] = (header & 0xFF00) >> 8;
    tx_buf[1] = (header) & 0x00FF;

    // Swap byte positions for payload
    for (uint16_t i = 0, j = 2; i < payload_length; i++, j = j + 2)
    {
        tx_buf[j] = (payload[i] & 0xFF00) >> 8;
        tx_buf[j + 1] = (payload[i]) & 0x00FF;
    }

    spi_ioctl.rx_buf = (unsigned long)NULL;
    spi_ioctl.tx_buf = (unsigned long)&tx_buf;
    spi_ioctl.len = tx_length;

    if (ioctl(*static_cast<int*>(handle), SPI_IOC_MESSAGE(1), &spi_ioctl) == -1)
    {
        return process_spi_dev_error_codes(errno);
    }

    return E_COMBRIDGE_OK;
}

/*****************************************************************************************/
combridge_status_t combridge_i2c_read_16bit(bmv080_sercom_handle_t handle, uint16_t header, uint16_t* payload, uint16_t payload_length)
{
    if (!is_i2c_initialized)
    {
        return E_COMBRIDGE_ERROR_ENDPOINT_NOT_INITIALIZED;
    }

    if ((handle == nullptr) || (payload == nullptr))
    {
        return E_COMBRIDGE_ERROR_PARAMETER_NULL_POINTER;
    }

    if ((payload_length == 0) || (MAX_TX_RX_BYTES < (payload_length * 2)))
    {
        return E_COMBRIDGE_ERROR_PARAMETER_INVALID_VALUE;
    }

    // Single buffer for tranfer, first two bytes contain the header 
    // information, the rest of the buffer will be used for receiving data
    uint8_t i2c_buffer[REG_ADDR_HEADER_SIZE + (payload_length * 2)] = {0};
    uint16_t rx_length = static_cast<uint16_t>(payload_length * 2);

    /* 16 bit header left shifted, since the R/W bit has already been passed */
    uint16_t header_adjusted = header << 1;

    // Swap byte positions for header
    i2c_buffer[0] = static_cast<uint8_t>((header_adjusted >> 8) & 0xFF);
    i2c_buffer[1] = static_cast<uint8_t>(header_adjusted & 0xFF);
    
    // Write Header
    if(write(*static_cast<int*>(handle), i2c_buffer, 2) < 0)
    {
        return process_i2c_dev_error_codes(errno);
    }

    // Read Data
    if(read(*static_cast<int*>(handle), &i2c_buffer[2], rx_length) < 0)
    {
        return process_i2c_dev_error_codes(errno);
    }

    // Swap byte positions for payload
    for (uint16_t i = 0, j = 2; i < payload_length; i++, j = j + 2)
    {
        // Set initial value to zero before bit manipulation.
        payload[i] = 0;
        payload[i] = ((i2c_buffer[j] << 8) & 0xFF00);
        payload[i] = (payload[i] | (i2c_buffer[j + 1] & 0x00FF));
    }

    return E_COMBRIDGE_OK;
}

/*****************************************************************************************/
combridge_status_t combridge_i2c_write_16bit(bmv080_sercom_handle_t handle, uint16_t header, const uint16_t* payload, uint16_t payload_length)
{
    if (!is_i2c_initialized)
    {
        return E_COMBRIDGE_ERROR_ENDPOINT_NOT_INITIALIZED;
    }

    if ((handle == nullptr) || (payload == nullptr))
    {
        return E_COMBRIDGE_ERROR_PARAMETER_NULL_POINTER;
    }

    if ((payload_length == 0) || (MAX_TX_RX_BYTES < (payload_length * 2)))
    {
        return E_COMBRIDGE_ERROR_PARAMETER_INVALID_VALUE;
    }

    uint8_t tx_buf[REG_ADDR_HEADER_SIZE + (payload_length * 2)] = { 0 };
    uint16_t tx_length = static_cast<uint16_t>(REG_ADDR_HEADER_SIZE + (payload_length * 2));

    /* 16 bit header left shifted, since the R/W bit has already been passed */
    uint16_t header_adjusted = header << 1;

    // Swap byte positions for header
    tx_buf[0] = static_cast<uint8_t>((header_adjusted >> 8) & 0xFF);
    tx_buf[1] = static_cast<uint8_t>(header_adjusted & 0xFF);

    // Swap byte positions for payload
    for (uint16_t i = 0, j = 2; i < payload_length; i++, j = j + 2)
    {
        tx_buf[j] = (payload[i] & 0xFF00) >> 8;
        tx_buf[j + 1] = (payload[i]) & 0x00FF;
    }

    if (write(*static_cast<int*>(handle), tx_buf, tx_length) < 0)
    {
        return process_i2c_dev_error_codes(errno);
    }

    return E_COMBRIDGE_OK;
}

/*****************************************************************************************/
combridge_status_t combridge_release(bmv080_sercom_handle_t* handle)
{
    if (handle == nullptr)
    {
        return E_COMBRIDGE_ERROR_PARAMETER_NULL_POINTER;
    }

    if (is_spi_initialized)
    {
        close(*static_cast<int*>(*handle));
        is_spi_initialized = false;
    }
    else if (is_i2c_initialized)
    {
        close(*static_cast<int*>(*handle));
        is_i2c_initialized = false;
    }
    else
    {
        return E_COMBRIDGE_ERROR_ENDPOINT_NOT_INITIALIZED;
    }

    return E_COMBRIDGE_OK;
}

/*****************************************************************************************/
uint32_t combridge_get_tick(void)
{
    return static_cast<uint32_t>(chrono::duration_cast<chrono::milliseconds>(chrono::steady_clock::now().time_since_epoch()).count());
}

/*****************************************************************************************/
int8_t combridge_delay(uint32_t period)
{
    if(usleep(period * MICROSECONDS_TO_MILLISECONDS) == -1)
    {
        return E_COMBRIDGE_ERROR_EXTERNAL_LIB_COM;
    }

    return E_COMBRIDGE_OK;
}

/***************************************************************************************/
static combridge_status_t process_spi_dev_error_codes(int error_code)
{
    switch(error_code)
    {
        case EPERM:
            return E_COMBRIDGE_SPIDEV_EPERM;
        case ENOENT:
            return E_COMBRIDGE_SPIDEV_ENOENT;
        case EINTR:
            return E_COMBRIDGE_SPIDEV_EINTR;
        case ENXIO:
            return E_COMBRIDGE_SPIDEV_ENXIO;
        case EBADF:
            return E_COMBRIDGE_SPIDEV_EBADF;
        case EAGAIN:
            return E_COMBRIDGE_SPIDEV_EAGAIN;
        case ENOMEM:
            return E_COMBRIDGE_SPIDEV_ENOMEM;
        case EACCES:
            return E_COMBRIDGE_SPIDEV_EACCES;
        case EFAULT:
            return E_COMBRIDGE_SPIDEV_EFAULT;
        case ENODEV:
            return E_COMBRIDGE_SPIDEV_ENODEV;
        case EISDIR:
            return E_COMBRIDGE_SPIDEV_EISDIR;
        case EINVAL:
            return E_COMBRIDGE_SPIDEV_EINVAL;
        case ENFILE:
            return E_COMBRIDGE_SPIDEV_ENFILE;
        case EMFILE:
            return E_COMBRIDGE_SPIDEV_EMFILE;
        case ENOTTY:
            return E_COMBRIDGE_SPIDEV_ENOTTY;
        case ETXTBSY:
            return E_COMBRIDGE_SPIDEV_ETXTBSY;
        case ENOSPC:
            return E_COMBRIDGE_SPIDEV_ENOSPC;
        case EROFS:
            return E_COMBRIDGE_SPIDEV_EROFS;
        case ELOOP:
            return E_COMBRIDGE_SPIDEV_ELOOP;
        default:
            return E_COMBRIDGE_ERROR_EXTERNAL_LIB_CONFIG;
    }
}

static combridge_status_t process_i2c_dev_error_codes(int error_code)
{
    switch(error_code)
    {
        case EPERM:
            return E_COMBRIDGE_SPIDEV_EPERM;
        case EAFNOSUPPORT:
            return E_COMBRIDGE_I2CDEV_EAFNOSUPPORT;
        case EAGAIN:
            return E_COMBRIDGE_SPIDEV_EAGAIN;
        case EBADMSG:
            return E_COMBRIDGE_I2CDEV_EBADMSG;
        case EBUSY:
            return E_COMBRIDGE_I2CDEV_EBUSY;
        case EINVAL:
            return E_COMBRIDGE_SPIDEV_EINVAL;
        case EFAULT:
            return E_COMBRIDGE_SPIDEV_EFAULT;
        case EACCES:
            return E_COMBRIDGE_SPIDEV_EACCES;
        case EIO:
            return E_COMBRIDGE_I2CDEV_EIO;
        case ENODEV:
            return E_COMBRIDGE_SPIDEV_ENODEV;
        case ENOMEM:
            return E_COMBRIDGE_SPIDEV_ENOMEM;
        case ENXIO:
            return E_COMBRIDGE_SPIDEV_ENXIO;
        case EOPNOTSUPP:
            return E_COMBRIDGE_I2CDEV_EOPNOTSUPP;
        case EPROTO:
            return E_COMBRIDGE_I2CDEV_EPROTO;
        case ETIMEDOUT:
            return E_COMBRIDGE_I2CDEV_ETIMEDOUT;
        default:
            return E_COMBRIDGE_ERROR_EXTERNAL_LIB_CONFIG;
    }
}
