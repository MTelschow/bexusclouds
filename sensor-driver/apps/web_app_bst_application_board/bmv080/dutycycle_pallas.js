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

const integrationTimeHtml = `<div id="integrationTimeId">
<h2>Integration Time</h2>
<p class="explanation">Moving window over which particulate matter detections are collected and processed.</p>
<div class="setValue">
    <label for="integrationTimeVal">Value: </label>
    <input type="number" id="integrationTimeVal" min="3" max="10" step="1" value="10" required style="width: 40px">
    <label for="integrationTimeVal"> s </label>
</div>
<div class="example-slider-wrapper">
    <div id="integrationTimeSlider" class="mdc-slider mdc-slider--discrete">
        <input class="mdc-slider__input" type="range" min="3" max="10" value="10" name="volume" step="1" aria-label="Integration Time">
        <div class="mdc-slider__track">
            <div class="mdc-slider__track--inactive"></div>
            <div class="mdc-slider__track--active">
                <div class="mdc-slider__track--active_fill"></div>
            </div>
        </div>
        <div class="mdc-slider__thumb">
            <div class="mdc-slider__value-indicator-container" aria-hidden="true">
                <div class="mdc-slider__value-indicator">
                    <span class="mdc-slider__value-indicator-text">
                    50
                </span>
            </div>
        </div>
        <div class="mdc-slider__thumb-knob"></div>
    </div>
</div>
</div>`;
const sensorModeSelectionHtml = `<div id="sensorModeSelectionId">
<h2>Sensor Measurement Mode</h2>
<p class="explanation">Select sensor measurement mode.</p>
<div id="sensorMode" class="mdc-select mdc-select--filled">
    <div class="mdc-select__anchor"
        role="button"
        aria-haspopup="listbox"
        aria-expanded="false"
        aria-labelledby="demo-label demo-selected-text">
    <span class="mdc-select__ripple"></span>
    <span class="mdc-select__selected-text-container">
      <span id="demo-selected-text" class="mdc-select__selected-text">Continuous</span>
    </span>
    <span class="mdc-select__dropdown-icon">
      <svg
          class="mdc-select__dropdown-icon-graphic"
          viewBox="7 10 10 5" focusable="false">
        <polygon
            class="mdc-select__dropdown-icon-inactive"
            stroke="none"
            fill-rule="evenodd"
            points="7 10 12 15 17 10">
        </polygon>
        <polygon
            class="mdc-select__dropdown-icon-active"
            stroke="none"
            fill-rule="evenodd"
            points="7 15 12 10 17 15">
        </polygon>
      </svg>
    </span>
    <span class="mdc-line-ripple"></span>
  </div>

  <div id="sensorModeConfig" class="mdc-select__menu mdc-menu mdc-menu-surface mdc-menu-surface--fullwidth">
    <ul class="mdc-deprecated-list" role="listbox" aria-label="Sensor mode list">
      <li class="mdc-deprecated-list-item mdc-deprecated-list-item--selected" aria-selected="true" data-value="continuous" role="option">
        <span class="mdc-deprecated-list-item__ripple"></span>
        <span class="mdc-deprecated-list-item__text">
          Continuous
        </span>
      </li>
      <li class="mdc-deprecated-list-item" aria-selected="false" data-value="duty_cycling" role="option">
        <span class="mdc-deprecated-list-item__ripple"></span>
        <span class="mdc-deprecated-list-item__text">
          Duty Cycling
        </span>
      </li>
    </ul>
  </div>
</div>
<div id="optionImagePart">
    <img id="optionsImage" src="bmv080/img/DutyCycling.png" alt="Duty Cycling"/>
    <style>
        #optionsImage {
            width: 120%;
            margin: 0 auto;
        }
    </style>
</div>
</div>`;
const dutyCyclingOnTimeHtml = `<div id="dutyCyclingSettingsId">
<h2>Duty Cycling Period</h2>
<p class="explanation">Duration in seconds between two consecutive ON times.</p>
<div class="setValue">
    <label for="backgroundWaitTimeVal">Value: </label>
    <input type="number" id="backgroundWaitTimeVal" min="11" max="3600" step="1" value="300" required style="width: 55px">
    <label for="backgroundWaitTimeVal"> s </label>
</div>
<div id="backgroundWaitTime" class="example-slider-wrapper">
    <div id="backgroundWaitTimeSlider" class="mdc-slider mdc-slider--discrete">
        <input class="mdc-slider__input" type="range" min="5" max="3600" value="300" name="volume" step="1" aria-label="Duty Cycling Period">
        <div class="mdc-slider__track">
            <div class="mdc-slider__track--inactive"></div>
            <div class="mdc-slider__track--active">
                <div class="mdc-slider__track--active_fill"></div>
            </div>
        </div>
        <div class="mdc-slider__thumb">
            <div class="mdc-slider__value-indicator-container" aria-hidden="true">
                <div class="mdc-slider__value-indicator">
                    <span class="mdc-slider__value-indicator-text">
                    50
                </span>
            </div>
        </div>
        <div class="mdc-slider__thumb-knob"></div>
    </div>							
</div>
</div>`;

