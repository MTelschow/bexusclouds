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

// Message handling arrays
let tempSchema = [];
let tempStreamBuffer = [];
let tempErrorBuffer = [];
let dataBuffer = [];
let exportBuffer = "";
// Objects for parsing and schema context
let staticSchemata = null;
let schemaLists = null;
let lastCommandSent = "";
let csvStorage = [];
const MAX_SIZE = 3600;

// Ensuring that the measurement data accumulated in the array does not exceed the maximum size
function addToCsvStorage(newData) {
    if (csvStorage.length >= MAX_SIZE) {
        csvStorage.shift(); // Remove the oldest element
    }
    csvStorage.push(newData); // Add the new element
}

// Handling incoming data from device
function handleData(decoded) {
    console.log("Decoded : " + decoded)
    if (lastCommandSent.includes("schema")) {
        handleSchemaData(decoded);
    } else if (lastCommandSent.includes("cfgse")) {
        handleStreamData(decoded);
        handleMeasurementError(decoded);
    } else if (lastCommandSent.includes("bmvSettings")) {
        handleBMVData(decoded);
    } else {
        handleBufferData(decoded);
    }
}

let lastStreamDataTime = null;
let streamDataTimeoutId = null;

function resetStreamDataTimeout() {
    if (streamDataTimeoutId) {
        clearTimeout(streamDataTimeoutId);
    }
    timeoutDuration = 5000; // 5 seconds
    if (localStorage.getItem('IsDutyCyclingEnabled') == "1") {
        timeoutDuration += Number(localStorage.getItem('DutyCyclingPeriod')) * 1000;
    } 

    streamDataTimeoutId = setTimeout(() => {
        if (Controller && Controller.state === "running") {
            alert("No data received from the device. The measurement will be stopped. Please check the connection and power cycle the Application Board.");
            // Simulate a click to stop streaming
            document.getElementById("drawerStreamingText").click();
        }
    }, timeoutDuration);
}


function handleStreamData(decoded) {

    lastStreamDataTime = Date.now();
    resetStreamDataTimeout();

    dataBuffer.push(decoded);
    if (decoded.includes("\r\n")) {
        const fullBuffer = dataBuffer.join('');
        const startIdx = fullBuffer.indexOf("[H]");
        const endIdx = fullBuffer.indexOf("\r\n", startIdx);

        if (startIdx !== -1 && endIdx !== -1) {
            const extractedData = fullBuffer.slice(startIdx + 3, endIdx);
            const extractedDataArray = parseHexData(extractedData);
            exportBuffer = exportBuffer.concat(extractedData)
            dataBuffer = [];
            const decodedData = streamUdfDecoder(new Uint8Array(extractedDataArray), staticSchemata, schemaLists);

            // pm1,pm25,pm10,nc1,nc25,nc10,obs,range,r0,r1,r2
            const pm1Data = decodedData.schemata[239]._streamValues[0].slice(-1)[0];
            const pm25Data = decodedData.schemata[239]._streamValues[1].slice(-1)[0];
            const pm10Data = decodedData.schemata[239]._streamValues[2].slice(-1)[0];
            const obsData = decodedData.schemata[239]._streamValues[3].slice(-1)[0];
            const rangeData = decodedData.schemata[239]._streamValues[4].slice(-1)[0];
            const n_pm1 = decodedData.schemata[239]._streamValues[5].slice(-1)[0];
            const n_pm25 = decodedData.schemata[239]._streamValues[6].slice(-1)[0];
            const n_pm10 = decodedData.schemata[239]._streamValues[7].slice(-1)[0];
            const r0 = decodedData.schemata[239]._streamValues[8].slice(-1)[0];
            const r1 = decodedData.schemata[239]._streamValues[9].slice(-1)[0];
            const r2 = decodedData.schemata[239]._streamValues[10].slice(-1)[0];
            const time = decodedData.schemata[239]._timeStamps.slice(-1)[0];

            console.log(`pm1 : ${pm1Data} , pm25 : ${pm25Data} , pm10 : ${pm10Data} ,  
                n_pm1 : ${n_pm1}, n_pm25 : ${n_pm25}, n_pm10 : ${n_pm10}, obs : ${obsData}, range : ${rangeData}, 
                r0 : ${r0}, r1 : ${r1}, r2 : ${r2}`);
            if (Controller.obstructionDetection === "1") {
                Controller.notifyObstruction(obsData);
            }
            const currentTime = useSystemTime ? new Date() : new Date(measurementStartTime.getTime() + Math.round(time) * s2ms);
            const [month, day, year, hour, minutes, seconds] = [ currentTime.getMonth()+1, currentTime.getDate(), currentTime.getFullYear(), currentTime.getHours(), currentTime.getMinutes(), currentTime.getSeconds()];
            const currentTimeString = `${year}${month.toString().padStart(2, '0')}${day.toString().padStart(2, '0')}T` +
                `${hour.toString().padStart(2, '0')}${minutes.toString().padStart(2, '0')}${seconds.toString().padStart(2, '0')}`;
            addToCsvStorage([currentTimeString, pm1Data, pm25Data, pm10Data, n_pm1, n_pm25, n_pm10, obsData, rangeData, r0, r1, r2]);
            updateCharts([pm1Data, pm25Data, pm10Data], currentTime);
        }
    }
}

