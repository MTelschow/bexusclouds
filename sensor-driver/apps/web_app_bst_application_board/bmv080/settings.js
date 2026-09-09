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

var settingsVersion = "1.0.0"; // set setting version to the same as the web app version
var defaultObstructionDetectionFlag = 1; // 0 => OFF; 1 = ON
var obstructionDetectionFlag;
var defaultMeasurementAlgorithmFlag = 3;
var measurementAlgorithmFlag;
var slidersInitialized = false;

document.getElementById("androidVersionLabel").innerText = settingsVersion;

/* function for adding multiple event listeners to the same element */
function addMultipleEventListeners(element, events, handler) {
    events.forEach(ev => element.addEventListener(ev, handler));
}

function addMultipleEventListenersToSlider(element, events, handler) {
    events.forEach(ev => element.listen(ev, handler));
}

//Used to toggle advanced settings section.
function toggleAdvancedSettings() {
    var x = document.getElementById("ObstructionDetectionSection");
    if (x.style.display === "none") {
      x.style.display = "block";
      x.style.marginBottom = "50px"
    } else {
      x.style.display = "none";
    }
    var x = document.getElementById("MeasurementAlgorithmSection");
    if (x.style.display === "none") {
      x.style.display = "block";
      x.style.marginBottom = "50px"
    } else {
      x.style.display = "none";
    }
}

function getSettings()
{
	generateDefaultSettingsOnFirstLoad();
	settings = {};
	for (var i = 0; i < localStorage.length; i++){
		var key = localStorage.key(i);
		if(key != 'settingsInitialized')
		{
			settings[key] = localStorage.getItem(key);
		}
	}
	
	return settings;
}

function generateDefaultSettingsOnFirstLoad()
{
    //If settingsInitialized or if Settings version changed, was not set then reset all variables in local storage
    if( (localStorage.getItem('settingsInitialized')==null) || (localStorage.getItem('SettingsVersion') != settingsVersion) ) {
       localStorage.setItem('ObstructionDetection', defaultObstructionDetectionFlag);
       localStorage.setItem('MeasurementAlgorithm', defaultMeasurementAlgorithmFlag);
       localStorage.setItem('SettingsVersion', settingsVersion);
       localStorage.setItem('settingsInitialized', true);
    }
}

function loadSettings(){
    
    $("#headline").text("Settings");
    $(".tab").css("display","none");
	$("#settingsContent").css("display","block");

	if(!slidersInitialized){
        // if there is a version change ensure that the settings stored in the local app data cache are not used
        if( (localStorage.getItem('settingsInitialized')==null) || (localStorage.getItem('SettingsVersion') != settingsVersion) ) {
            localStorage.clear()
        }
		initSettings();
	}
	initSliders();

    document.getElementById("mainmenu").classList.remove("mdc-drawer--open");
}

//Sliders must be initialized while being visible
function initSliders()
{
    if(obstructionDetectionFlag!=null)
    {
        obstructionDetectionFlag.destroy();
    }
    obstructionDetectionFlag = new mdc.select.MDCSelect(document.querySelector('#obstructionDetection'));

    var obstructionDetectionFlagOptions = ["Obstruction notifier OFF", "Obstruction notifier ON"];

    if(localStorage.getItem('ObstructionDetection') == "0") { // Indexing starts with 0
        obstructionDetectionFlag.value = "0";
    }
    else if(localStorage.getItem('ObstructionDetection') == "1") { // Indexing starts with 0
        obstructionDetectionFlag.value = "1";
    }

    if(measurementAlgorithmFlag!=null)
    {
        measurementAlgorithmFlag.destroy();
    }
    measurementAlgorithmFlag = new mdc.select.MDCSelect(document.querySelector('#measurementAlgorithm'));

    var measurementAlgorithmFlagOptions = ["Fast Response Time", "Balanced", "High Precision"];

    if(localStorage.getItem('MeasurementAlgorithm') == "1") { 
        measurementAlgorithmFlag.value = "1";
    }
    else if(localStorage.getItem('MeasurementAlgorithm') == "2") {
        measurementAlgorithmFlag.value = "2";
    }
    else if(localStorage.getItem('MeasurementAlgorithm') == "3") {
        measurementAlgorithmFlag.value = "3";
    }

    if(!slidersInitialized)
    {
        /* ----------------- Obstruction Detection Flag Event Listener ------------------- */

        obstructionDetectionFlag.listen('MDCSelect:change', () => {
            localStorage.setItem('ObstructionDetection', obstructionDetectionFlag.value);
            console.log(`Selected option ${obstructionDetectionFlag.value} corresponds to 
                "${obstructionDetectionFlagOptions[Number(obstructionDetectionFlag.value)]}"`);
        });

        /* ----------------- Measurement Algorithm Flag Event Listener ------------------- */

        measurementAlgorithmFlag.listen('MDCSelect:change', () => {
            localStorage.setItem('MeasurementAlgorithm', measurementAlgorithmFlag.value);
            console.log(`Selected option ${measurementAlgorithmFlag.value} corresponds to 
                "${measurementAlgorithmFlagOptions[Number(measurementAlgorithmFlag.value)-1]}"`);
        });

        slidersInitialized = true;
	}

    // disable the measurement algorithm selection for duty cycling
    if(localStorage.getItem('IsDutyCyclingEnabled') == "1") {
        measurementAlgorithmFlag.disabled = true;
        measurementAlgorithmFlag.value = "1";
        localStorage.setItem('MeasurementAlgorithm', measurementAlgorithmFlag.value);
    }
}

function initSettings(){
    generateDefaultSettingsOnFirstLoad();
    toggleAdvancedSettings();
}

function disableSettings()
{
    if(slidersInitialized){
        obstructionDetectionFlag.disabled = true;
        measurementAlgorithmFlag.disabled = true;
    }
}

function enableSettings()
{
    if(slidersInitialized){
        obstructionDetectionFlag.disabled = false;
        measurementAlgorithmFlag.disabled = false;
        // disable the measurement algorithm selection for duty cycling
        if(localStorage.getItem('IsDutyCyclingEnabled') == "1") {
            measurementAlgorithmFlag.disabled = true;
            measurementAlgorithmFlag.value = "1";
            localStorage.setItem('MeasurementAlgorithm', measurementAlgorithmFlag.value);
        }
    }
}
