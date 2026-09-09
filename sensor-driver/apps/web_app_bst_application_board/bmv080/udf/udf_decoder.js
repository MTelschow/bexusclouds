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

/**
 * 
 * @param {FileReader} reader 
 * @param {File} file 
 */
function readFile(reader, file) {
    return new Promise((resolve, reject) => {
        reader.onload = (event) => {
            const arrayBuffer = event.target.result;
            let tempBuffer = arrayBuffer;

            let searchString;
            let endOfHeader;
            let headerSchema;
            let headerArray;

            if (tempBuffer.slice(0, 3) === "1.1" || tempBuffer.slice(0, 3) === "1.2") {
                console.log("version 1.1");
                searchString = "\r\n\r\n\r\n";
                endOfHeader = arrayBuffer.indexOf(searchString);
                headerSchema = arrayBuffer.slice(0, endOfHeader);
                headerArray = headerSchema.split(/\r\n/);
                endOfHeader = endOfHeader + 5;

            } else if (tempBuffer.slice(0, 3) === "1.0") {
                searchString = "\n\n";
                endOfHeader = arrayBuffer.indexOf(searchString);
                headerSchema = arrayBuffer.slice(0, endOfHeader);
                headerArray = headerSchema.split(/\n/);
                endOfHeader = endOfHeader + 1;
            }

            let schemata = createSchemaFromHeader(headerArray);

            let schemaLists = populateSchemaLists(schemata);
            let returnValue = valuesFromByteArray(file, endOfHeader, schemata, schemaLists);

            returnValue.then((udfObject) => {
                resolve(udfObject);
            }).catch(error => {
                console.error("Error processing UDF data:", error);
                reject(error);
            });
        };

        reader.onerror = function () {
            console.error("Error reading file:", reader.error);
            reject(reader.error);
        };

        reader.readAsText(file);
    });
}

function populateSchemaLists(schemata) {
    let schemaLists = {
        schemaIndexList : [],
        schemaEventSizeList : [],
        schemaDtypeList : [],
        schemaBytesList : [],
        schemaScalingFactorList : [],
        schemaPropertiesList : [],
        schemaSampleRateList : [],
    }
    Object.entries(schemata).forEach(([index, schema]) => {
        schemaLists.schemaIndexList.push(parseInt(index, 10));
        schemaLists.schemaEventSizeList.push(schema._eventSize);
        schemaLists.schemaDtypeList.push(schema._dataType);
        schemaLists.schemaBytesList.push(schema._sizeInBytes);
        schemaLists.schemaScalingFactorList.push(schema._scalingFactor);
        schemaLists.schemaPropertiesList.push(schema._propertiesObj);
        schemaLists.schemaSampleRateList.push(schema._samplingRate);
    });
    return schemaLists;
}

/**
 * 
 * @param {File} file 
 * @param {Number} endOfHeader 
 * @param {Object} schemata 
 * @param {Object} schemaLists 
 */
function valuesFromByteArray(file, endOfHeader, schemata, schemaLists) {

    return new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = (event) => {
            const arrayBuffer = event.target.result;

            let uint8ArrayBuffer = new Uint8Array(arrayBuffer);

            while (uint8ArrayBuffer[endOfHeader] === 10) { // 0x0A
                endOfHeader = endOfHeader + 1;
            }

            uint8ArrayBuffer = uint8ArrayBuffer.subarray(endOfHeader, uint8ArrayBuffer.length);
            resolve(udfDecoder(uint8ArrayBuffer, schemata, schemaLists));
        };

        reader.onerror = function () {
            console.error("Error reading file:", reader.error);
            reject(reader.error);
        };

        reader.readAsArrayBuffer(file);
    });
}

/**
 * 
 * @param {Uint8Array} uint8ArrayBuffer 
 * @param {Object} schemata 
 * @returns 
 */
