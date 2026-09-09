/**
 ******************************************************************************
 * @file           : main.c
 * @brief          : Example application demonstrating how to execute a 
 *                   particulate matter measurement with a BMV080 sensor unit.
 * @details        : Target SoC: ESP32, ESP32-S2, E32-S3
 *                   Board: Adafruit ESP32 Feather V2
 *                          Adafruit ESP32-S2 Feather
 *                          Adafruit ESP32-S3 Feather
 *                   Toolchain: GCC (Xtensa)
 *                   Framework: ESP-IDF
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
#include <unistd.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_system.h"
#include "esp_log.h"
#include "combridge.h"
#include "bmv080_example.h"
#include "driver/gpio.h"


/* Private defines------------------------------------------------------------*/
#if defined(BOARD_ESP32_V2)
    #define PIN_IRQ	GPIO_NUM_14 /*GPIO 14 for ESP32 V2*/
#elif defined(BOARD_ESP32_S3) || defined(BOARD_ESP32_S2)
    #define PIN_IRQ	GPIO_NUM_5 /*GPIO 5 for ESP32-S3*/
#elif defined(BOARD_ESP32_C6)
    #define PIN_IRQ	GPIO_NUM_15 /*GPIO 14 for ESP32-C6*/
#endif
#define PIN_IRQ_MASK	(1ULL << PIN_IRQ) /* GPIO Mask for interrupt pin */

/* Private variables ---------------------------------------------------------*/
spi_device_handle_t hspi;
int hi2c;
SemaphoreHandle_t sem_ext_irq_triggered = NULL;
SemaphoreHandle_t mutex = NULL;
bool is_irq_enabled = false;

/* Private function prototypes -----------------------------------------------*/
uint32_t get_tick_ms(void);

/* Private functions ---------------------------------------------------------*/

/**
 * @brief Enables or disables the external interrupt.
 *
 * This function enables or disables the external interrupt based on the value of the 'enable' parameter.
 *
 * @param enable Flag indicating whether to enable or disable the external interrupt.
 *               - true: Enable the external interrupt.
 *               - false: Disable the external interrupt.
 */
void enable_external_interrupt(bool enable)
{
    if(enable)
    {
        gpio_intr_enable(PIN_IRQ);
        is_irq_enabled = true;
    }else
    {
        gpio_intr_disable (PIN_IRQ);
        is_irq_enabled = false;
    }    
}

/* This function, thread_safe_printf, is a thread-safe version of the standard printf function.
* It uses a mutex to ensure that only one thread can execute the printf function at a time, preventing race conditions.
*/
int thread_safe_printf(const char *const _format, ...)
{
    int retVal = 0;
    const int wait_for_mutex = 100 / portTICK_PERIOD_MS; // wait maximum of 100ms for the mutex
    va_list args;
    va_start(args, _format);

    if(mutex == NULL) {
        // Handle error: Mutex creation failed
        return -1;
    }

    if(xSemaphoreTake(mutex, wait_for_mutex) == pdTRUE) {
        retVal = vprintf(_format, args);
        xSemaphoreGive(mutex);
    } else {
        retVal = -1; /* Mutex take failed, return -1 to signal error */
    }

    va_end(args);
    return retVal;
}

void bmv080_task(void *pvParameter)
{
    bmv080_status_code_t bmv080_final_status = bmv080(
#if HOST_INTERFACE == SPI
                    (bmv080_sercom_handle_t)hspi,
                    (const bmv080_callback_read_t)combridge_spi_read_16bit,
                    (const bmv080_callback_write_t)combridge_spi_write_16bit,
#elif HOST_INTERFACE == I2C
                    (bmv080_sercom_handle_t)&hi2c,
                    (const bmv080_callback_read_t)combridge_i2c_read_16bit,
                    (const bmv080_callback_write_t)combridge_i2c_write_16bit,
#else
    #error "Unknown host interface. Supported host communication interfaces are SPI and I2C."
#endif 
                    (const bmv080_callback_delay_t)combridge_delay,
                    (const bmv080_callback_tick_t)get_tick_ms,
                    (const print_function_t)thread_safe_printf,
                    (const enable_ext_interrupt_function_t) enable_external_interrupt);

    if (bmv080_final_status != E_BMV080_OK)
    {
        printf("Executing the sensor APIs failed with bmv080 status %d\r\n", (int)bmv080_final_status);
    }

    while (1);
}


