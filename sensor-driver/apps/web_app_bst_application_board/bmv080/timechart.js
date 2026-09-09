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

var pmElementPM25 = document.getElementById("pmChartPM25");
var pmElementPM1 = document.getElementById("pmChartPM1");
var pmElementPM10 = document.getElementById("pmChartPM10");
today = new Date();

var s2ms = 1000; // Conversion from seconds to miliseconds
var maxNumOfPlotValuesOnScreen = 60;
var continuousPlotPeriod = 1; // [s]
var minDeltaYaxis = 1;
var storedValidValue = {};
var measurementStartTime;
var useSystemTime = true;
var chartPM25, chartPM1, chartPM10;
[chartPM25, chartPM1, chartPM10] = create_new_plotly_time_chart_obj();

function create_new_plotly_time_chart_obj() {
    if (localStorage.getItem('IsDutyCyclingEnabled') == 1) {
        var chart1 = new plotlyTimeChartMarkers(pmElementPM1, "PM1 [µg/m³]", undefined, undefined, plotWidthInMiliseconds = maxNumOfPlotValuesOnScreen * localStorage.getItem('DutyCyclingPeriod') * s2ms);
        var chart25 = new plotlyTimeChartMarkers(pmElementPM25, "PM2.5 [µg/m³]", undefined, undefined, plotWidthInMiliseconds = maxNumOfPlotValuesOnScreen * localStorage.getItem('DutyCyclingPeriod') * s2ms);
        var chart10 = new plotlyTimeChartMarkers(pmElementPM10, "PM10 [µg/m³]", undefined, undefined, plotWidthInMiliseconds = maxNumOfPlotValuesOnScreen * localStorage.getItem('DutyCyclingPeriod') * s2ms);
    } else {
        var chart1 = new plotlyTimeChartLines(pmElementPM1, "PM1 [µg/m³]", undefined, undefined, plotWidthInMiliseconds = maxNumOfPlotValuesOnScreen * continuousPlotPeriod * s2ms);
        var chart25 = new plotlyTimeChartLines(pmElementPM25, "PM2.5 [µg/m³]", undefined, undefined, plotWidthInMiliseconds = maxNumOfPlotValuesOnScreen * continuousPlotPeriod * s2ms);
        var chart10 = new plotlyTimeChartLines(pmElementPM10, "PM10 [µg/m³]", undefined, undefined, plotWidthInMiliseconds = maxNumOfPlotValuesOnScreen * continuousPlotPeriod * s2ms);
    }
    return [chart25, chart1, chart10];
}

function loadTimeline() {
    $("#headline").text("Past Readings");
    $(".tab").css("display", "none");
    $("#chartContainer").css("display", "flex");
    document.getElementById("mainmenu").classList.remove("mdc-drawer--open");
}
function updateCharts(sample, currentTime) {
    if (Controller.showCharts) {
        chartPM1.push(currentTime, sample[0]);
        chartPM25.push(currentTime, sample[1]);
        chartPM10.push(currentTime, sample[2]);
        //update the gauge chart
        gaugePM1.refresh(convertToLogScale(sample[0].toFixed(0) * 1.0));
        gaugePM25.refresh(convertToLogScale(sample[1].toFixed(0) * 1.0)); //toFixed will reference the number of floating point values printed. 0 -> no floating point suffix
        gaugePM10.refresh(convertToLogScale(sample[2].toFixed(0) * 1.0));
    }
    else {
        chartPM1.push(currentTime, null);
        chartPM25.push(currentTime, null);
        chartPM10.push(currentTime, null);
    }
    chartPM1.updateAxis();
    chartPM25.updateAxis();
    chartPM10.updateAxis();
}

function clearCharts() {
    chartPM1.clear();
    chartPM25.clear();
    chartPM10.clear();
    [chartPM25, chartPM1, chartPM10] = create_new_plotly_time_chart_obj();
}