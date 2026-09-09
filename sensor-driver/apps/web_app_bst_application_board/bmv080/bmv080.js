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

let connectionType = null;
let sendCommandQueue = Promise.resolve();

function loadHelp() {
    $("#headline").text("Help");
    var elem = $("#helpContent");
    $(".tab").css("display", "none");
    $("#helpContent").css("display", "block");
    document.getElementById("mainmenu").classList.remove("mdc-drawer--open");
}

function loadVersion() {
    $("#headline").text("Version");
    var elem = $("#versionContent");
    $(".tab").css("display", "none");
    elem.css("display", "block");
    document.getElementById("mainmenu").classList.remove("mdc-drawer--open");
}

function deleteLogFiles() {
    const dialog = new mdc.dialog.MDCDialog(document.querySelector('#deleteDialog'));
    dialog.listen('MDCDialog:closing', function (e) {
        if (e.detail.action == "yes") {
            Controller.sendJSON({ "action": "delete" });
        }
    });
    dialog.open();
}

var ControllerClass = function () {
    loadStaticDataTypes();
    loadGauge();
    console.log("ControllerClass constructor")
    console.log("startup")
    
    this.state = "standby"
    this.isConnected = false;
    this.version = {};
    this.flavor = "user";
    this.sample = {};
    this.showCharts = true;
    this.version.androidVersion = "not-initialized";
    gaugePM25.deactivateGauge();
    gaugePM10.deactivateGauge();
    gaugePM1.deactivateGauge();

};

ControllerClass.prototype.sendCommand = async function (input) {
    await writeData(input);

    await new Promise(resolve => setTimeout(resolve, 500)); // wait 500ms
}

ControllerClass.prototype.queueSendCommand = function (input) {
    sendCommandQueue = sendCommandQueue.then(() => this.sendCommand(input));

    return sendCommandQueue;
}

ControllerClass.prototype.confirmError = function (event) {
    if (event.detail.action == "ok") {
        this.state = "standby";
        this.doStop();
    }
};

ControllerClass.prototype.showError = function (errorMessage, displayAbort = false) {
    this.state = "error";
    $("#error-content").text(errorMessage);
    if (displayAbort) {
        $(".abortButton").css("display", "block");
    } else {
        $(".abortButton").css("display", "none");
    }
    if (this.errorDialog == undefined) {
        const dialog = new mdc.dialog.MDCDialog(document.querySelector('#errorDialog'));
        dialog.scrimClickAction = "";
        dialog.listen('MDCDialog:closing', this.confirmError.bind(this));
        this.errorDialog = dialog;
    }
    this.errorDialog.open();
}
ControllerClass.prototype.updateAppVersion = function (update) {
    var shortversion;
    if (update != undefined) {
        this.version = update;

        this.flavor = this.version.flavor;
        shortversion = this.version.tag;

        if (this.version.hash != undefined) {
            shortversion += "-" + this.version.hash;
            if (this.version.dirty) {
                shortversion += "M";
            }
        }
        else {
            shortversion = this.version.androidVersion;
        }
    }
    else {
        shortversion = "N/A";
    }

    console.log("Version:" + shortversion);
    $("#androidVersionLabel").text(this.version.androidVersion);
    $("#currentVersion").text("Version " + this.version.androidVersion);
};

ControllerClass.prototype.updateHardwareVersion = function (hwVersion) {
    $("#sensorStackVersionLabel").text(hwVersion.SensorStackVersion);
    $("#asicTrackerIdChannel1Label").text(hwVersion.AsicTrackerIdChannel1)
};


ControllerClass.prototype.doStart = function () {
    console.log("doStart");
    clearCharts();
    gaugePM25.activateGauge();
    gaugePM10.activateGauge();
    gaugePM1.activateGauge();

    measurementStartTime = new Date();
    this.state = "starting";
    // clear array with stored measurement data in place
    csvStorage.length = 0;
};

ControllerClass.prototype.sendSettings = function () {
    var settings = getSettings();
    this.obstructionDetection = settings["ObstructionDetection"];
    console.log(settings);
    var settingsString = "bmv";
    var settingsCommand = settingsString + ` -i -v set_int_time ${settings.IntegrationTime} set_obs_notify ${settings.ObstructionDetection} set_mode ${settings.IsDutyCyclingEnabled} set_algo ${settings.MeasurementAlgorithm}`
    if (settings.IsDutyCyclingEnabled == "0") {
        this.queueSendCommand(settingsCommand);
    } else {
        this.queueSendCommand(settingsCommand + ` set_duty_cycle ${settings.DutyCyclingPeriod}`);
    }
};


