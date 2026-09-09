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

/** Base class for dealing with plotly time charts in the Pallas application. */
class plotlyTimeChartBase {
    /**
     * @param {Object} graphDiv - A HTMLElement object (a DOM node as a result of document.getElementById()) where to create the new plotly chart.
     * @param {String} ylabel - The label of the y axis.
     * @param {Number} plotWidthInMiliseconds - The width of the time-axis in miliseconds.
     */
    constructor(graphDiv, ylabel, plotWidthInMiliseconds = 60 * 1000, maxnumOfDataPointsShown = 3*3600) {
        if (!graphDiv instanceof HTMLElement) {
            throw "Error: Unvalid value for graphDiv. graphDiv must be a HTML element.";
        }
        // Begin Default Parameters
        // Smallest maximum value allowed for the y-axis
        this.smallestMaxYvalue = 10;
        this.scaleFactorForMaxYvalue = 1.1;
        //Time-axis will be updated at each PlotUpdateAxisPeriodTime in  [ms]
        this.PlotUpdateAxisPeriodTime = 30000;
        // End Default Parameters
        
        this.graphDiv = graphDiv;
        this.plotWidthInMiliseconds = plotWidthInMiliseconds;
        this.plotlyChartLayout = {
            xaxis: {
                type: "date",
                title: {
                    text: "Time [h:min:sec]",
                    font: {
                        family: "Bosch Sans Regular",
                        size: 14,
                        color: "#000000"
                    },
                    standoff: 75
                },
            },
            yaxis: {
                title: {
                    text: ylabel,
                    font: {
                        family: "Bosch Sans Regular",
                        size: 14,
                        color: "#000000"
                    }
                },
                autorange: false,
                range: [0, this.smallestMaxYvalue]
            },
            margin: {t: 40}
        };
        this.plotlyChartConfig = {
            modeBarButtonsToRemove: ["toImage", "lasso", "select"],
            scrollZoom: true,
            responsive: true
        };
        this.hovertemplateString = "<extra></extra>%{x|%b %e, %Y, %H:%M:%S}, %{y}";

        this.storedLastPlotUpdateAxisTime = new Date(0); // Set to epoch allows updateAxis() to run during the first run
        this.xdata = [];
        this.ydata = [];
        this.maxnumOfDataPointsShown = maxnumOfDataPointsShown;
    }

    /**
     * Method for updating the plotly plot with one new value
     * @param {Object} timeValue - a Date() object containing the time to be plotted
     * @param {Number} yValue - the value to be plotted
    */
    push(timeValue, yValue) {
        this.xdata.push(new Date(timeValue)); // Creating a deep copy, otherwise time is passed by reference
        this.ydata.push(yValue);
        if(this.xdata.length > this.maxnumOfDataPointsShown){
            this.xdata.shift();
            this.ydata.shift();
        }        
        var dataUpdate = {
            x: [this.xdata],
            y: [this.ydata]
        }
        Plotly.update(this.graphDiv, dataUpdate);
        this.updateYAxisMaxValue();
    }

    /**
     * Method for removing all plot data
    */
     clear() {
        Plotly.purge(this.graphDiv);
        this.xdata = [];
        this.ydata = [];
    }

    /**
     * Method for updating the time and y axis cyclic
    */
    updateAxis() {
        var currentTime = new Date();
        // Initialization of storedLastPlotUpdateAxisTime
        if (this.storedLastPlotUpdateAxisTime == undefined) {
            this.storedLastPlotUpdateAxisTime = new Date(currentTime);
        }
        if ((currentTime - this.storedLastPlotUpdateAxisTime) > this.PlotUpdateAxisPeriodTime) {
            // Update the chart axis
            this.updateXAxisRange();
            this.updateYAxisMinValue();
            this.updateYAxisMaxValue(this.plotWidthInMiliseconds, true);
            this.storedLastPlotUpdateAxisTime.setTime(currentTime.getTime());
        }
    }

    updateXAxisRange(){
        var currentTime = new Date();
        var minTime = new Date(currentTime.getTime() - this.plotWidthInMiliseconds + this.PlotUpdateAxisPeriodTime);
        var maxTime = new Date(currentTime.getTime() + this.PlotUpdateAxisPeriodTime);
        this.plotlyChartLayout.xaxis.range[0] = minTime;
        this.plotlyChartLayout.xaxis.range[1] = maxTime;
        this.plotlyChartLayout.xaxis.autorange = false;
        Plotly.relayout(this.graphDiv, this.plotlyChartLayout);
    }

    updateYAxisMaxValue(timeWindowinMiliseconds = this.plotWidthInMiliseconds, forceUpdate = false) {
        if(this.graphDiv.data[0].y.length <= 0){
            return;
        }
        var currentTime = new Date();
        var pastTime = new Date(currentTime.getTime() - timeWindowinMiliseconds);
        var startIndex = this.graphDiv.data[0].x.findIndex(time => time >= pastTime);
        if(startIndex == -1){
            return;
        }
        var maxYvalue = Math.max(...this.graphDiv.data[0].y.slice(startIndex), this.smallestMaxYvalue);    
        var scaledMaxYvalue = this.scaleFactorForMaxYvalue * maxYvalue;
        var currentMaxYvalue = this.plotlyChartLayout.yaxis.range[1];

        if ((maxYvalue > currentMaxYvalue) || forceUpdate) {
            this.plotlyChartLayout.yaxis.autorange = false;
            this.plotlyChartLayout.yaxis.range[1] = scaledMaxYvalue;
            Plotly.relayout(this.graphDiv, this.plotlyChartLayout);
        }
    }

    updateYAxisMinValue(){
        this.plotlyChartLayout.yaxis.range[0] = 0;
        this.plotlyChartLayout.yaxis.autorange = false;
        Plotly.relayout(this.graphDiv, this.plotlyChartLayout);
    }
}