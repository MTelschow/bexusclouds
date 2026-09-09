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

class DataType {

    static dataTypes = []
    static dataConversionMap = {}
    static stringDataTypes = ["st", "c", "fls", "vls", "flb"] // datatypes whose value is to be displayed as a string
    static stringDataTypeIndex = []
    /**
     * 
     * @param {String} udfType 
     * @param {*} length 
     */
    constructor(udfType, length) {
        this.udfType = udfType
        this.length = length
    }
}

function loadStaticDataTypes() {
    DataType.dataTypes.push(new DataType("s8", 1))
    DataType.dataConversionMap.s8 = uint8ToInt8

    DataType.dataTypes.push(new DataType("u8", 1))
    DataType.dataConversionMap.u8 = uint8ToUint8

    DataType.dataTypes.push(new DataType("s16", 2))
    DataType.dataConversionMap.s16 = uint8ToInt16

    DataType.dataTypes.push(new DataType("u16", 2))
    DataType.dataConversionMap.u16 = uint8ToUint16

    DataType.dataTypes.push(new DataType("s24", 3))
    DataType.dataConversionMap.s24 = uint8ToInt24

    DataType.dataTypes.push(new DataType("u24", 3))
    DataType.dataConversionMap.u24 = uint8ToUint24

    DataType.dataTypes.push(new DataType("s32", 4))
    DataType.dataConversionMap.s32 = uint8ToInt32

    DataType.dataTypes.push(new DataType("u32", 4))
    DataType.dataConversionMap.u32 = uint8ToUint32

    DataType.dataTypes.push(new DataType("s64", 8))
    DataType.dataConversionMap.s64 = uint8ToInt64

    DataType.dataTypes.push(new DataType("u64", 8))
    DataType.dataConversionMap.u64 = uint8ToUint64

    DataType.dataTypes.push(new DataType("f", 4))
    DataType.dataConversionMap.f = uint8ToFloat

    DataType.dataTypes.push(new DataType("d", 8))
    DataType.dataConversionMap.d = uint8ToDouble

    DataType.dataTypes.push(new DataType("st", 16))
    DataType.dataConversionMap.st = uint8ArrayToString

    DataType.dataTypes.push(new DataType("c", 1))
    DataType.dataConversionMap.c = uint8ArrayToString
}

function getUdfLength(udfType) {
    return DataType.dataTypes.filter((dataType) => dataType.udfType === udfType).map((dataType) => dataType.length)
}

function uint8ToUint8(uint8Array) {
    let littleEndianValue = uint8Array[0]; // Combine bytes
    return littleEndianValue;
}

function uint8ToInt8(uint8Array) {
    let littleEndianValue = new Int8Array(uint8Array); // Combine bytes
    return littleEndianValue[0];
}

function uint8ToUint16(uint8Array) {
    if (uint8Array.length % 2 !== 0) {
        throw new Error("Uint8Array length must be a multiple of 2");
    }
    let uint16Array = new Uint16Array(uint8Array)
    let littleEndianValue = (uint16Array[1] << 8) | uint16Array[0]; // Combine bytes
    return littleEndianValue;
}

function uint8ToInt16(uint8Array) {
    if (uint8Array.length % 2 !== 0) {
        throw new Error("Uint8Array length must be a multiple of 2");
    }
    let int16Array = new Int16Array(uint8Array)
    let littleEndianValue = (int16Array[1] << 8) | int16Array[0]; // Combine bytes
    // Check if the number is negative (if the 15th bit is 1)
    if (littleEndianValue & 0x8000) { // 0x8000 = 1000 0000 0000 0000 in binary
        littleEndianValue = littleEndianValue - 0x10000; // Subtract 2^16 to convert to signed value
    }
    return littleEndianValue;
}


function uint8ToUint32(uint8Array) {
    if (uint8Array.length % 4 !== 0) {
        throw new Error("Uint8Array length must be a multiple of 4");
    }

    const buffer = new Uint8Array(uint8Array);
    const uint32Array = new Uint32Array(uint8Array.length / 4);
    const dataView = new DataView(buffer.buffer);
    for (let i = 0; i < uint8Array.length; i += 4) {
        const value = dataView.getUint32(i, true); // Read little-endian 64-bit integer
        uint32Array[i / 4] = value;
    }
    return Number(uint32Array[0])
}