ControllerClass.prototype.doStop = function () {
    try {
        this.sendCommand("cfgse 239:0");
    } catch (e) {
        console.error("Error sending stop command:", e);
    }
    console.log("doStop");
    gaugePM25.deactivateGauge();
    gaugePM10.deactivateGauge();
    gaugePM1.deactivateGauge();
    this.state = "standby";
    removeObstruction();
    var sizeCsvStorage = csvStorage.length;
    if (sizeCsvStorage > 0) {
        const confirmedFileExport = confirm("Would you like to export the measured data to a file?");
        if (confirmedFileExport) {
            exportData();
        };
    };
    document.getElementById("drawerStreamingText").innerHTML = "Start Streaming";
    // ensure that the settings are enabled again after a measurement is stopped
	enableSettings();
};

ControllerClass.prototype.button = function (name) {
    if (name == "change") {
        if (this.state == "standby") {
            this.doStart();
        }
        else {
            this.doStop();
        }
    }
    if (name == "Gauge") {
        loadGauge();
    }
    if (name == "Timeline") {
        loadTimeline();
    }
    if (name == "Settings") {
        loadSettings();
        if (this.state == "running") {
            disableSettings();
        }
        else {
            enableSettings();
        }
    }
    if (name == "Help") {
        loadHelp();
    }
    if (name == "About") {
        loadLicenses();
    }
    if (name == "Version") {
        console.log("Version button pressed");
        loadVersion();
    }
};

ControllerClass.prototype.connect = function (type, domElement) {
    connectionType = type;
    let connectCheck = null
    if (connectionType === 1) {
        connectCheck = connectSerial(domElement);
    } else if (connectionType === 0) {
        connectCheck = connectBLE(handleData, domElement);
    }
    connectCheck.then(async () => {
        if (connectionType === 0) {
            alert("Device connected. \nPlease note that USB connection is recommended. \nBLE feature is in Beta stage and may not work as expected.");
        } else {
           alert("Device connected.");
        }

        this.doStart();
        handleSchemaData('1.1\r\n239: Particulate matter: 38: f,f,f,u8,u8,f,f,f,f,f,f: pm1,pm25,pm10,obs,range,n_pm1,n_pm25,n_pm10,r0,r1,r2: -1.000000000000000: -1.000000000000000: na\r\n\r\n\r\n');
        if (connectionType === 1) {
            await readDataSerial(handleData);
        }
    }).catch((error) => {
        console.error("Failed to connect to Device:", error);
        if (error && error.name === "NetworkError") {
        alert("Failed to connect to device. Please power cycle the Application Board and try again.");
    }
    });
};

ControllerClass.prototype.disconnect = function () {
    this.doStop();
    let disconnectCheck = null
    if (connectionType === 1) {
        disconnectCheck = disconnectSerial();
    } else if (connectionType === 0) {
        disconnectCheck = disconnectBLE();
    }
    disconnectCheck.then(() => {
        alert("Device disconnected.");
    }).catch((error) => {
        console.error("Failed to disconnect from device:", error);
    });
}

// Make the function wait until the connection is made...
ControllerClass.prototype.waitForSocketConnection = function (socket, callback) {

    var myTimeout = function () {
        if (socket.readyState === 1) {
            this.failcounter = 0;
            if (callback != null) {
                callback();
            }
        } else {
            if (this.failcounter === undefined) {
                this.failcounter = 0;
            }
            else {
                this.failcounter++
            }
            console.log("wait for connection...")
            if (this.failcounter < 10) {
                this.waitForSocketConnection(socket, callback);
            }
        }

    }.bind(this);
    //setTimeout looses scope
    setTimeout(myTimeout, 50); // wait 5 milisecond for the connection...
};

var Controller = new ControllerClass();

// Function to disable web-view text selection
$.fn.extend({
    disableWebViewTextSelection: function () {
        this.each(function () {
            this.onselectstart = function () { return false; };
        });
    }
});


$(function () {
    $(this).disableWebViewTextSelection();
});