var sensorModeSelectionElement = document.getElementById("settingsContent");
sensorModeSelectionElement.insertAdjacentHTML("afterbegin", sensorModeSelectionHtml);
var intgTimeElement = document.getElementById("sensorModeSelectionId");
intgTimeElement.insertAdjacentHTML("afterbegin", integrationTimeHtml);

var defaultIntegrationTime = 10;
var defaultBackgroundWaitTime = 300;
var defaultIsDutyCyclingEnabled = 0;

var minIntegrationTime = 3;
var maxIntegrationTime = 10;
var minDutyCyclingPeriod = minIntegrationTime + 2;
var maxBackgroundWaitTime = 3600;

var backgroundWaitTimeSlider;
var backgroundWaitTimeVal;
var sensorMode;
var sensorModeOptions;
var discreteSlider;
var discreteCommittedValue;

var loadDefaultSettingsUser = generateDefaultSettingsOnFirstLoad;

generateDefaultSettingsOnFirstLoad = function() {
    if( (localStorage.getItem('settingsInitialized')==null) || (localStorage.getItem('SettingsVersion') != settingsVersion) )
    {
        localStorage.setItem('IntegrationTime', defaultIntegrationTime);
        localStorage.setItem('DutyCyclingPeriod', defaultBackgroundWaitTime);
        localStorage.setItem('IsDutyCyclingEnabled', 0);
	}

    loadDefaultSettingsUser();
}