function udfDecoder(uint8ArrayBuffer, schemata, schemaLists) {
    let cursor = 0;
    let timestamps = [];
    let timeStamp = 0;
    let nTimestamps = 0;
    let labels = [];
    let label = null;

    let tempSchemata = {};
    let length = uint8ArrayBuffer.length;

    let lastRelativeTimeStamp = null;

    while (cursor < length) {
        let schemaEventId = uint8ArrayBuffer[cursor];
        let value = 0;

        if ([240, 241, 242, 249, 250, 251].includes(schemaEventId)) { //timestamps - only for 8bytes
            cursor += 1;
            if (cursor + 8 > length) {
                console.warn("Timestamp is Incomplete");
                break;
            }
            let timestampBytes = uint8ArrayBuffer.subarray(cursor, cursor + 8);
            timeStamp = uint8ToUint64(timestampBytes);
            timestamps.push(timeStamp);
            nTimestamps += 1;
            cursor += 8;
            lastRelativeTimeStamp = timeStamp;
        }
        else if ([243, 244, 245].includes(schemaEventId)) { //relative timestamps
            cursor += 1;
            if (cursor + 4 > length) {
                console.warn("Relative Timestamp is Incomplete");
                break;
            }
            let timestampBytes = uint8ArrayBuffer.subarray(cursor, cursor + 4);
            let relativeTimeStamp = uint8ToUint32(timestampBytes);
            if (lastRelativeTimeStamp === null) {
                console.error("Relative Timestamps can't be used without a previous Absolute Timestamp");
                break;
            }
            timeStamp = lastRelativeTimeStamp + relativeTimeStamp;
            timestamps.push(timeStamp);
            nTimestamps += 1;
            lastRelativeTimeStamp = timeStamp;
            cursor += 4;
            if (uint8ArrayBuffer[cursor] !== 248) {
                labels.push(null);
                label = null;
            }
        }
        else if (schemaEventId === 248) { //labels
            lastSchemaIndex = schemaEventId;
            cursor += 1;
            if (cursor + 16 > length) {
                console.warn("Label is Incomplete");
                break;
            }
            let labelBytes = uint8ArrayBuffer.subarray(cursor, cursor + 16);
            if (labelBytes.length !== 16) {
                console.error("The labels are not in the correct format");
                break;
            }
            label = uint8ArrayToString(labelBytes);
            labels.push(label);
            cursor += 16;
            lastRelativeTimeStamp = timeStamp;

        } else if (schemaLists.schemaIndexList.includes(schemaEventId)) { // data
            let currentSchemaIndex = schemaLists.schemaIndexList.findIndex(index => index === schemaEventId);
            let sizeBytes = schemaLists.schemaBytesList[currentSchemaIndex];
            let dataType = schemaLists.schemaDtypeList[currentSchemaIndex];
            let scalingFactor = schemaLists.schemaScalingFactorList[currentSchemaIndex];
            let properties = schemaLists.schemaPropertiesList[currentSchemaIndex];

            cursor += 1;

            if (dataType[0] === "vls") {
                let tempCursor = cursor;
                while (tempCursor < length) {
                    if (uint8ArrayBuffer[tempCursor] === 0)
                        break;
                    else
                        tempCursor = tempCursor + 1;
                }
                let valueBytes = uint8ArrayBuffer.subarray(cursor, tempCursor);
                let nBytes = tempCursor - cursor;
                if (valueBytes.length !== nBytes) {
                    console.error("Size Mismatch " + valueBytes.length + " " + nBytes);
                    return;
                } else {
                    if (properties.signalType === "JSON") {
                        value = JSON.parse(uint8ArrayToString(valueBytes).replace(/'/g, '"'));
                        console.log(value);
                    } else {
                        value = uint8ArrayToString(valueBytes);
                    }
                }
                schemata[schemaEventId].addValue(0, value);
                schemata[schemaEventId].addTimestampIndex(0, nTimestamps - 1);
                cursor = tempCursor + 1;
            } else {
                for (let idx = 0; idx < sizeBytes.length; idx++) {
                    let nBytes = sizeBytes[idx][0];
                    let valueBytes = uint8ArrayBuffer.subarray(cursor, cursor + nBytes);
                    if (valueBytes.length !== nBytes) {
                        console.error("Size Mismatch " + valueBytes.length + " " + nBytes);
                        return;
                    } else {
                        let typeIdentifier = dataType[idx];
                        value = DataType.dataConversionMap[typeIdentifier](valueBytes);
                    }
                    schemata[schemaEventId].addValue(idx, value);
                    if (scalingFactor > 0)
                        schemata[schemaEventId].addScaledValue(idx, value * scalingFactor);

                    schemata[schemaEventId].addTimestampIndex(idx, nTimestamps - 1);
                    cursor += nBytes;
                }
            }
            schemata[schemaEventId]._timeStamps.push(timeStamp);
            schemata[schemaEventId]._streamTimeStamps.push(timeStamp);
            schemata[schemaEventId]._labels.push(label);

        } else if (cursor <= length) {
            console.error(`Error parsing ${schemaEventId} (0x${schemaEventId.toString(16)}) @ ${cursor - 1} (0x${(cursor - 1).toString(16)})
            Can't read Values from file. File may not be readable!`);
            return;
        }
    }
    Object.keys(schemata).forEach(idx => {
        const schema = schemata[idx];
        if (Object.keys(schema._values).length > 0) {
            tempSchemata[idx] = schema;
            Schema.filledSchemaList.push(Number(idx));
        }
    });

    return { "schemata": tempSchemata, "timeStamps": timestamps, "labels": labels };
}

function streamUdfDecoder(uint8ArrayBuffer, schemata, schemaLists) {
    let cursor = 0;
    let timeStamp = 0;
    let label = "";

    let timestamps = [];
    let labels = [];

    let length = uint8ArrayBuffer.length;

    while (cursor < length) {
        let schemaEventId = uint8ArrayBuffer[cursor];
        let value = 0;

        if ([240, 241, 242, 249, 250, 251].includes(schemaEventId)) { //timestamps - only for 8bytes
            timeStampBeforeData = true;
            cursor += 1;
            let timestampBytes = uint8ArrayBuffer.subarray(cursor, cursor + 8);
            timeStamp = uint8ToUint64(timestampBytes);
            timestamps.push(timeStamp);
            cursor += 8;
        }
        else if (schemaEventId === 248) { //labels
            console.log("true");
            lastSchemaIndex = schemaEventId;
            cursor += 1;
            let labelBytes = uint8ArrayBuffer.subarray(cursor, cursor + 16);
            if (labelBytes.length !== 16) {
                console.error("The labels are not in the correct format");
                break;
            }
            label = uint8ArrayToString(labelBytes);
            labels.push(label);
            cursor += 16;
        }
        else if (schemaLists.schemaIndexList.includes(schemaEventId)) { // data
            let currentSchemaIndex = schemaLists.schemaIndexList.findIndex(index => index === schemaEventId);
            let sizeBytes = schemaLists.schemaBytesList[currentSchemaIndex];
            let dataType = schemaLists.schemaDtypeList[currentSchemaIndex];
            let scalingFactor = schemaLists.schemaScalingFactorList[currentSchemaIndex];

            cursor += 1;

            for (let idx = 0; idx < sizeBytes.length; idx++) {
                let nBytes = sizeBytes[idx][0];
                let valueBytes = uint8ArrayBuffer.subarray(cursor, cursor + nBytes);
                if (valueBytes.length !== nBytes) {
                    console.error("Size Mismatch " + valueBytes.length + " " + nBytes);
                } else {
                    let typeIdentifier = dataType[idx];
                    value = DataType.dataConversionMap[typeIdentifier](valueBytes);
                }
                schemata[schemaEventId].addValue(idx, value);
                if (scalingFactor > 0) {
                    schemata[schemaEventId].addScaledValue(idx, (value * scalingFactor));
                }
                cursor += nBytes;
            }
            schemata[schemaEventId]._timeStamps.push(timeStamp);
            schemata[schemaEventId]._streamTimeStamps.push(timeStamp);
            schemata[schemaEventId]._labels.push(label);

        } else if (cursor <= length) {
            console.error(`Error parsing ${schemaEventId} (0x${schemaEventId.toString(16)}) @ ${cursor - 1} (0x${(cursor - 1).toString(16)})
            Can't read Values from file. File may not be readable!`);
            return;
        }
    }

    return { "schemata": schemata, "timeStamps": timestamps, "labels": labels };
}

function createSchemaFromHeader(headerArray) {
    let version = headerArray.splice(0, 1)[0];

    let schemata = {};

    if (version === "1.0") {
        headerArray.forEach(schemas => {
            let schema = schemas.split(":");
            let eventSize = schema[2].trim();
            let axisNames = schema[4].split(",").map(axis => axis.trim());
            let dataTypes = schema[3].split(",").map(data => data.trim());
            let size = dataTypes.map(type => getUdfLength(type));

            // Schema verification
            const totalSize = size.map(x => Number(x)).reduce((acc, curr) => acc + curr, 0);
            if (totalSize !== Number(eventSize)) {
                console.error(`Schema Error: Schema's (${schema[0]}) Event Size (${eventSize}) doesn't match the Byte Size total of the datatypes (${totalSize})`);
                return;
            }

            schemata[parseInt(schema[0])] = new Schema(
                parseInt(schema[0]),
                schema[1],
                size,
                eventSize,
                dataTypes,
                axisNames,
                parseFloat(schema[5]),
                -1,
                "na",
            );
        });
        return schemata;

    } else if (version === "1.1" || version === "1.2") {
        headerArray.forEach(schemas => {
            let schema = schemas.split(":");
            let eventSize = schema[2].trim();
            let axisNames = schema[4].split(",").map(axis => axis.trim());
            let dataTypes = schema[3].split(",").map(data => data.trim());

            if (dataTypes.includes("fls") && !Object.keys(DataType.dataConversionMap).includes("fls")) {
                DataType.dataTypes.push(new DataType("fls", parseInt(eventSize)));
                DataType.dataConversionMap.fls = uint8ArrayToString;
            } else if (dataTypes.includes("vls") && !Object.keys(DataType.dataConversionMap).includes("vls")) {
                DataType.dataTypes.push(new DataType("vls", 0));
                DataType.dataConversionMap.vls = uint8ArrayToString;
            } else if (dataTypes.includes("flb") && !Object.keys(DataType.dataConversionMap).includes("flb")) {
                DataType.dataTypes.push(new DataType("flb", parseInt(eventSize)));
                DataType.dataConversionMap.flb = uint8ArrayToFixedLengthBinary;
            }

            if (DataType.stringDataTypes.includes(dataTypes[0]))
                DataType.stringDataTypeIndex.push(schema[0]);

            let size = dataTypes.map(type => getUdfLength(type));
            let propertiesObj = {};
            let properties = schema[7].split(",").map(prop => prop.trim());

            properties.forEach((property, index) => {
                if (property.includes("=")) {
                    let temp = property.split("=");
                    propertiesObj[`${temp[0]}`] = temp[1];
                } else {
                    propertiesObj.data = property;
                }
            });

            // Schema verification
            const totalSize = size.map(x => Number(x)).reduce((acc, curr) => acc + curr, 0);
            if (totalSize !== Number(eventSize)) {
                console.error(`Schema Error: Schema's (${schema[0]}) Event Size (${eventSize}) doesn't match the Byte Size total of the datatypes (${totalSize})`);
                return;
            }

            schemata[parseInt(schema[0])] = new Schema(
                parseInt(schema[0]),
                schema[1],
                size,
                eventSize,
                dataTypes,
                axisNames,
                parseFloat(schema[5]),
                parseFloat(schema[6]),
                properties,
                propertiesObj
            );
        });
        return schemata;

    } else {
        console.error("Unsupported UDF Schema version");
    }
}
