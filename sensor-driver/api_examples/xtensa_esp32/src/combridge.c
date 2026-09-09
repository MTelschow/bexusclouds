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
#include <unistd.h>
#include <sys/param.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/semphr.h"
#include "driver/gpio.h"
#include "esp_log.h"
#include "sdkconfig.h"


/* Private define ------------------------------------------------------------*/
#if defined(BOARD_ESP32_V2)
    /* SPI GPIO Configuration */
    #define PIN_NUM_MISO        21
    #define PIN_NUM_MOSI        19
    #define PIN_NUM_CLK          5
    #define PIN_NUM_CS          15
    #define SPI_MODULE          SPI3_HOST
    /* I2C GPIO Configuration */
    #define PIN_NUM_SCL         20      
    #define PIN_NUM_SDA         22
#elif defined(BOARD_ESP32_S2) || defined(BOARD_ESP32_S3)
    /* SPI GPIO Configuration */
    #define PIN_NUM_MISO        37
    #define PIN_NUM_MOSI        35
    #define PIN_NUM_CLK         36
    #define PIN_NUM_CS          9
    #define SPI_MODULE          SPI3_HOST
    /* I2C GPIO Configuration */
    #define PIN_NUM_SCL         4 
    #define PIN_NUM_SDA         3
#elif defined(BOARD_ESP32_C6)
    /* SPI GPIO Configuration */
    #define PIN_NUM_MISO        18
    #define PIN_NUM_MOSI        23
    #define PIN_NUM_CLK         19
    #define PIN_NUM_CS          13   
    #define SPI_MODULE          SPI2_HOST
    /* I2C GPIO Configuration */
    #define PIN_NUM_SCL         7 
    #define PIN_NUM_SDA         6
#endif

#define SPI_CLK_FREQ ((int)(1e6))

#define I2C_CLK_FREQ          ((int)(100e3))
#define I2C_MODULE            0
#define I2C_DEVICE_ADDRESS    0x54
#define I2C_TIMEOUT_MS        1000
#define I2C_ACK_CHECK_EN      0x1


/* Exported functions --------------------------------------------------------*/

esp_err_t spi_init(spi_device_handle_t *spi)
{
    esp_err_t err = ESP_OK;

    spi_bus_config_t buscfg = {
        .miso_io_num = PIN_NUM_MISO,
        .mosi_io_num = PIN_NUM_MOSI,
        .sclk_io_num = PIN_NUM_CLK,
        .quadwp_io_num = -1,
        .quadhd_io_num = -1};

    err = spi_bus_initialize(SPI_MODULE, &buscfg, SPI_DMA_CH_AUTO);

    spi_device_interface_config_t devcfg = {
        .address_bits = 16,
        .clock_speed_hz = SPI_CLK_FREQ,
        .mode = 0,
        .spics_io_num = PIN_NUM_CS,
        .queue_size = 1};

    err = spi_bus_add_device(SPI_MODULE, &devcfg, spi);
    return err;
}


esp_err_t spi_deinit(spi_device_handle_t *spi)
{
    spi_bus_remove_device(*spi);
    *spi = NULL;
    return ESP_OK;
}


esp_err_t i2c_init(int *i2c)
{
    esp_err_t err = ESP_OK;

    i2c_config_t buscfg = {
        .mode = I2C_MODE_MASTER,
        .sda_io_num = PIN_NUM_SDA,
        .scl_io_num = PIN_NUM_SCL,
        .sda_pullup_en = GPIO_PULLUP_DISABLE,
        .scl_pullup_en = GPIO_PULLUP_DISABLE,
        .master.clk_speed = I2C_CLK_FREQ,
        .clk_flags = 0,
    };
    *i2c = I2C_MODULE;
    err = i2c_param_config(*i2c, &buscfg);
    err = i2c_driver_install(*i2c, buscfg.mode, 0, 0, 0);

    return err;
}


esp_err_t i2c_deinit(int *i2c)
{
    i2c_driver_delete(*i2c);
    return ESP_OK;
}


int8_t combridge_spi_read_16bit(bmv080_sercom_handle_t handle, uint16_t header, uint16_t *payload, uint16_t payload_length)
{
    spi_transaction_ext_t spi_transaction = (spi_transaction_ext_t){
        .base = {
            .flags = (SPI_TRANS_VARIABLE_ADDR | SPI_TRANS_VARIABLE_CMD),
            .addr = header,
            .length = payload_length * 2 * 8,
            .rxlength = payload_length * 2 * 8,
            .tx_buffer = NULL,
            .rx_buffer = (void *)payload},
        .command_bits = 0,
        .address_bits = 16,
        .dummy_bits = 0,
    };

    esp_err_t err = spi_device_polling_transmit((spi_device_handle_t)handle, (spi_transaction_t *)&spi_transaction);

    /* Conversion of payload from big endian to little endian */
    for (int payload_idx = 0; payload_idx < payload_length; payload_idx++)
    {
        uint16_t swapped_word = ((payload[payload_idx] << 8) | (payload[payload_idx] >> 8)) & 0xffff;
        payload[payload_idx] = swapped_word;
    }

    return (int8_t)err;
}