/**
 * @brief Task that handles the interrupt triggered by the BMV080 sensor.
 *
 * This task creates a binary semaphore to signal the occurrence of an interrupt.
 * The semaphore is posted in the gpio_isr_handler() and consumed in this task.
 * When the semaphore becomes available, the task calls the bmv080_service_routine()
 * to process the new data. The task continues to call the service routine until the
 * interrupt pin (PIN_IRQ) is no longer active.
 *
 * @param pvParameter Pointer to the task parameter (not used in this task).
 */
void bmv080_InterruptTask(void *pvParameter)
{
    /* Create a binary semaphore for signaling. Semaphore is posted
    in gpio_isr_handler() and consumed in this task. */ 
    sem_ext_irq_triggered = xSemaphoreCreateBinary();

    while (1)
    {
        if(!is_irq_enabled)
        {
            continue;
        }
        if (xSemaphoreTake(sem_ext_irq_triggered, ( TickType_t )portMAX_DELAY))
        { /* If semaphore becomes available call bmv080_service_routine to process the new data */
            do
            {
                bmv080_service_routine();
            } while (gpio_get_level(PIN_IRQ) == 0);
            /* Turn on the external interrupt again after data processing is complete */            
            enable_external_interrupt(true);
       }
    }
}
/**
 * @brief GPIO ISR handler function.
 *
 * This function is the interrupt service routine (ISR) for the GPIO interrupt.
 * It is called when a GPIO interrupt is triggered. The function posts the semaphore 
 * sem_ext_irq_triggered, which is consumed in the bmv080_InterruptTask.
 *
 * @param arg Pointer to the argument passed to the ISR, not used.
 */
static void IRAM_ATTR gpio_isr_handler(void* arg)
{
    if (sem_ext_irq_triggered != NULL)
    {
        BaseType_t xHigherPriorityTaskWoken = pdFALSE;
        xSemaphoreGiveFromISR(sem_ext_irq_triggered, &xHigherPriorityTaskWoken);
        portYIELD_FROM_ISR(xHigherPriorityTaskWoken);
        /* Disable external interrupt to address ESP32's issue where the edge interrupt may be triggered multiple times */
        enable_external_interrupt(false); 
    }
}

void init_ext_irq(void)
{
/* Initialize the GPIO configuration structure to zero. This ensures all fields are set to safe default values. */
    gpio_config_t io_conf = {};
    /* Disable pull-down mode. The BMV080 IRQ line is equipped with an internal pull-up resistor. */
    io_conf.pull_down_en = 0;
    /* Disable pull-up mode. The BMV080 IRQ line is equipped with an internal pull-up resistor. */
    io_conf.pull_up_en = 0;
    /* Set the interrupt type to falling edge.*/
    io_conf.intr_type = GPIO_INTR_NEGEDGE;
    /* Set the pin bit mask. This identifies which pin(s) the configuration applies to. */
    io_conf.pin_bit_mask = PIN_IRQ_MASK;
    /* Set the mode to input. This means the pin will be used to read data, not send it. */
    io_conf.mode = GPIO_MODE_INPUT;
    /* Apply the configuration to the GPIO pin with the gpio_config function. */
    gpio_config(&io_conf);
    /* Install the GPIO ISR (Interrupt Service Routine) service. This allows the pin to handle interrupts. */
    gpio_install_isr_service(0);
    /* Hook the ISR handler for the specific GPIO pin. This sets up the function that will be called when an interrupt occurs.*/
    gpio_isr_handler_add(PIN_IRQ, gpio_isr_handler, (void*) PIN_IRQ);
    /* Deactivate the external interrupt for now, it will be activated in the example code once it is needed */ 
    enable_external_interrupt(false);    
    printf("Initializing IRQ\n");

}

void app_main()
{
    mutex = xSemaphoreCreateMutex();
    combridge_delay(5000);
    
    printf("\r\n");

    esp_err_t comm_status = spi_init(&hspi);
    if(comm_status != ESP_OK)
    {
        printf("Initializing the SPI communication interface failed with status %d\r\n", (int)comm_status);
        while (1);
    }

    comm_status = i2c_init(&hi2c);
    if(comm_status != ESP_OK)
    {
        printf("Initializing the I2C communication interface failed with status %d\r\n", (int)comm_status);
        while (1);
    }

    xTaskCreate(&bmv080_task, "bmv080_task", 60 * 1024, NULL, configMAX_PRIORITIES - 1, NULL);
#ifdef USE_EXTERNAL_INTERRUPT
    init_ext_irq();
    xTaskCreate(&bmv080_InterruptTask, "bmv080_InterruptTask", 50 * 1024, NULL, configMAX_PRIORITIES -15, NULL);
#endif
}

uint32_t get_tick_ms(void)
{
    return xTaskGetTickCount() * portTICK_PERIOD_MS;
}