function handleBufferData(decoded) {
    tempStreamBuffer.push(decoded);

    if (decoded.includes("\r\n")) {
        const fullBuffer = tempStreamBuffer.join('');
        const shuttleBloardIdMatch = decoded.match(/Shuttle ID\s*(\S+)/);
        if (shuttleBloardIdMatch[1] != '0x197') {
            alert(`Shuttle Board Id ${shuttleBloardIdMatch[1]} not in the set of known Ids.`);
        }
        console.log(fullBuffer);
        
        tempStreamBuffer = [];
    }
}


function handleMeasurementError(decoded) {
    if (!(Controller && Controller.state === "running"))
        return;

    tempErrorBuffer.push(decoded);

    if (decoded.includes("\r\n")) {
        const errorString = tempErrorBuffer.join('');
        const searchString = "[E][BMV] ";
        startIdx = -1;
        endIdx = -1;
        // Check if error reported and extract the error information
        if( errorString.includes(searchString)) {
            startIdx = errorString.indexOf(searchString);
            endIdx = errorString.indexOf("\r\n", startIdx + searchString.length);
            // Only proceed if \r\n appears after searchString
            if (endIdx !== -1) {

                const extractedData = errorString.slice(startIdx + searchString.length, endIdx);
                console.log(tempErrorBuffer);
                tempErrorBuffer = [];
                alert(`Measurement failed: ${extractedData}.`);

                // Simulate a click to stop streaming
                document.getElementById("drawerStreamingText").click();
            }
        }
        if(startIdx === -1 && endIdx === -1) {
            tempErrorBuffer = [];
        }
    }
}

function handleBMVData(decoded) {
    if (decoded.includes("\r\n")) {
        const sensorIdMatch = decoded.match(/Sensor ID:\s*(\S+)/);
        const versionMatch = decoded.match(/\[V\](\S+)/);
        console.log(sensorIdMatch)
        console.log(versionMatch)
        if (sensorIdMatch) {
            document.getElementById("asicTrackerIdChannel1Label").innerText = sensorIdMatch[1];
        }
        if (versionMatch) {
            document.getElementById("sensorStackVersionLabel").innerText = versionMatch[1];
        }
    }
}

function handleSchemaData(decoded) {
    tempSchema.push(decoded);
    if (tempSchema.join('').includes("\r\n\r\n\r\n")) {
        const fullSchema = tempSchema.join('');
        exportBuffer = exportBuffer.concat(fullSchema);
        let testSchema = fullSchema.split("\r\n\r\n\r\n")[0];
        const splitSchema = testSchema.split("\r\n");
        console.log(splitSchema);
        staticSchemata = createSchemaFromHeader(splitSchema);
        schemaLists = populateSchemaLists(staticSchemata);
        console.log(staticSchemata);
        tempSchema = [];
    }
}

