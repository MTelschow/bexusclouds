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


/* Includes ------------------------------------------------------------------*/
#include "combridge.h"
#include "main.h"
#include <stdlib.h>


/* Private define ------------------------------------------------------------*/
/* BMV080 I2C address
 * note that the BMV080 pins are connected such that I2C Address Bit 0 = 0 and I2C Address Bit 1 = 0 
 */
#define BMV080_I2C_ADDRESS 0x54


/* Exported functions --------------------------------------------------------*/
int8_t combridge_spi_read_16bit(bmv080_sercom_handle_t handle, uint16_t header, uint16_t *payload, uint16_t payload_length)
{
    HAL_StatusTypeDef return_value;
    SPI_HandleTypeDef *spi_handle = (SPI_HandleTypeDef *)handle;

    /* verify function parameters */
    if ((handle == NULL) || (payload == NULL))
    {
        return HAL_ERROR;
    }

    if ((payload_length == 0))
    {
        return HAL_ERROR;
    }

    HAL_GPIO_WritePin(CS_GPIO_Port, CS_Pin, GPIO_PIN_RESET);
    return_value = HAL_SPI_Transmit(spi_handle, (uint8_t *)(&header), 1, HAL_MAX_DELAY);
    if (return_value == HAL_OK)
    {
        return_value = HAL_SPI_Receive(spi_handle, (uint8_t *)payload, payload_length, HAL_MAX_DELAY);
    }
    HAL_GPIO_WritePin(CS_GPIO_Port, CS_Pin, GPIO_PIN_SET);

    return (int8_t)return_value;
}


int8_t combridge_spi_write_16bit(bmv080_sercom_handle_t handle, uint16_t header, const uint16_t *payload, uint16_t payload_length)
{
    HAL_StatusTypeDef return_value;
    SPI_HandleTypeDef *spi_handle = (SPI_HandleTypeDef *)handle;

    /* verify function parameters */
    if ((handle == NULL) || (payload == NULL))
    {
        return HAL_ERROR;
    }

    if ((payload_length == 0))
    {
        return HAL_ERROR;
    }

    HAL_GPIO_WritePin(CS_GPIO_Port, CS_Pin, GPIO_PIN_RESET);
    return_value = HAL_SPI_Transmit(spi_handle, (uint8_t *)(&header), 1, HAL_MAX_DELAY);
    if (return_value == HAL_OK)
    {
        return_value = HAL_SPI_Transmit(spi_handle, (uint8_t *)payload, payload_length, HAL_MAX_DELAY);
    }
    HAL_GPIO_WritePin(CS_GPIO_Port, CS_Pin, GPIO_PIN_SET);

    return (int8_t)return_value;
}


int8_t combridge_i2c_read_16bit(bmv080_sercom_handle_t handle, uint16_t header, uint16_t *payload, uint16_t payload_length)
{
    HAL_StatusTypeDef return_value;
    I2C_HandleTypeDef *i2c_handle = (I2C_HandleTypeDef *)handle;

    /* verify function parameters */
    if ((handle == NULL) || (payload == NULL))
    {
        return HAL_ERROR;
    }

    if ((payload_length == 0))
    {
        return HAL_ERROR;
    }
    
    /* 7 bit I2C address + most significant bit of the header passed from the sensor driver which represents the R/W bit (R = high) */
    uint16_t device_address = (BMV080_I2C_ADDRESS << 1) | (header >> 15);
    /* 16 bit header left shifted, since the R/W bit has already been passed */
    uint16_t header_adjusted = header << 1;

    return_value = HAL_I2C_Mem_Read(i2c_handle, device_address, header_adjusted, I2C_MEMADD_SIZE_16BIT, (uint8_t *)payload, payload_length * 2, HAL_MAX_DELAY);
    
    /* Conversion of payload from big endian to little endian */
    for(int payload_idx = 0; payload_idx < payload_length; payload_idx++)
    {
        uint16_t swapped_word = ((payload[payload_idx] << 8)| (payload[payload_idx] >> 8)) & 0xffff;
        payload[payload_idx] = swapped_word;
    }

    return (int8_t)return_value;
}


int8_t combridge_i2c_write_16bit(bmv080_sercom_handle_t handle, uint16_t header, const uint16_t *payload, uint16_t payload_length)
{
    HAL_StatusTypeDef return_value;
    I2C_HandleTypeDef *i2c_handle = (I2C_HandleTypeDef *)handle;

    /* verify function parameters */
    if ((handle == NULL) || (payload == NULL))
    {
        return HAL_ERROR;
    }

    if ((payload_length == 0))
    {
        return HAL_ERROR;
    }

    /* 7 bit I2C address + most significant bit of the header passed from the sensor driver which represents the R/W bit (R = high) */
    uint16_t device_address = (BMV080_I2C_ADDRESS << 1) | (header >> 15);
    /* 16 bit header left shifted, since the R/W bit has already been passed */
    uint16_t header_adjusted = header << 1;

    /* Conversion of payload from little endian to big endian (dynamic allocation is used) */
    uint16_t *payload_swapped = (uint16_t *)calloc(payload_length, sizeof(uint16_t));
    for(int payload_idx = 0; payload_idx < payload_length; payload_idx++)
    {
        payload_swapped[payload_idx] =  ((payload[payload_idx] << 8)| (payload[payload_idx] >> 8)) & 0xffff;
    }
    

    return_value = HAL_I2C_Mem_Write(i2c_handle, device_address, header_adjusted, I2C_MEMADD_SIZE_16BIT, (uint8_t *)payload_swapped, payload_length * 2, HAL_MAX_DELAY);

    free(payload_swapped);

    return (int8_t)return_value;
}


int8_t combridge_delay(uint32_t period)
{
    HAL_Delay(period);
    return HAL_OK;
}