addDutyCyclingSettings = function(){

    if(backgroundWaitTimeSlider==null)
    {
        var dutyCyclingOnTimeElement = document.getElementById("sensorModeSelectionId");
        dutyCyclingOnTimeElement.insertAdjacentHTML("beforeend", dutyCyclingOnTimeHtml);

        /* --------------------- Background wait time ------------------------ */

        backgroundWaitTimeVal = document.getElementById('backgroundWaitTimeVal');
        var backgroundWaitTimeElememt = document.getElementById('backgroundWaitTimeSlider');
        if(backgroundWaitTimeSlider!=null) //Destroying existing slider object to avoid multiple subscriptions on window is reloaded
        {
            backgroundWaitTimeSlider.destroy();
        }
        backgroundWaitTimeSlider = new mdc.slider.MDCSlider(backgroundWaitTimeElememt);

        var currentIntegrationTime = localStorage.getItem('IntegrationTime');
        var minDutyCyclingPeriodLocal = String(Number(currentIntegrationTime) + 2);
        if(Number(minDutyCyclingPeriodLocal) < minDutyCyclingPeriod)
        {
            minDutyCyclingPeriodLocal = minDutyCyclingPeriod;
        }
        backgroundWaitTimeSlider.min = Number(minDutyCyclingPeriodLocal);
        backgroundWaitTimeVal.min = Number(minDutyCyclingPeriodLocal);

        var backWaitvalue = localStorage.getItem('DutyCyclingPeriod');
        // In case the current duty cycling period is smaller than the (current integration time + 2s), it must reset with current integration time
        if (Number(backWaitvalue) <= Number(minDutyCyclingPeriodLocal))
        {
            backgroundWaitTimeVal.textContent = minDutyCyclingPeriodLocal + " s";
            backgroundWaitTimeVal.value = minDutyCyclingPeriodLocal;
            backgroundWaitTimeVal.min = Number(minDutyCyclingPeriodLocal);
            backgroundWaitTimeSlider.setValue(Number(minDutyCyclingPeriodLocal));
            backgroundWaitTimeSlider.min = Number(minDutyCyclingPeriodLocal);
            localStorage.setItem('DutyCyclingPeriod', minDutyCyclingPeriodLocal);
        }
        else
        {
            backgroundWaitTimeVal.textContent = backWaitvalue + " s";
            backgroundWaitTimeVal.value = backWaitvalue;
            backgroundWaitTimeSlider.setValue(Number(backWaitvalue));
        }
        backgroundWaitTimeElememt.disabled = true;
        
        /* ----------------- Event Listener: Wait time ------------------- */

        console.log("Subscribing background wait time Event Listeners");
        addMultipleEventListenersToSlider(backgroundWaitTimeSlider, ['MDCSlider:input', 'MDCSlider:change'],  function(event) {
            currentBackgroundWaitTime = backgroundWaitTimeSlider.getValue();
            var currentIntegrationTime = localStorage.getItem('IntegrationTime');
            var minDutyCyclingPeriodLocal = Number(currentIntegrationTime) + 2;
            if (currentBackgroundWaitTime < minDutyCyclingPeriodLocal)
            {
                currentBackgroundWaitTime = minDutyCyclingPeriodLocal;
            }    
            /* update text box value when the slider is changed */
            backgroundWaitTimeVal.textContent = currentBackgroundWaitTime + " s";
            backgroundWaitTimeVal.value = currentBackgroundWaitTime;
            backgroundWaitTimeSlider.min = Number(minDutyCyclingPeriodLocal);
            backgroundWaitTimeSlider.setValue(Number(currentBackgroundWaitTime));
            localStorage.setItem('DutyCyclingPeriod', currentBackgroundWaitTime);
            if (event.type == 'MDCSlider:change') {
                console.log(currentBackgroundWaitTime);
            }
        });
        /* update slider value when the text box is changed */
        addMultipleEventListeners(backgroundWaitTimeVal, ['input', 'change'], function(event) {
            if (backgroundWaitTimeVal.validity.rangeUnderflow) {
                backgroundWaitTimeVal.setCustomValidity("Value must be an integer between 5s and 3600s and it must be larger than the current integration time.");
                var currentIntegrationTime = localStorage.getItem('IntegrationTime');
                var minDutyCyclingPeriodLocal = String(Number(currentIntegrationTime) + 2);
                if (minDutyCyclingPeriodLocal < minDutyCyclingPeriod)
                {
                    minDutyCyclingPeriodLocal = minDutyCyclingPeriod;
                }
                if (event.type == 'change') {
                    backgroundWaitTimeVal.value = minDutyCyclingPeriodLocal;
                }
            }
            else if (backgroundWaitTimeVal.validity.rangeOverflow) {
                backgroundWaitTimeVal.setCustomValidity("Value must be an integer between 5s and 3600s and it must be larger than the current integration time.");
                if (event.type == 'change') {
                    backgroundWaitTimeVal.value = maxBackgroundWaitTime;
                }
            }
            else if (backgroundWaitTimeVal.validity.stepMismatch) {
                backgroundWaitTimeVal.setCustomValidity("Value must be an integer between 5s and 3600s and it must be larger than the current integration time.");
                if (event.type == 'change') {
                    backgroundWaitTimeVal.value = Math.round(backgroundWaitTimeVal.value);
                }
            }
            else if (backgroundWaitTimeVal.validity.valueMissing) {
                backgroundWaitTimeVal.setCustomValidity("Please fill out this field.");
                if (event.type == 'change') {
                    backgroundWaitTimeVal.setCustomValidity("A value is needed for this field. Setting value to the default.");
                    backgroundWaitTimeVal.value = defaultBackgroundWaitTime;
                    backgroundWaitTimeVal.validity.valueMissing = false;
                }
            }
            else {
                backgroundWaitTimeVal.setCustomValidity("");
            }
            backgroundWaitTimeVal.reportValidity();
            backgroundWaitTimeSlider.setValue(Number(backgroundWaitTimeVal.value));
            localStorage.setItem('DutyCyclingPeriod', backgroundWaitTimeVal.value);
        });
    }
}