function writeData(input) {
    const commandMap = new Map([
        ["schema", "schema"],
        ["cfgse", "cfgse"],
        ["reset", "reset"],
        ['bmv', 'bmvSettings']
    ]);

    for (const [key, value] of commandMap) {
        if (input.includes(key)) {
            lastCommandSent = value;
            if (value === "reset") {
                document.getElementById("drawerStreamingText").innerHTML = "Start Streaming";
            }
            break;
        }
    }

    if (bleDevice && openCheck === false) {
        return writeDataBLE(input);
    } else {
        return writeDataSerial(input);
    }

}

function exportData() {
    var sizeCsvStorage = csvStorage.length;
    if (sizeCsvStorage < 1) {
        alert("No data to export. Please start streaming first.");
        return;
    }
    suggestedFileName = `${csvStorage[0][0]}_bmv080Output`;
    const fileName = prompt("Enter a file name", suggestedFileName)
    if (fileName) {
        // get the start time of the measurement
        const [month, day, year, hour, minutes, seconds] = [ measurementStartTime.getMonth()+1, measurementStartTime.getDate(), measurementStartTime.getFullYear(), measurementStartTime.getHours(), measurementStartTime.getMinutes(), measurementStartTime.getSeconds()];
        const measurementStartTimeString = `${year}${month.toString().padStart(2, '0')}${day.toString().padStart(2, '0')}T` + `${hour.toString().padStart(2, '0')}${minutes.toString().padStart(2, '0')}${seconds.toString().padStart(2, '0')}`;
        // the header with the measurement settings
        // and the column names   
        var measurementSettings = `HEADER_START\n` +
            `# This file is generated by the BMV080 Web App\n` +
            `WebAppVersion="${document.getElementById("androidVersionLabel").innerText}"\n` +
            `SensorDriverVersion="${document.getElementById("sensorStackVersionLabel").innerText}"\n` +
            `SensorId="${document.getElementById("asicTrackerIdChannel1Label").innerText}"\n` +
            `ObstructionDetection="${localStorage.getItem('ObstructionDetection')}"\n` +
            `IntegrationTime="${localStorage.getItem('IntegrationTime')}"\n` +
            `DutyCycling="${localStorage.getItem('IsDutyCyclingEnabled')}"\n` +
            `DutyCyclingPeriod="${localStorage.getItem('DutyCyclingPeriod')}"\n` +
            `MeasurementAlgorithm="${localStorage.getItem('MeasurementAlgorithm')}"\n` +
            `ProcessingDate="${measurementStartTimeString}"\n` +
            `HEADER_END\n` +
            "ISO Time Code;PM1 mass concentration [µg/m³];PM2.5 mass concentration [µg/m³];PM10 mass concentration [µg/m³];"+
            "PM1 number concentration [particles/cm³];PM2.5 number concentration [particles/cm³];PM10 number concentration [particles/cm³];"+
            "Obstruction Flag;Outside Measurement Range Flag;Reserved 0;Reserved 1;Reserved 2\n" +
            "yyyymmddTHHMMSS;µg/m³;µg/m³;µg/m³;particles/cm³;particles/cm³;particles/cm³;-;-;-;-;-\n"+
            "String;Double;Double;Double;Double;Double;Double;Boolean;Boolean;Double;Double;Double\n"
        var csvContent = measurementSettings + csvStorage.map(e => e.join(";")).join("\n");
        var bom = "\uFEFF";
        var blob = new Blob([bom + csvContent], { type: 'text/csv;charset=utf-8;' });
        var link = document.createElement("a");
        var url = URL.createObjectURL(blob);
        link.setAttribute("href", url);
        link.setAttribute("download", `${fileName}.csv`);
        link.style.visibility = 'hidden';
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        // clear array with stored measurement data in place
        // for the next file export
        csvStorage.length = 0;
    } else {
        console.error("Filename Not entered.")
    }
}

function hexStringToByteArray(hexString) {
    const bytes = new Uint8Array(hexString.length / 2);
    for (let i = 0; i < hexString.length; i += 2) {
        bytes[i / 2] = parseInt(hexString.substr(i, 2), 16);
    }
    return bytes;
}

function parseHexData(data) {
    const length = data.length;
    const extractedDataArray = new Array(length / 2); // Preallocate array
    for (let index = 0, j = 0; index < length; index += 2, j++) {
        const hexPair = data[index] + data[index + 1];
        extractedDataArray[j] = parseInt(hexPair, 16);
    }
    return extractedDataArray;
}