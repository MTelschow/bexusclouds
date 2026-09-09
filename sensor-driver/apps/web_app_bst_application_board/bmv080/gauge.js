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

var isGaugePageLoaded = false;

var defaultButtonValue = "Start";
var defaultGaugeValue = 50;
var gaugeValue = 0;
var gaugePageLoaded = false;

function loadGauge() {
    $("#headline").text("Current Reading");
    $(".tab").css("display", "none");
    $("#gaugeContentWithObstrution").css("display", "flex");
    document.getElementById("mainmenu").classList.remove("mdc-drawer--open");
}

// Convert values to log scale, this is used for the values displayed by the gauge
function convertToLogScale(val) {
    if (val < 0) { // negative values will be displayed as a dash, so just pass them on 
        // textRenderer will take care of that
        return val;
    } else {
        // Workaround for the value zero which is undefined in log scale
        // shift values by 1, 0->1 log(1) = 0 
        return Math.log10(val + 1);
    }
}

gaugePM25 = new JustGage({
    id: "gaugePM25",
    value: gaugeValue,
    min: convertToLogScale(0),
    max: convertToLogScale(1000),
    label: 'µg/m³',
    donut: false,
    title: 'PM2.5',
    gaugeWidthScale: 0.7,
    counter: false,
    hideInnerShadow: true,
    relativeGaugeSize: true,
    pointer: true,
    pointerOptions: {
        toplength: -6,
        bottomlength: -30,
        bottomwidth: 4,
        color: '#000000'
    },
    textRenderer: function (val) {
        if (val > this.max) { val = this.max; }
          
        if (val < 0) {
            return "-"
        } else if (val == 0) {
            return "0";
        } else {
            return Math.round(Math.pow(10, val) - 1);
        }
    },
    customSectors: {
        ranges: [
        {
            color : "#0000FF", //Blue
            lo : 0,
            hi : 15
        },{
            color : "#00FF00", // Green
            lo : 16,
            hi : 35
        },{
            color : "#FFFF00", // Yellow
            lo : 36,
            hi : 75
        },{
            color : "#FF0000", //red
            lo : 76,
            hi : 1000
        }]
    },
    levelColors: ["#008000", "#FFFF00", "#FFC90e", "#ff0000", "#9400D3"],
    noGradient: true,
    gaugeColor: "#b2b3b5",
    titleFontColor: "#000000",
    titlePosition: "above",
    valueFontColor: "#000000",
    labelFontColor: "#212121",
});

gaugePM10 = new JustGage({
    id: "gaugePM10",
    value: gaugeValue,
    min: convertToLogScale(0),
    max: convertToLogScale(1000),
    label: 'µg/m³',
    donut: false,
    title: 'PM10',
    gaugeWidthScale: 0.7,
    counter: false,
    hideInnerShadow: true,
    relativeGaugeSize: true,
    pointer: true,
    pointerOptions: {
        toplength: -6,
        bottomlength: -30,
        bottomwidth: 4,
        color: '#000000'
    },
    textRenderer: function (val) {
        if (val > this.max) { val = this.max; }          
        if (val < 0) {
            return "-"
        } else if (val == 0) {
            return "0";
        } else {
            return Math.round(Math.pow(10, val) - 1);
        }
    },
    customSectors: {
        ranges: [
        {
            color : "#0000FF", //Blue
            lo : 0,
            hi : 15
        },{
            color : "#00FF00", // Green
            lo : 16,
            hi : 35
        },{
            color : "#FFFF00", // Yellow
            lo : 36,
            hi : 75
        },{
            color : "#FF0000", //red
            lo : 76,
            hi : 1000
        }]
    },
    levelColors: ["#008000", "#FFFF00", "#FFC90e", "#ff0000", "#9400D3"],
    noGradient: true,
    gaugeColor: "#b2b3b5",
    titleFontColor: "#000000",
    titlePosition: "above",
    valueFontColor: "#000000",
    labelFontColor: "#212121",
});

gaugePM1 = new JustGage({
    id: "gaugePM1",
    value: gaugeValue,
    min: convertToLogScale(0),
    max: convertToLogScale(1000),
    label: 'µg/m³',
    donut: false,
    title: 'PM1',
    gaugeWidthScale: 0.7,
    counter: false,
    hideInnerShadow: true,
    relativeGaugeSize: true,
    pointer: true,
    pointerOptions: {
        toplength: -6,
        bottomlength: -30,
        bottomwidth: 4,
        color: '#000000'
    },
    textRenderer: function (val) {
        if (val > this.max) { val = this.max; }          
        if (val < 0) {
            return "-"
        } else if (val == 0) {
            return "0";
        } else {
            return Math.round(Math.pow(10, val) - 1);
        }
    },
    customSectors: {
        ranges: [
        {
            color : "#0000FF", //Blue
            lo : 0,
            hi : 15
        },{
            color : "#00FF00", // Green
            lo : 16,
            hi : 35
        },{
            color : "#FFFF00", // Yellow
            lo : 36,
            hi : 75
        },{
            color : "#FF0000", //red
            lo : 76,
            hi : 1000
        }]
    },
    levelColors: ["#008000", "#FFFF00", "#FFC90e", "#ff0000", "#9400D3"],
    noGradient: true,
    gaugeColor: "#b2b3b5",
    titleFontColor: "#000000",
    titlePosition: "above",
    valueFontColor: "#000000",
    labelFontColor: "#212121",
});