removeDutyCyclingSettings = function(){
    
    if(backgroundWaitTimeSlider!=null) //Destroying existing slider object to avoid multiple subscriptions on window is reloaded
    {
        var dutyCyclingOnTimeElement = document.getElementById("dutyCyclingSettingsId");
        dutyCyclingOnTimeElement.remove(dutyCyclingOnTimeHtml);
        backgroundWaitTimeSlider.destroy();
        backgroundWaitTimeSlider=null;
        backgroundWaitTimeVal=null;
    }
}

var initSlidersUser = initSliders;

//Sliders must be initialized while being visible
initSliders = function(){
	
	/* --------------------- Integration Time slider ------------------------ */
	discreteCommittedValue = document.getElementById('integrationTimeVal');
	var discreteSliderEl = document.getElementById('integrationTimeSlider');

	if(discreteSlider!=null) //Destroying existing slider object to avoid multiple subscriptions on window is reloaded
    {
         discreteSlider.destroy();
    }
	discreteSlider = new mdc.slider.MDCSlider(discreteSliderEl);
	
	var value = localStorage.getItem('IntegrationTime');
	discreteCommittedValue.textContent = value +" s";
    discreteSlider.setValue(Number(value));
    discreteCommittedValue.value = value;

    /* update text box value when the slider is changed */
    addMultipleEventListenersToSlider(discreteSlider, ['MDCSlider:input', 'MDCSlider:change'], function() {
        discreteCommittedValue.textContent = discreteSlider.value +" s";
        discreteCommittedValue.value = discreteSlider.getValue();
        localStorage.setItem('IntegrationTime', discreteSlider.getValue());
    });
    /* update slider value when the text box is changed */
    addMultipleEventListeners(discreteCommittedValue, ['input', 'change'], function(event) {
        if (discreteCommittedValue.validity.rangeUnderflow) {
            discreteCommittedValue.setCustomValidity("Value must be an integer between 3s and 10s.");
            if (event.type == 'change') {
                discreteCommittedValue.value = minIntegrationTime;
            }
        }
        else if (discreteCommittedValue.validity.rangeOverflow) {
            discreteCommittedValue.setCustomValidity("Value must be an integer between 3s and 10s.");
            if (event.type == 'change') {
                discreteCommittedValue.value = maxIntegrationTime;
            }
        }
        else if (discreteCommittedValue.validity.stepMismatch) {
            discreteCommittedValue.setCustomValidity("Value must be an integer between 3s and 10s.");
            if (event.type == 'change') {
                discreteCommittedValue.value = Math.round(discreteCommittedValue.value);
            }
        }
        else if (discreteCommittedValue.validity.valueMissing) {
            discreteCommittedValue.setCustomValidity("Please fill out this field.");
            if (event.type == 'change') {
                discreteCommittedValue.setCustomValidity("A value is needed for this field. Setting value to the default.");
                discreteCommittedValue.value = defaultIntegrationTime;
                discreteCommittedValue.validity.valueMissing = false;
            }
        }
        else {
            discreteCommittedValue.setCustomValidity("");
        }
        discreteCommittedValue.reportValidity();
        discreteSlider.setValue(Number(discreteCommittedValue.value));
        localStorage.setItem('IntegrationTime', discreteCommittedValue.value);
    });

    /* --------------------- Sensor running mode ------------------------ */

    if(sensorMode!=null) //Destroying existing dropdown object to avoid multiple subscriptions on window is reloaded
    {
        sensorMode.destroy();
    }
    sensorMode = new mdc.select.MDCSelect(document.querySelector('#sensorMode'));
    
    sensorModeOptions = sensorMode.menuItemValues;
    sensorModeOptionsPic = document.getElementById("optionsImage");

    if(localStorage.getItem('IsDutyCyclingEnabled') == "0") { // Indexing starts with 0
        sensorMode.value = "continuous";
        removeDutyCyclingSettings();
        sensorModeOptionsPic.src = "bmv080/img/continuous.png";
        sensorModeOptionsPic.alt = "continuous";
    }
    else if(localStorage.getItem('IsDutyCyclingEnabled') == "1") {
        sensorMode.value = "duty_cycling";
        addDutyCyclingSettings();
        sensorModeOptionsPic.src = "bmv080/img/DutyCycling.png";
        sensorModeOptionsPic.alt = "Duty Cycling";
    }
    
    sensorMode.listen('MDCSelect:change', () => {
            
        if(sensorMode.value == "continuous"){
            localStorage.setItem('IsDutyCyclingEnabled', 0);
            removeDutyCyclingSettings();
            sensorModeOptionsPic.src = "bmv080/img/continuous.png";
            sensorModeOptionsPic.alt = "continuous";
            // enable the measurement algorithm selection
            if(measurementAlgorithmFlag!=null)
            {
                measurementAlgorithmFlag.disabled = false;
                // use the previously selected value for measurementAlgorithm
                localStorage.setItem('MeasurementAlgorithm', measurementAlgorithmFlag.value);
            }
        }
        else{
            localStorage.setItem('IsDutyCyclingEnabled', 1);
            addDutyCyclingSettings();
            sensorModeOptionsPic.src = "bmv080/img/DutyCycling.png";
            sensorModeOptionsPic.alt = "Duty Cycling";
            // disable the measurement algorithm selection
            if(measurementAlgorithmFlag!=null)
            {
                measurementAlgorithmFlag.disabled = true;
                measurementAlgorithmFlag.value = "1";
                localStorage.setItem('MeasurementAlgorithm', measurementAlgorithmFlag.value);
            }
        }
        console.log(`Selected sensor mode option ${sensorMode.value}`);
        console.log("IsDutyCyclingEnabled: ", localStorage.getItem('IsDutyCyclingEnabled') );
    });

	if(!slidersInitialized)
    {
        addMultipleEventListenersToSlider(discreteSlider, ['MDCSlider:input', 'MDCSlider:change'],  function(event) {
            if(sensorMode.value == "continuous") {
                return;
            }
            var currentDutyCyclingPeriod = 0;
            if (event.type == 'MDCSlider:input') {
                discreteCommittedValue.textContent = discreteSlider.value +" s";
                discreteCommittedValue.value = discreteSlider.getValue();
                currentDutyCyclingPeriod = Number(localStorage.getItem('DutyCyclingPeriod'));
            }
            else {
                currentDutyCyclingPeriod = backgroundWaitTimeSlider.getValue();
            }
            // In case the current duty cycling period is smaller than the (current integration time + 3s), it must reset with current integration time
            var minDutyCyclingPeriodLocal = String(Number(discreteSlider.getValue()) + 2);
            if (Number(minDutyCyclingPeriodLocal) < minDutyCyclingPeriod)
            { 
                minDutyCyclingPeriodLocal = minDutyCyclingPeriod;
            }

            if (currentDutyCyclingPeriod <= Number(minDutyCyclingPeriodLocal))
            {
                backgroundWaitTimeSlider.setValue(Number(minDutyCyclingPeriodLocal));
                backgroundWaitTimeVal.textContent = minDutyCyclingPeriodLocal + " s";
                backgroundWaitTimeVal.value = Number(minDutyCyclingPeriodLocal);
                localStorage.setItem('DutyCyclingPeriod', Number(minDutyCyclingPeriodLocal));
            }
            backgroundWaitTimeSlider.min = Number(minDutyCyclingPeriodLocal);
            backgroundWaitTimeVal.min = Number(minDutyCyclingPeriodLocal);
            localStorage.setItem('IntegrationTime', discreteSlider.getValue());
            if (event.type == 'MDCSlider:change') {
                console.log(discreteSlider.value);
            }
        });
        
        //// the same for the text box
        addMultipleEventListeners(discreteCommittedValue, ['input', 'change'], function(event) {
            if(sensorMode.value == "continuous") {
                return;
            }
            var currentDutyCyclingPeriod = 0;
            if (event.type == 'input') {
                discreteSlider.setValue(Number(discreteCommittedValue.value));
                currentDutyCyclingPeriod = Number(localStorage.getItem('DutyCyclingPeriod'));
            }
            else {
                currentDutyCyclingPeriod = backgroundWaitTimeSlider.getValue();
            }
            // In case the current duty cycling period is smaller than the current integration time, it must reset with current integration time
            var minDutyCyclingPeriodLocal = String(Number(discreteCommittedValue.value) + 2);
            if(minDutyCyclingPeriodLocal < minDutyCyclingPeriod)
            {
                minDutyCyclingPeriodLocal = minDutyCyclingPeriod;
            }
            if (currentDutyCyclingPeriod <= Number(minDutyCyclingPeriodLocal))
            {
                backgroundWaitTimeSlider.setValue(Number(minDutyCyclingPeriodLocal));
                backgroundWaitTimeVal.textContent = minDutyCyclingPeriodLocal + " s";
                backgroundWaitTimeVal.value = Number(minDutyCyclingPeriodLocal);
                localStorage.setItem('DutyCyclingPeriod', minDutyCyclingPeriodLocal);
            }
            backgroundWaitTimeSlider.min = Number(minDutyCyclingPeriodLocal);
            backgroundWaitTimeVal.min = Number(minDutyCyclingPeriodLocal);
            localStorage.setItem('IntegrationTime', discreteCommittedValue.value);
            if (event.type == 'change') {
                console.log(discreteCommittedValue.value);
            }
        });
    }
	
	initSlidersUser();
}
var initSettingsUser = initSettings;

initSettings = function(){

	initSettingsUser();
}

var disableSettingsPallas = disableSettings;

disableSettings = function() {

    if(backgroundWaitTimeSlider!=null)
    {
        backgroundWaitTimeSlider.setDisabled(true);
        backgroundWaitTimeVal.disabled = true;
    }

if (sensorMode && 'disabled' in sensorMode) {
    sensorMode.disabled = true;
}
	
	disableSettingsPallas();
	if(slidersInitialized){
		discreteSlider.setDisabled(true);
        discreteCommittedValue.disabled = true;
	}
}

var enableSettingsPallas = enableSettings;

enableSettings = function() {

    if(backgroundWaitTimeSlider!=null)
    {
        backgroundWaitTimeSlider.setDisabled(false);
        backgroundWaitTimeVal.disabled = false;
    }
    
    if (sensorMode && 'disabled' in sensorMode) {
        sensorMode.disabled = false;
    }
	
	enableSettingsPallas();
	if(slidersInitialized){
		discreteSlider.setDisabled(false);
        discreteCommittedValue.disabled = false;
  }
}