int8_t combridge_spi_write_16bit(bmv080_sercom_handle_t handle, uint16_t header, const uint16_t *payload, uint16_t payload_length)
{
    esp_err_t err;

    /* Conversion of payload from little endian to big endian (dynamic allocation is used) */
    uint16_t *payload_swapped = (uint16_t *)calloc(payload_length, sizeof(uint16_t));
    for (int payload_idx = 0; payload_idx < payload_length; payload_idx++)
    {
        payload_swapped[payload_idx] = ((payload[payload_idx] << 8) | (payload[payload_idx] >> 8)) & 0xffff;
    }

    spi_transaction_ext_t spi_transaction = (spi_transaction_ext_t){
        .base = {
            .flags = (SPI_TRANS_VARIABLE_ADDR | SPI_TRANS_VARIABLE_CMD),
            .addr = header,
            .length = payload_length * 2 * 8,
            .rx_buffer = NULL,
            .tx_buffer = (void *)payload_swapped},
        .command_bits = 0,
        .address_bits = 16,
        .dummy_bits = 0,
    };

    err = spi_device_transmit((spi_device_handle_t)handle, (spi_transaction_t *)&spi_transaction);

    free(payload_swapped);

    return (int8_t)err;
}


int8_t combridge_i2c_read_16bit(bmv080_sercom_handle_t handle, uint16_t header, uint16_t *payload, uint16_t payload_length)
{
    /* 16-bit header left shifted by 1, since the R/W bit (most significant bit) is passed along with the 7-bit device address  */
    uint16_t header_adjusted = header << 1;

    i2c_cmd_handle_t cmd = i2c_cmd_link_create();
    i2c_master_start(cmd);
    /* 7-bit I2C address + R/W bit (R = 1, W = 0) to write header information */
    i2c_master_write_byte(cmd, (I2C_DEVICE_ADDRESS << 1) | I2C_MASTER_WRITE, I2C_ACK_CHECK_EN);

    i2c_master_write_byte(cmd, (header_adjusted >> 8) & 0xFF, I2C_ACK_CHECK_EN);
    i2c_master_write_byte(cmd, header_adjusted & 0xFF, I2C_ACK_CHECK_EN);
    i2c_master_stop(cmd);
    
    int i2c_num = *((int *)handle);
    esp_err_t err  = i2c_master_cmd_begin(i2c_num, cmd, I2C_TIMEOUT_MS / portTICK_PERIOD_MS);
    i2c_cmd_link_delete(cmd);

    cmd = i2c_cmd_link_create();
    i2c_master_start(cmd);
    /* 7-bit I2C address + R/W bit (R = 1, W = 0) to read payload information */
    i2c_master_write_byte(cmd, (I2C_DEVICE_ADDRESS << 1) | I2C_MASTER_READ, I2C_ACK_CHECK_EN);
    i2c_master_read(cmd, (uint8_t *)payload, payload_length * 2, I2C_MASTER_LAST_NACK);
    i2c_master_stop(cmd);

    err = i2c_master_cmd_begin(i2c_num, cmd, I2C_TIMEOUT_MS/ portTICK_PERIOD_MS);
    i2c_cmd_link_delete(cmd);

    /* Conversion of payload from big endian to little endian */
    for (int payload_idx = 0; payload_idx < payload_length; payload_idx++)
    {
        uint16_t swapped_word = ((payload[payload_idx] << 8) | (payload[payload_idx] >> 8)) & 0xffff;
        payload[payload_idx] = swapped_word;
    }

    return (int8_t)err;
}


int8_t combridge_i2c_write_16bit(bmv080_sercom_handle_t handle, uint16_t header, const uint16_t *payload, uint16_t payload_length)
{
    /* 7-bit I2C address + most significant bit of the header passed from the sensor driver which represents the R/W bit (R = 1, W = 0) */
    uint8_t device_address = (I2C_DEVICE_ADDRESS << 1) | (header >> 15);
    /* 16-bit header left shifted by 1, since the R/W bit (most significant bit) is passed along with the 7-bit device address  */
    uint16_t header_adjusted = header << 1;

    /* Conversion of payload from little endian to big endian (dynamic allocation is used) */
    uint16_t *payload_swapped = (uint16_t *)calloc(payload_length, sizeof(uint16_t));
    for (int payload_idx = 0; payload_idx < payload_length; payload_idx++)
    {
        payload_swapped[payload_idx] = ((payload[payload_idx] << 8) | (payload[payload_idx] >> 8)) & 0xffff;
    }

    i2c_cmd_handle_t cmd = i2c_cmd_link_create();
    i2c_master_start(cmd);
    i2c_master_write_byte(cmd, device_address, I2C_ACK_CHECK_EN);

    i2c_master_write_byte(cmd, (header_adjusted >> 8) & 0xFF, I2C_ACK_CHECK_EN);
    i2c_master_write_byte(cmd, header_adjusted & 0xFF, I2C_ACK_CHECK_EN);

    i2c_master_write(cmd, (uint8_t *)payload_swapped, payload_length * 2, I2C_MASTER_ACK);
    i2c_master_stop(cmd);

    int i2c_num = *((int *)handle);
    esp_err_t err = i2c_master_cmd_begin(i2c_num, cmd, I2C_TIMEOUT_MS / portTICK_PERIOD_MS);
    i2c_cmd_link_delete(cmd);

    free(payload_swapped);

    return (int8_t)err;
}


int8_t combridge_delay(uint32_t period)
{
    vTaskDelay(period / portTICK_PERIOD_MS);
    return ESP_OK;
}
