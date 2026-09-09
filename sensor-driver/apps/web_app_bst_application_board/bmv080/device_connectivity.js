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
 */

var isConnected = false;
let connectionButton = null;
let disconnectButton = null;
const decoder = new TextDecoder();
const encoder = new TextEncoder();


let port = null;
let openCheck = false;
let reader = null;
let options = {
    baudRate: 115200,
    bufferSize: 255,
};

async function disconnectSerial() {
    return new Promise(async (resolve, reject) => {
        try {
            if (!openCheck) {
                console.log('No Device connected via Serial Port...');
            }
            console.log('Closing Serial Port...');

            if (reader) {
                await reader.cancel();
                await reader.releaseLock();
            }

            await port.close();
            openCheck = false;
            port = null;
            reader = null;
            isConnected = false;
            connectionButton.innerHTML = "Connect Serial";

            // Re-enable Connect BLE when Disconnect Serial is clicked
            document.getElementById("drawerConnectBLE").classList.remove("disabled-link");

            resolve(isConnected);
            Controller.isConnected = false;
        } catch (error) {
            console.error(error);
            reject(false);
        }
    });

}

async function connectSerial(domElementConnect) {
    return new Promise(async (resolve, reject) => {
        try {
            connectionButton = domElementConnect
            port = await navigator.serial.requestPort();
            const info = await port.getInfo();
            console.log("The Device has been connected.");
            console.log(info);
            console.log("Opening the Serial Port with Baud Rate - 115200 ");
            await port.open(options);
            openCheck = true;
            console.log("The Port is opened for Reading/Writing");
            isConnected = true
            connectionButton.innerHTML = "Disconnect Serial";

            // Disable Connect BLE when Connect Serial is clicked
            document.getElementById("drawerConnectBLE").classList.add("disabled-link");

            resolve(isConnected);
            Controller.isConnected = true;
        } catch (error) {
            console.log(error);
            alert("Error Connecting to Serial Port: " + error.message);
            await disconnectSerial();
            reject(false);
        }
    });
}

async function readDataSerial(onData) {
    reader = port.readable.getReader();
    if (openCheck && reader) {
        try {
            while (openCheck) {
                console.log("Reading..");
                const { value, done } = await reader.read();
                if (done) {
                    console.log("Done..");
                    this.open = false;
                    break;
                }
                let decoded = decoder.decode(value);
                onData(decoded);
            }
        }
        catch (error) {
            console.error('Reading Error : ', error);
            if (error.message.includes("lost") || error.name === "NetworkError") {
                document.getElementById("drawerConnectionSerialText").innerHTML = "Connect Serial";
                document.getElementById("drawerStreamingText").innerHTML = "Start Streaming";
                Controller.doStop()
            }
        } finally {
            reader.releaseLock();
        }
    }
}

async function writeDataSerial(parameterData) {
    return new Promise(async (resolve, reject) => {
        if (port) {
            const writer = port.writable.getWriter();
            if (!parameterData) {
                reject(false);
                return;
            }
            try {
                await writer.write(encoder.encode(parameterData + '\n'));
                console.log(`Command Sent: ${parameterData}`);
                // Wait for the writer to be released before resolving
                await writer.releaseLock();
                resolve(true);
            } catch (error) {
                console.error('Error sending data:', error);
                reject(false);
            } finally {
                // Ensure the writer is released in case of an error
                writer.releaseLock();
            }
        } else {
            reject(false);
        }
    });
}


let bleNusCharRxUuid = '6e400002-b5a3-f393-e0a9-e50e24dcca9e';
let bleNusServiceUuid = '6e400001-b5a3-f393-e0a9-e50e24dcca9e';
let bleNusCharTxUuid = '6e400003-b5a3-f393-e0a9-e50e24dcca9e';
let bleDevice = null;
let bleServer = null;
let nusService = null;
let rxCharacteristic = null;
let txCharacteristic = null;

async function connectBLE(handleData, domElementConnect) {
    return new Promise(async (resolve, reject) => {
        try {
            connectionButton = domElementConnect;
            console.log('Requesting Bluetooth Device...');
            bleDevice = await navigator.bluetooth.requestDevice({
                filters: [{ services: [bleNusServiceUuid] }]
            });

            console.log('Found ' + bleDevice.name);
            console.log('Connecting to GATT Server...');
            bleDevice.addEventListener('gattserverdisconnected', disconnectBLE);
            bleServer = await bleDevice.gatt.connect();

            console.log('Locate NUS service');
            nusService = await bleServer.getPrimaryService(bleNusServiceUuid);
            console.log('Found NUS service: ' + nusService.uuid);

            console.log('Locate RX characteristic');
            rxCharacteristic = await nusService.getCharacteristic(bleNusCharRxUuid);
            console.log('Found RX characteristic');

            console.log('Locate TX characteristic');
            txCharacteristic = await nusService.getCharacteristic(bleNusCharTxUuid);
            console.log('Found TX characteristic');

            console.log('Enable notifications');
            await txCharacteristic.startNotifications();

            console.log('Notifications started for reading.');

            txCharacteristic.addEventListener('characteristicvaluechanged', (event) => {
                readDataBLE(event, handleData);
            });

            isConnected = true;
            connectionButton.innerHTML = "Disconnect BLE";

            // Disable Connect Serial when Connect BLE is clicked
            document.getElementById("drawerConnectSerial").classList.add("disabled-link");

            resolve(txCharacteristic);
            Controller.isConnected = true;

        } catch (error) {
            console.log('' + error);
            if (bleDevice && bleDevice.gatt.connected) {
                bleDevice.gatt.disconnect();
            }
            reject(false);
        }
    });
}

function readDataBLE(event, onData) {
    let value = event.target.value;
    let decoded = decoder.decode(value);
    onData(decoded);
}

async function writeDataBLE(parameterData) {
    if (bleDevice && bleDevice.gatt.connected) {
        try {
            await rxCharacteristic.writeValue(encoder.encode(parameterData + '\n'));
            console.log(`Command Sent : ${parameterData}`);
        } catch (error) {
            console.log("DOMException: GATT operation already in progress.");

            if (isConnected) {
                await new Promise(resolve => setTimeout(resolve, 500));
                try {
                    await rxCharacteristic.writeValue(encoder.encode(parameterData + '\n'));
                } catch (retryError) {
                    console.error("Retry failed: ", retryError);
                }
            } else {
                console.log("Device disconnected.");
            }
        }
    } else {
        console.log("Device not connected.");
        alert("Device not connected. Please reconnect the device.");
    }
}

function disconnectBLE() {
    return new Promise(async (resolve, reject) => {
        try {
            if (!bleDevice) {
                console.log('No Bluetooth Device connected...');
                return;
            }
            console.log('Disconnecting from Bluetooth Device...');
            if (bleDevice.gatt.connected) {
                bleDevice.gatt.disconnect();
                console.log('Bluetooth Device Disconnected: ' + bleDevice.gatt.connected);
                bleDevice = null;
                bleServer = null;
                nusService = null;
                rxCharacteristic = null;
                txCharacteristic = null;
            } else {
                console.log('Bluetooth Device is already disconnected');
            }
            isConnected = false;
            connectionButton.innerHTML = "Connect BLE";

            // Re-enable Connect Serial when Connect BLE is clicked
            document.getElementById("drawerConnectSerial").classList.remove("disabled-link");

            resolve(isConnected);
            Controller.isConnected = false;
        } catch (error) {
            console.error(error);
            reject(false);
        }
    });
}