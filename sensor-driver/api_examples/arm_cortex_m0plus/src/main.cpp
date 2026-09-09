/**
 ******************************************************************************
 * @file           : main.cpp
 * @brief          : Example application demonstrating how to execute a 
 *                   particulate matter measurement with a BMV080 sensor unit.
 * @details        : Target SoC: ARM Cortex-M33F
 *                   Board: Arduino Portenta C33
 *                   Toolchain: GCC (ARM)
 *                   Framework: Arduino
 ******************************************************************************
 * @attention
 * 
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
 ******************************************************************************
 */

/* Includes ------------------------------------------------------------------*/
#include <stdio.h>
#include <stdarg.h>
#include "combridge.h"
#include "bmv080_example.h"

/* Private defines */
#define MAX_TX_RX_BUFFER_SIZE 2048
#define FLAG_EXT_IRQ_TRIGGERED (1UL << 0)
#define BSP_IO_PORT_PIN_13 (13u)
#define IRQ_Pin (7u)

/* Private variables ---------------------------------------------------------*/
spi_device_t spi_device = {};
i2c_device_t i2c_device = {};
uint8_t bmv080_stack[20000]; // user stack
rtos::EventFlags event_flags;

/* Private function prototypes -----------------------------------------------*/
void print_to_serial(const char *format, ...);
rtos::Thread thread(osPriorityLow, sizeof(bmv080_stack), bmv080_stack, "bmv080_example");
rtos::Thread bvm080_service_thread(osPriorityHigh, 20000);
void enable_external_interrupt(bool enable);
void gpio_isr_handler(void);

/* Private functions ---------------------------------------------------------*/
void bmv080_thread()
{
    bmv080_status_code_t bmv080_final_status = bmv080(
#if HOST_INTERFACE == HOST_INTERFACE_SPI
                    (bmv080_sercom_handle_t)&spi_device,
                    (const bmv080_callback_read_t)combridge_spi_read_16bit,
                    (const bmv080_callback_write_t)combridge_spi_write_16bit,
#elif HOST_INTERFACE == HOST_INTERFACE_I2C
                    (bmv080_sercom_handle_t)&i2c_device,
                    (const bmv080_callback_read_t)combridge_i2c_read_16bit,
                    (const bmv080_callback_write_t)combridge_i2c_write_16bit,
#else
    #error "Unknown host interface. Supported host communication interfaces are SPI and I2C."
#endif 
                    (const bmv080_callback_delay_t)combridge_delay,
                    (const bmv080_callback_tick_t)millis,
                    (const print_function_t)print_to_serial,
                    ( (const enable_ext_interrupt_function_t) enable_external_interrupt) );

    if (bmv080_final_status != E_BMV080_OK)
    {
        print_to_serial("Executing the sensor APIs failed with bmv080 status %d\n", (int)bmv080_final_status);
    }
}

void enable_external_interrupt(bool enable)
{
    if(enable)
    {    /* Enabel external interrupt */
        attachInterrupt(digitalPinToInterrupt(IRQ_Pin), gpio_isr_handler, FALLING );  
    }else
    {    /* Disable external interrupt */
        detachInterrupt(digitalPinToInterrupt(IRQ_Pin) );
    }    
}

void gpio_isr_handler(void)
{
    /* Set event flag to signal external irq was triggered */
    event_flags.set(FLAG_EXT_IRQ_TRIGGERED);
}

void bmv080_InterruptTask()
{
    while (1)
    {
        // Wait for an external interrupt event
        event_flags.wait_any(FLAG_EXT_IRQ_TRIGGERED);        

        // If an interrupt signal is received, process the new data
        do {
            // Call the service routine to handle the interrupt
            bmv080_service_routine();
            // Clear the interrupt flag
            event_flags.clear(FLAG_EXT_IRQ_TRIGGERED);
            // Add a delay to gice other threads the chance to run
            delay(50);
        // Continue processing as long as the interrupt pin is low
        } while (digitalRead(IRQ_Pin) == 0);
    }
}

void setup()
{
    Serial.begin(115200);
    delay(5000);
    /* Communication interface initialization */
    init_spi(&spi_device);
    init_i2c(&i2c_device);
    pinMode(BSP_IO_PORT_PIN_13, OUTPUT);
    /* Initialize external IRQ */
    pinMode(IRQ_Pin, INPUT);
    bvm080_service_thread.start(bmv080_InterruptTask);  
    /* Sensor API execution */
    thread.start(bmv080_thread);
}


void loop()
{
    delay(200);
    /* Pin BSP_IO_PORT_PIN_13 is connected to the status LED on the Feather RP2040 board */
    digitalWrite(BSP_IO_PORT_PIN_13 , !digitalRead(13));
}


void print_to_serial(const char *format, ...) 
{
    char print_buffer[1024];
    va_list args;
    va_start(args, format);
    vsnprintf(print_buffer, sizeof(print_buffer), format, args);
    va_end(args);
    Serial.print(print_buffer);
}
