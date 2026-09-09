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
 * @brief Serial communication interface functions
 *
 *
 */

#ifndef COMBRIDGE_H
#define COMBRIDGE_H

#include <stdint.h>

#include "combridge_defs.h"


/*********************************************************************************************************************
* Combridge functions
*********************************************************************************************************************/

#ifdef __cplusplus
extern "C" {
#endif /* __cplusplus */

    /*!
    * @brief Initialize the serial communication interface and return the found channels.
    *
    * @pre Must be called first in order to initialize the serial communication framework.
    * @post The serial communication framework must be terminated via _combridge_terminate_.
    *
    * @param[out] num_channels : Number of available channels.
    * @param[out] channel_ids : Description of these _num_channels_ in incrementing order.
    *
    * @return E_COMBRIDGE_OK if successful, otherwise the return value is a combridge status code.
    */
    combridge_status_t combridge_initialize(uint32_t* num_channels, char*** channel_ids);

    /*!
    * @brief Setup a serial communication channel by creating a new handle.
    *
    * @pre The via _combridge_initialize_ initialized serial communication framework is required.
    * @pre Must be called first in order to create the _handle_ required by other functions.
    * @post The _handle_ must be released via _combridge_release_.
    *
    * @param[out] handle : Unique handle for a serial communication channel.
    * @param[in] channel_index : Select the channel to open from the available ones.
    *                            It corresponds to the position in _combridge_initialize_'s _channel_ids_ with
    *                            0 <= _channel_index_ < _num_channels_.
    * @param[in] clock_rate_in_hz : Clock rate in Hz of the serial communication channel.
    * @param[in] spi_mode : SPI mode of the serial communication channel.
    *
    * @return E_COMBRIDGE_OK if successful, otherwise the return value is a combridge status code.
    */
    combridge_status_t combridge_setup(combridge_handle_t* handle, uint32_t channel_index, uint32_t clock_rate_in_hz,
        combridge_spi_mode_t spi_mode);
	/*!
	* @brief Set a parameter.
	*
	* @details Table \ref parameter lists the available parameters with their keys.
	* This function can be called multiple times and is optional.
	*
	* <table>
	* <caption id = "parameter">Table parameter : Available parameters </caption>
	* <tr> <th> Key                        <th> Type                 <th> FT4222
	* <tr> <td> "spi_mode"                 <td> combridge_spi_mode_t <td> x     
	* <tr> <td> "clock_rate_hz"            <td> uint32_t             <td> x     
	* <tr> <td> "directory"                <td> char*                <td> x     
	* <tr> <td> "filename"                 <td> char*                <td> x     
	* <tr> <td> "ignore_length"            <td> uint32_t             <td> x     
	* <tr> <td> "log_irq"                  <td> bool                 <td> x     
	* <tr> <td> "status"                   <td> FT_STATUS            <td> x     
    * <tr> <td> "write_iso_time_code"      <td> bool                 <td> x     
	* </table>
	*
	* @pre A valid _handle_ generated by _combridge_setup_ is required.
	* @pre This function must be called before other functions in order to apply the parameter.
	*
	* @param[out] handle : Unique handle for a serial communication channel.
	* @param[in] key : Key of the parameter to set. Valid keys are listed in table \ref parameter.
	* @param[in] value : Value of the parameter to set of the in table \ref parameter listed type casted as void-pointer.
	*
	* @return E_COMBRIDGE_OK if successful, otherwise the return value is a combridge status code.
	*/
	combridge_status_t combridge_set_parameter(combridge_handle_t handle, const char* key, void* value);

    /*!
    * @brief Gets a parameter.
    *
    * @details Table \ref parameter lists the available parameters with their keys.
    * @pre A valid _handle_ generated by _combridge_setup_ is required.
    * @pre This function must be called before other functions in order to apply the parameter.
    *
    * @param[out] handle : Unique handle for a serial communication channel.
    * @param[in] key : Key of the parameter to get. Valid keys are listed in table \ref parameter.
    * @param[in] value : Value of the parameter to get, table \ref parameter lists types which are then casted as void-pointer.
    *
    * @return E_COMBRIDGE_OK if successful, otherwise the return value is a combridge status code.
    */
    combridge_status_t combridge_get_parameter(combridge_handle_t handle, const char* key, void* value);

	/*!
	* @brief Set a parameter.
	*
	* @details Table \ref parameter lists the available parameters with their keys.
	* This function can be called multiple times and is optional.
	*
	* <table>
	* <caption id = "parameter">Table parameter : Available parameters </caption>
	* <tr> <th> Key                        <th> Type                 <th> Set/Get <th> FT4222 
	* <tr> <td> "spi_mode"                 <td> combridge_spi_mode_t <td> set     <td> x     
	* <tr> <td> "clock_rate_hz"            <td> uint32_t             <td> set     <td> x     
	* <tr> <td> "directory"                <td> char*                <td> set     <td> x     
	* <tr> <td> "filename"                 <td> char*                <td> set     <td> x     
	* <tr> <td> "ignore_length"            <td> uint32_t             <td> set     <td> x     
	* <tr> <td> "log_irq"                  <td> bool                 <td> set     <td> x     
	* <tr> <td> "status"                   <td> FT_STATUS            <td> set     <td> x     
    * <tr> <td> "write_iso_time_code"      <td> bool                 <td> set     <td> x     
	* </table>
	*
	* @pre A valid _handle_ generated by _combridge_setup_ is required.
	* @pre This function must be called before other functions in order to apply the parameter.
	*
	* @param[out] handle : Unique handle for a serial communication channel.
	* @param[in] key : Key of the parameter to set. Valid keys are listed in table \ref parameter.
	* @param[in] value : Value of the parameter to set of the in table \ref parameter listed type casted as void-pointer.
	*
	* @return E_COMBRIDGE_OK if successful, otherwise the return value is a combridge status code.
	*/
	combridge_status_t combridge_set_parameter(combridge_handle_t handle, const char* key, void* value);

    /*!
    * @brief Gets a parameter.
    *
    * @details Table \ref parameter lists the available parameters with their keys.
    * @pre A valid _handle_ generated by _combridge_setup_ is required.
    * @pre This function must be called before other functions in order to apply the parameter.
    *
    * @param[out] handle : Unique handle for a serial communication channel.
    * @param[in] key : Key of the parameter to get. Valid keys are listed in table \ref parameter.
    * @param[in] value : Value of the parameter to get, table \ref parameter lists types which are then casted as void-pointer.
    *
    * @return E_COMBRIDGE_OK if successful, otherwise the return value is a combridge status code.
    */
    combridge_status_t combridge_get_parameter(combridge_handle_t handle, const char* key, void* value);

    /*!
    * @brief Read an array of _payload_length_ words of 16 bit _payload_.
    *
    * @details All data, _header_ and _payload_, is transferred as MSB first.
    *          Both _header_ and _payload_ words are 16 bit and combined.
    *          A _payload_ is only transferred on a complete transmission of 16 bits.
    *          Burst transfers, i.e. reading a _header_ followed by several _payload_ elements, are supported.
    *
    * @pre A valid _handle_ generated by _combridge_setup_ is required.
    *
    * @param[in] sercom_handle : Handle for a serial communication interface to a specific sensor unit.
    * @param[in] header : Header information for the following _payload_.
    * @param[out] payload : Payload to be read consisting of 16 bit words.
    * @param[in] payload_length : Number of _payload_ elements to be read.
    *
    * @return E_COMBRIDGE_OK if successful, otherwise the return value is a combridge status code.
    */
    combridge_status_t combridge_read_16bit(combridge_handle_t handle, uint16_t header, uint16_t* payload, uint16_t payload_length);

    /*!
    * @brief Write an array of _payload_length_ words of 16 bit _payload_.
    *
    * @details All data, _header_ and _payload_, is transferred as MSB first.
    *          Both _header_ and _payload_ words are 16 bit and combined.
    *          A _payload_ is only transferred on a complete transmission of 16 bits.
    *          Burst transfers, i.e. writing a _header_ followed by several _payload_ elements, are supported.
    *
    * @pre A valid _handle_ generated by _combridge_setup_ is required.
    *
    * @param[in] sercom_handle : Handle for a serial communication interface to a specific sensor unit.
    * @param[in] header : Header information for the following _payload_.
    * @param[in] payload : Payload to be written consisting of 16 bit words.
    * @param[in] payload_length : Number of _payload_ elements to be written.
    *
    * @return E_COMBRIDGE_OK if successful, otherwise the return value is a combridge status code.
    */
    combridge_status_t combridge_write_16bit(combridge_handle_t handle, uint16_t header, const uint16_t* payload, uint16_t payload_length);

    /*!
    * @brief Release the serial communication channel.
    *
    * @pre Must be called last in order to release the _handle_ created by _combridge_setup_.
    *
    * @param[in] handle : Unique handle for a serial communication channel.
    *
    * @return E_COMBRIDGE_OK if successful, otherwise the return value is a combridge status code.
    */
    combridge_status_t combridge_release(combridge_handle_t* handle);

    /*!
    * @brief Terminate the serial communication interface.
    *
    * @pre Must be called last in order to terminate the serial communication framework initialized by _combridge_initialize_.
    *
    * @return E_COMBRIDGE_OK if successful, otherwise the return value is a combridge status code.
    */
    combridge_status_t combridge_terminate(void);

    /*!
    * @brief Execute a software delay operation.
    *
    * @pre A valid _handle_ generated by _combridge_setup_ is required.
    *
    * @param[in] duration_in_ms : Duration of the delay in milliseconds.
    *
    * @return E_COMBRIDGE_OK if successful, otherwise the return value is a combridge status code.
    */
    combridge_status_t combridge_delay(uint32_t duration_in_ms);

    /*!
    * @brief Get the current tick value in milliseconds (based on the host system clock).
    *
    * @details This serves as a measure of the elapsed time since start up.
    *
    * @return Tick value in milliseconds.
    */
    uint32_t combridge_get_tick(void);

#ifdef __cplusplus
}
#endif

#endif /* COMBRIDGE_H */