function uint8ToInt32(uint8Array) {
    if (uint8Array.length % 4 !== 0) {
        throw new Error("Uint8Array length must be a multiple of 4");
    }
    let int32Array = new Int32Array(uint8Array)
    let littleEndianValue = (int32Array[3] & 0xFF) << 24 | (int32Array[2] & 0xFF) << 16 | (int32Array[1] & 0xFF) << 8 | (int32Array[0] & 0xFF);
    return littleEndianValue;
}

function uint8ToUint64(uint8Array) {
    if (uint8Array.length % 8 !== 0) {
        throw new Error("Uint8Array length must be a multiple of 8");
    }
    const buffer = new Uint8Array(uint8Array);
    const uint64Array = new BigUint64Array(uint8Array.length / 8);
    const dataView = new DataView(buffer.buffer);
    for (let i = 0; i < uint8Array.length; i += 8) {
        const value = dataView.getBigUint64(i, true);
        uint64Array[i / 8] = value;
    }

    // converting to Number for plotting purposes
    if (Number(uint64Array[0]) <= Number.MAX_SAFE_INTEGER)
        return Number(uint64Array[0])
    else
        return Number.MAX_SAFE_INTEGER
}

function uint8ToInt64(uint8Array) {
    if (uint8Array.length % 8 !== 0) {
        throw new Error("Uint8Array length must be a multiple of 8");
    }
    const buffer = new Uint8Array(uint8Array);
    const int64Array = new BigInt64Array(uint8Array.length / 8);
    const dataView = new DataView(buffer.buffer);
    for (let i = 0; i < uint8Array.length; i += 8) {
        const value = dataView.getBigInt64(i, true);
        int64Array[i / 8] = value;
    }

    // converting to Number for plotting purposes
    if (Number(Number.MIN_SAFE_INTEGER <= int64Array[0]) <= Number.MAX_SAFE_INTEGER)
        return Number(int64Array[0])
    else if (Number(int64Array[0]) < Number.MIN_SAFE_INTEGER)
        return Number.MAX_SAFE_INTEGER
    else
        return Number.MAX_SAFE_INTEGER
}

function uint8ToFloat(uint8Array) {
    if (uint8Array.length % 4 !== 0) {
        throw new Error("Uint8Array length must be a multiple of 4");
    }

    const buffer = new Uint8Array(uint8Array);
    const floatArray = new Float32Array(uint8Array.length / 4);
    const dataView = new DataView(buffer.buffer);
    for (let i = 0; i < uint8Array.length; i += 4) {
        const value = dataView.getFloat32(i, true); // Read little-endian 64-bit integer
        floatArray[i / 4] = value;
    }
    return Number(floatArray[0])
}

function uint8ToDouble(uint8Array) {
    if (uint8Array.length % 8 !== 0) {
        throw new Error("Uint8Array length must be a multiple of 8");
    }

    const buffer = new Uint8Array(uint8Array);
    const doubleArray = new Float64Array(uint8Array.length / 8);
    const dataView = new DataView(buffer.buffer);
    for (let i = 0; i < uint8Array.length; i += 8) {
        const value = dataView.getFloat64(i, true); // Read little-endian 64-bit integer
        doubleArray[i / 8] = value;
    }
    return Number(doubleArray[0])
}

function uint8ArrayToString(uint8Array) {
    let decoder = new TextDecoder("utf-8");
    if (!decoder.decode(uint8Array).includes("\x00"))
        return decoder.decode(uint8Array).trim();
    else
        return decoder.decode(uint8Array).split("\x00")[0];
}

function uint8ArrayToFixedLengthBinary(uint8Array) {
    return "0x".concat(parseInt(uint8Array.join(""), 2).toString(16))
}

function uint8ToUint24(uint8Array) {
    if (uint8Array.length % 3 !== 0) {
        throw new Error("Uint8Array length must be a multiple of 3");
    }
    let uint24Array = new Uint32Array(Math.ceil(uint8Array.length / 3));
    for (let i = 0; i < uint24Array.length; i++) {
        let byte1 = uint8Array[i * 3];
        let byte2 = uint8Array[i * 3 + 1];
        let byte3 = uint8Array[i * 3 + 2];
        let value = (byte1 << 16) | (byte2 << 8) | byte3;
        uint24Array[i] = value;
    }
    return Number(uint24Array[0]);
}

function uint8ToInt24(uint8Array) {
    if (uint8Array.length % 3 !== 0) {
        throw new Error("Uint8Array length must be a multiple of 3");
    }
    let value = (uint8Array[0]) | (uint8Array[1] << 8) | (uint8Array[2] << 16);

    if (value & 0x800000) {
        value -= 1 << 24; // Convert to negative using two's complement
    }
    return value;
}